from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Street Food Safety AI"
    API_V1_STR: str = "/api/v1"

    # --- Secrets (required, no defaults) ---
    JWT_SECRET_KEY: str
    DATABASE_URL: str

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- Google Cloud (OCR only) ---
    # Vision is the only remaining Google dependency. It authenticates with
    # Application Default Credentials, which the google-cloud library reads
    # from GOOGLE_APPLICATION_CREDENTIALS in the environment; the setting is
    # declared mainly for validation and documentation.
    #
    # Translation no longer uses Google at all -- it runs a local IndicTrans2
    # model -- so nothing here is needed for translation, and the Google
    # Translate API key that used to live here is gone.
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    # Not read by this codebase any more. Kept so existing deployments do not
    # fail validation and because the Cloud project is still meaningful
    # operationally for Vision's billing/enablement.
    GOOGLE_CLOUD_PROJECT: Optional[str] = None

    # Unified Gemini API Key (used for OCR, Translation, and Vision when
    # provider is set to "gemini")
    GOOGLE_API_KEY: Optional[str] = None
    # Gemini model name - use a valid public model. gemini-2.0-flash is the
    # current stable fast model. Override via env if needed.
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # --- OCR ---
    # Swap point for integrations/ocr_client.py. Defaults to "heuristic" friendly
    # offline behavior via google_vision/gemini switch. For tests we default to
    # heuristic-friendly but production can use gemini.
    OCR_PROVIDER: str = "gemini"
    # Labels are photographed, not scanned flat, so we ask Vision for dense
    # document text rather than sparse scene text. See ocr_client for detail.
    OCR_TIMEOUT_SECONDS: float = 30.0

    # --- Scan pipeline ---
    # Where uploaded label images are stored. Relative paths resolve against
    # the backend/ directory.
    SCAN_UPLOAD_DIR: str = "var/uploads/scans"
    SCAN_MAX_UPLOAD_MB: float = 8.0
    # Longest edge, in pixels, that an upload is downscaled to before OCR.
    SCAN_MAX_IMAGE_EDGE: int = 1600

    # Confidence thresholds. See services/products/status_engine.py for how
    # these combine; they are surfaced here so they can be tuned per
    # deployment without touching pipeline logic.
    SCAN_REVIEW_THRESHOLD: float = 0.45
    SCAN_MIN_USABLE_CONFIDENCE: float = 0.25
    SCAN_FUZZY_MATCH_THRESHOLD: int = 88

    # Image quality gate thresholds (services/products/image_quality.py).
    SCAN_MIN_BLUR_VARIANCE: float = 60.0
    SCAN_MIN_BRIGHTNESS: float = 45.0
    SCAN_MAX_BRIGHTNESS: float = 225.0
    SCAN_MAX_GLARE_RATIO: float = 0.12
    SCAN_MIN_IMAGE_EDGE: int = 480

    # --- Translation (local, no Google credentials) ---
    # Kill switch / latency control for the translation step.
    SCAN_TRANSLATION_ENABLED: bool = True
    # Provider swap point for integrations/translate_client.py.
    # Default is indictrans2 (local model) to keep tests offline and deterministic.
    # Set to "gemini" in production via .env for unified Gemini usage.
    TRANSLATION_PROVIDER: str = "indictrans2"

    # Weights. `TRANSLATION_MODEL_DIR` wins when it exists, so a downloaded
    # model runs with no network at all; otherwise `TRANSLATION_MODEL` is
    # treated as a Hub repo id and fetched on first use.
    TRANSLATION_MODEL: str = "ai4bharat/indictrans2-en-indic-dist-200M"
    TRANSLATION_MODEL_DIR: str = "var/models/indictrans2-en-indic-dist-200M"
    TRANSLATION_MODEL_CACHE_DIR: str = "var/models/hf"
    # "auto" uses CUDA when available and CPU otherwise. CPU is fully
    # supported; CUDA is never required.
    TRANSLATION_DEVICE: str = "auto"
    # 5 matches the model card. Greedy (1) is roughly 2x faster with a small
    # quality cost -- see docs/translation.md.
    TRANSLATION_NUM_BEAMS: int = 5
    TRANSLATION_MAX_NEW_TOKENS: int = 256
    # Inferences run on one worker by default, so a burst of scans queues
    # instead of starting several CPU-bound decodes at once.
    TRANSLATION_MAX_CONCURRENCY: int = 1
    # Refuse to touch the network. Set once the model is downloaded.
    TRANSLATION_OFFLINE: bool = False

    # A local model is far slower than an HTTP call: a normal sentence takes
    # ~2s on CPU and a long label ~8s. 15s was tuned for a network round trip
    # and is too tight here.
    TRANSLATE_TIMEOUT_SECONDS: float = 30.0

    # Languages the vendor UI offers. `en` is always the canonical source
    # language and is never sent to the translation API.
    SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "hi", "mr")

    # --- Uploads / static ---
    # Public base URL of the backend, used to build absolute image URLs that
    # the mobile client and reviewer dashboard can load directly.
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

    # Public origin of the *frontend*. This is what a QR code encodes
    # (`{PUBLIC_APP_URL}/stall/{code}`), so it must be the address a consumer
    # can actually reach -- not the API host and not localhost in production.
    PUBLIC_APP_URL: str = "http://localhost:3000"

    # --- Auth Integrations ---
    GOOGLE_CLIENT_ID: Optional[str] = None
    DIGILOCKER_CLIENT_ID: Optional[str] = None
    DIGILOCKER_CLIENT_SECRET: Optional[str] = None

    # --- Computer vision (hygiene) ---
    # Provider swap point for integrations/cv_client.py:
    #   "heuristic" -- deterministic OpenCV signals (default, works offline, used by tests)
    #   "gemini" -- unified Gemini AI for vision
    #   "onnx_yolo" -- YOLO-family inference via onnxruntime
    CV_PROVIDER: str = "heuristic"
    # Path to the exported ONNX model. Relative paths resolve against
    # backend/. The app never downloads this itself -- see
    # scripts/export_yolov8_onnx.py.
    CV_MODEL_PATH: str = "var/models/yolov8n.onnx"
    CV_CONFIDENCE_THRESHOLD: float = 0.35
    CV_NMS_IOU_THRESHOLD: float = 0.45
    CV_INPUT_SIZE: int = 640
    CV_TIMEOUT_SECONDS: float = 20.0

    # Two views whose perceptual hashes are within this Hamming distance are
    # treated as the same photo (64-bit dHash, so 0 = identical).
    CV_DUPLICATE_HAMMING_THRESHOLD: int = 5

    # Heuristic detector thresholds. Exposed so they can be tuned against
    # real stall photos without a code change.
    CV_HEURISTIC_EDGE_DENSITY: float = 0.16
    CV_HEURISTIC_SMALL_BLOB_COUNT: int = 45
    CV_HEURISTIC_DARK_RATIO: float = 0.30
    # Fraction of the frame a bounded, glinting smooth region must cover to
    # read as standing water. Kept low because the bounded-region and
    # specular-glint guards already reject dry surfaces -- this only has to
    # exclude puddles too small to matter.
    CV_HEURISTIC_UNIFORM_REGION_RATIO: float = 0.10

    # --- Hygiene checks ---
    HYGIENE_UPLOAD_DIR: str = "var/uploads/hygiene"
    HYGIENE_MAX_UPLOAD_MB: float = 8.0
    HYGIENE_MAX_IMAGE_EDGE: int = 1600
    # Score weights. Must sum to 1.0; validated at startup by
    # services/hygiene/scoring.py.
    HYGIENE_VISUAL_WEIGHT: float = 0.70
    HYGIENE_CHECKLIST_WEIGHT: float = 0.30

    @property
    def cv_model_path(self) -> Path:
        """Absolute path to the ONNX model, resolved against backend/."""
        p = Path(self.CV_MODEL_PATH)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        return p

    @property
    def hygiene_upload_path(self) -> Path:
        """Absolute path to the hygiene upload directory."""
        p = Path(self.HYGIENE_UPLOAD_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        return p

    @property
    def scan_upload_path(self) -> Path:
        """Absolute path to the scan upload directory, resolved against backend/."""
        p = Path(self.SCAN_UPLOAD_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        return p

    @property
    def translation_model_path(self) -> Path:
        """Absolute path to the local model directory, resolved against backend/."""
        p = Path(self.TRANSLATION_MODEL_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        return p

    @property
    def translation_cache_path(self) -> Path:
        """Absolute path to the Hugging Face download cache."""
        p = Path(self.TRANSLATION_MODEL_CACHE_DIR)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        return p

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )


settings = Settings()
