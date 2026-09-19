"""OCR integration: label image in, text out.

WHY GOOGLE CLOUD VISION
-----------------------
PaddleOCR would be the natural first choice for Indian packaging labels --
it is strong on Devanagari and runs locally. It is not usable here: its
inference engine `paddlepaddle` publishes **no wheel for cp314**, so it
cannot be installed on this project's Python 3.14 venv at all.

The remaining candidates were Tesseract and EasyOCR:
  * Tesseract needs an unmanaged system binary plus `hin`/`mar` traineddata
    that pip cannot install, and its Devanagari accuracy on photographed
    (not scanned) labels is the weakest of the three.
  * EasyOCR works but pulls ~2.5 GB of torch and adds multi-second CPU
    inference per label on top of an already synchronous request.

Cloud Vision needs no system dependency, has the strongest Devanagari text
detection, and reuses the same service-account credentials the translation
step already requires -- so it adds no new operational surface.

The tradeoff is real and worth stating: OCR now requires network access and
a billing-enabled project. `settings.OCR_PROVIDER` exists as the swap point;
a local provider would be a sibling implementation of `run_ocr`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class OcrError(RuntimeError):
    """OCR could not be completed.

    Carries a `user_message` safe to show a vendor, and `retryable` so the
    caller can distinguish "try again in a moment" (quota, network) from
    "this will never work" (permission denied, API not enabled).
    """

    def __init__(self, message: str, user_message: str, retryable: bool = False):
        super().__init__(message)
        self.user_message = user_message
        self.retryable = retryable


@dataclass
class OcrResult:
    text: str
    confidence: Optional[float]
    """Mean per-word confidence in [0, 1], or None when the provider did not
    report any. See `_extract_confidence` -- None is a real possibility with
    Cloud Vision and the caller must handle it rather than assume 0.0."""

    word_count: int = 0
    engine: str = "google_vision"
    # Characters the provider was unsure about, for debugging bad scans.
    low_confidence_words: List[str] = field(default_factory=list)


def _extract_confidence(response) -> tuple[Optional[float], int, List[str]]:
    """Pull per-word confidences out of a Vision annotation.

    IMPORTANT: Cloud Vision's `document_text_detection` frequently does not
    populate `word.confidence` -- the field comes back as 0.0 for every word.
    Returning 0.0 in that case would be actively harmful: it would look like
    "the OCR was terrible" when in fact the provider simply declined to
    report a number, and it would drive every scan to "Needs review".

    So: treat an all-zero/unset distribution as "not reported" and return
    None. The scan pipeline then falls back to an image-quality-derived
    estimate (see services/products/status_engine.py::resolve_ocr_confidence).
    """
    try:
        annotation = response.full_text_annotation
    except AttributeError:
        return None, 0, []

    confidences: List[float] = []
    low_confidence_words: List[str] = []
    word_count = 0

    for page in getattr(annotation, "pages", []) or []:
        for block in getattr(page, "blocks", []) or []:
            for paragraph in getattr(block, "paragraphs", []) or []:
                for word in getattr(paragraph, "words", []) or []:
                    word_count += 1
                    confidence = getattr(word, "confidence", 0.0) or 0.0
                    if confidence > 0.0:
                        confidences.append(confidence)
                        if confidence < 0.6:
                            text = "".join(
                                symbol.text
                                for symbol in getattr(word, "symbols", []) or []
                            )
                            if text:
                                low_confidence_words.append(text)

    if not confidences:
        # Provider reported nothing usable. Not the same as low confidence.
        return None, word_count, []

    mean = sum(confidences) / len(confidences)
    # Low-confidence word list is only useful in moderation; a bad photo can
    # produce hundreds and it is stored on the product row.
    return mean, word_count, low_confidence_words[:25]


def _run_google_vision(image_bytes: bytes) -> OcrResult:
    # Imported lazily so the module can be imported (and the pipeline unit
    # tested) without the google-cloud-vision package or credentials present.
    try:
        from google.api_core import exceptions as google_exceptions
        from google.cloud import vision
    except ImportError as exc:
        logger.error("Google Cloud Vision not installed: %s", exc)
        raise OcrError(
            "google-cloud-vision is not installed",
            "Label reading is not configured correctly. Please contact support.",
            retryable=False,
        ) from exc

    try:
        client = vision.ImageAnnotatorClient()
    except Exception as exc:  # noqa: BLE001 - credential/config failure
        logger.error("Could not initialise Vision client: %s", exc)
        raise OcrError(
            f"Vision client init failed: {exc}",
            "Label reading is not configured correctly. Please contact support.",
            retryable=False,
        ) from exc

    image = vision.Image(content=image_bytes)

    try:
        # DOCUMENT_TEXT_DETECTION rather than TEXT_DETECTION: labels are
        # dense, small-print paragraphs, which is the document case, not the
        # sparse scene-text case.
        response = client.document_text_detection(
            image=image, timeout=settings.OCR_TIMEOUT_SECONDS
        )
    except google_exceptions.PermissionDenied as exc:
        logger.error("Vision permission denied: %s", exc)
        raise OcrError(
            f"Vision PermissionDenied: {exc}",
            "Label reading is not enabled for this account.",
            retryable=False,
        ) from exc
    except google_exceptions.Unauthenticated as exc:
        logger.error("Vision unauthenticated: %s", exc)
        raise OcrError(
            f"Vision Unauthenticated: {exc}",
            "Label reading credentials are invalid.",
            retryable=False,
        ) from exc
    except (
        google_exceptions.ServiceUnavailable,
        google_exceptions.DeadlineExceeded,
        google_exceptions.ResourceExhausted,
        google_exceptions.TooManyRequests,
    ) as exc:
        logger.warning("Vision temporarily unavailable: %s", exc)
        raise OcrError(
            f"Vision unavailable: {exc}",
            "Label reading is busy right now. Please try again.",
            retryable=True,
        ) from exc
    except google_exceptions.GoogleAPIError as exc:
        logger.error("Vision API error: %s", exc)
        raise OcrError(
            f"Vision GoogleAPIError: {exc}",
            "Could not read the label. Please try again.",
            retryable=True,
        ) from exc

    if response.error and response.error.message:
        logger.error("Vision returned error: %s", response.error.message)
        raise OcrError(
            f"Vision error: {response.error.message}",
            "Could not read the label. Please try again.",
            retryable=True,
        )

    text = (response.full_text_annotation.text or "").strip()
    confidence, word_count, low_conf = _extract_confidence(response)

    return OcrResult(
        text=text,
        confidence=confidence,
        word_count=word_count,
        engine="google_vision",
        low_confidence_words=low_conf,
    )


def _run_gemini(image_bytes: bytes) -> OcrResult:
    from google import genai
    from google.genai import types
    from tenacity import retry, stop_after_attempt, wait_exponential

    if not settings.GOOGLE_API_KEY:
        raise OcrError(
            "Gemini API key missing",
            "Label reading is not configured correctly. Please contact support.",
            retryable=False,
        )

    try:
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)

        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
        )
        def _call_api():
            return client.models.generate_content(
                model=getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash"),
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    "Extract all visible text from this product label verbatim. Return ONLY the extracted text with no other explanations, markdown formatting, or tags.",
                ],
            )

        response = _call_api()
        raw_text = getattr(response, "text", None) or ""
        text = raw_text.strip()
        word_count = len(text.split()) if text else 0

        # Gemini does not provide per-word confidence. We pass None so the downstream
        # pipeline uses its heuristic image-quality-based fallback.
        return OcrResult(
            text=text,
            confidence=None,
            word_count=word_count,
            engine="gemini",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini OCR failed: %s", exc)
        raise OcrError(
            f"Gemini API Error: {exc}",
            "Could not read the label right now. Please try again.",
            retryable=True,
        ) from exc


_PROVIDERS = {
    "google_vision": _run_google_vision,
    "gemini": _run_gemini,
}


def run_ocr(image_bytes: bytes) -> OcrResult:
    """Extract text from a label image.

    Raises OcrError on any provider failure; callers translate that into a
    user-facing message rather than a 500.
    """
    if not image_bytes:
        raise OcrError("Empty image", "No image was received. Please retake.")

    provider = settings.OCR_PROVIDER
    runner = _PROVIDERS.get(provider)
    if runner is None:
        raise OcrError(
            f"Unknown OCR_PROVIDER {provider!r}",
            "Label reading is misconfigured.",
            retryable=False,
        )

    return runner(image_bytes)
