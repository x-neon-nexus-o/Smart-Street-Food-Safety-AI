"""Translation integration: canonical English in, vendor language out.

FAILURE POLICY
--------------
Translation is an enhancement, never a gate. If the model is missing, still
downloading, too slow, or misconfigured, the scan still succeeds: the caller
gets the original English alongside `translated=False` and a `warning`, and
the UI shows a small "showing English" banner. A vendor standing at their
stall holding a phone must never lose a scan verdict because a translation
step had a bad minute.

PROVIDERS
---------
`TRANSLATION_PROVIDER` selects the implementation, the same swap-point pattern
as `OCR_PROVIDER` and `CV_PROVIDER`.

  * "indictrans2" (default) -- a local AI4Bharat IndicTrans2 model, run
    in-process. No API key, no quota, no network after the one-time download.

Google Cloud Translation used to live here and has been removed: it required
billing and a credential, it sent label text to a third party, and the local
model is good enough for the vendor languages this app offers. Google Cloud
*Vision* is untouched and still performs OCR -- see ocr_client; the two no
longer share any credential.

LANGUAGE CODES
--------------
The application speaks `en` / `hi` / `mr` (`settings.SUPPORTED_LANGUAGES`).
The model wants FLORES-200 tags (`eng_Latn` / `hin_Deva` / `mar_Deva`). The
mapping lives in `indic_text.APP_TO_TAG` and nowhere else.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from app.core.config import settings
from app.integrations import indic_text
from app.integrations.indictrans2 import IndicTrans2Runtime
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Map short codes to full language names for Gemini prompts
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "or": "Odia",
    "as": "Assamese",
}

# English is the canonical source language. Translating it to itself would be
# a pointless model call.
SOURCE_LANGUAGE = "en"


@dataclass
class TranslationResult:
    text: str
    translated: bool
    """False when the original text was returned unchanged -- because the
    target is English, translation is disabled, the language is unsupported,
    or the provider failed."""

    warning: Optional[str] = None
    """Set only on provider failure, so the UI can show a fallback banner.
    None for the ordinary "target is English" case, which is not a failure."""

    provider: str = "indictrans2"


class _TranslationCache:
    """Bounded LRU cache keyed by (target_language, text).

    Explanation templates are drawn from a small fixed set of rules, so the
    same handful of sentences repeat across every scan in a given language.
    Caching turns the steady state into zero inference calls -- which matters
    much more with a local model than it did with an HTTP one, since every
    miss now costs CPU seconds rather than milliseconds.

    A lock is required because FastAPI runs sync endpoints in a threadpool,
    so concurrent scans really can hit this at once.
    """

    def __init__(self, max_entries: int = 512):
        self._store: "OrderedDict[tuple[str, str], str]" = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def get(self, key: tuple[str, str]) -> Optional[str]:
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def put(self, key: tuple[str, str], value: str) -> None:
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_cache = _TranslationCache()

# --- Provider registry ------------------------------------------------------

_runtime: Optional[IndicTrans2Runtime] = None
_runtime_lock = threading.Lock()


def _build_runtime() -> IndicTrans2Runtime:
    return IndicTrans2Runtime(
        model_id=settings.TRANSLATION_MODEL,
        model_dir=settings.translation_model_path,
        cache_dir=settings.translation_cache_path,
        device=settings.TRANSLATION_DEVICE,
        num_beams=settings.TRANSLATION_NUM_BEAMS,
        max_new_tokens=settings.TRANSLATION_MAX_NEW_TOKENS,
        timeout_seconds=settings.TRANSLATE_TIMEOUT_SECONDS,
        max_concurrency=settings.TRANSLATION_MAX_CONCURRENCY,
        offline=settings.TRANSLATION_OFFLINE,
    )


def get_runtime() -> IndicTrans2Runtime:
    """The process-wide runtime, built on first use.

    Lazily built on purpose: a dev server or a test run that never translates
    never loads a 400 MB model.
    """
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = _build_runtime()
    return _runtime


def _run_indictrans2(texts: List[str], target_language: str) -> List[str]:
    """Translate via the local model. Raises on any real failure."""
    tag = indic_text.tag_for(target_language)
    if tag is None:
        raise ValueError(
            f"No IndicTrans2 tag maps to language {target_language!r}. "
            f"Add it to indic_text.APP_TO_TAG."
        )
    return get_runtime().translate_batch(texts, tag)


def _run_gemini(texts: List[str], target_language: str) -> List[str]:
    """Translate via Gemini API."""
    from google import genai

    if not settings.GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY must be set for Gemini translation.")

    client = genai.Client(api_key=settings.GOOGLE_API_KEY)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_api(prompt_text: str):
        return client.models.generate_content(
            model=getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt_text,
        )

    target_name = _LANGUAGE_NAMES.get(target_language.lower(), target_language)
    results: List[str] = []
    for text in texts:
        prompt = (
            f"Translate the following text to {target_name}. "
            "Return ONLY the translated text, with no explanations, markdown formatting, or original text. "
            f"Text to translate:\n\n{text}"
        )
        response = _call_api(prompt)
        translated = (getattr(response, "text", None) or "").strip()
        results.append(translated if translated else text)

    return results


_PROVIDERS: Dict[str, Callable[[List[str], str], List[str]]] = {
    "indictrans2": _run_indictrans2,
    "gemini": _run_gemini,
}


def _run_provider(texts: List[str], target_language: str) -> List[str]:
    """Dispatch to the configured provider.

    Kept as a module-level function (rather than a class method) because it is
    the single seam the translation tests patch.
    """
    provider = settings.TRANSLATION_PROVIDER
    runner = _PROVIDERS.get(provider)
    if runner is None:
        raise RuntimeError(
            f"Unknown TRANSLATION_PROVIDER {provider!r}. "
            f"Known providers: {', '.join(sorted(_PROVIDERS))}."
        )
    return runner(texts, target_language)


def _passthrough(text: str, warning: Optional[str] = None) -> TranslationResult:
    return TranslationResult(text=text, translated=False, warning=warning)


def translate_many(
    texts: Iterable[str], target_language: str
) -> List[TranslationResult]:
    """Translate several strings, falling back to English on any failure.

    Batch-aware: uncached strings are decoded in a single model call, since an
    explanation plus its recommendations would otherwise be N expensive passes.
    """
    items = list(texts)
    if not items:
        return []

    target = (target_language or SOURCE_LANGUAGE).strip().lower()

    # Nothing to do -- not a failure, so no warning.
    if target == SOURCE_LANGUAGE or not settings.SCAN_TRANSLATION_ENABLED:
        return [_passthrough(text) for text in items]

    # An unsupported language is a caller/config problem, not a provider
    # outage: say so plainly and show English.
    # For indictrans2 we require a FLORES tag; for gemini we allow any language
    # in our LANGUAGE_NAMES map or that has a FLORES tag.
    provider = settings.TRANSLATION_PROVIDER
    is_indic = provider == "indictrans2"
    has_tag = indic_text.tag_for(target) is not None
    has_gemini_name = target in _LANGUAGE_NAMES
    if is_indic and not has_tag:
        logger.warning(
            "Translation requested for unsupported language %r; showing English",
            target,
        )
        warning = (
            f"'{target}' is not a language this deployment translates into. "
            "Showing the original English."
        )
        return [_passthrough(text, warning=warning) for text in items]
    if not is_indic and not (has_tag or has_gemini_name):
        # Still guard against completely unknown codes, but be permissive for gemini
        logger.warning(
            "Translation requested for unsupported language %r; showing English",
            target,
        )
        warning = (
            f"'{target}' is not a language this deployment translates into. "
            "Showing the original English."
        )
        return [_passthrough(text, warning=warning) for text in items]

    results: List[Optional[TranslationResult]] = [None] * len(items)
    pending: List[tuple[int, str]] = []

    for index, text in enumerate(items):
        if not text or not text.strip():
            results[index] = _passthrough(text)
            continue
        cached = _cache.get((target, text))
        if cached is not None:
            results[index] = TranslationResult(text=cached, translated=True)
        else:
            pending.append((index, text))

    if pending:
        try:
            translated_texts = _run_provider(
                [text for _, text in pending], target
            )
        except Exception as exc:  # noqa: BLE001 - never fail the scan
            logger.warning(
                "Translation to %s failed, falling back to English: %s", target, exc
            )
            warning = (
                f"Translation to '{target}' is unavailable right now. "
                "Showing the original English."
            )
            for index, text in pending:
                results[index] = _passthrough(text, warning=warning)
        else:
            if len(translated_texts) != len(pending):
                # Provider contract violation; treat as a failure rather
                # than silently mismatching texts to indices.
                logger.error(
                    "Translate returned %d results for %d inputs",
                    len(translated_texts),
                    len(pending),
                )
                warning = (
                    "Translation returned an unexpected response. "
                    "Showing the original English."
                )
                for index, text in pending:
                    results[index] = _passthrough(text, warning=warning)
            else:
                for (index, source), translated in zip(pending, translated_texts):
                    _cache.put((target, source), translated)
                    results[index] = TranslationResult(
                        text=translated, translated=True
                    )

    return [r if r is not None else _passthrough(items[i]) for i, r in enumerate(results)]


def translate_text(text: str, target_language: str) -> TranslationResult:
    """Translate a single string. See `translate_many`."""
    return translate_many([text], target_language)[0]


def clear_cache() -> None:
    """Exposed for tests."""
    _cache.clear()


def reset_runtime() -> None:
    """Drop the loaded model. Exposed for tests and for a settings reload."""
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            _runtime.shutdown()
        _runtime = None
