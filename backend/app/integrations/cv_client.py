"""Computer-vision integration: stall photos in, hygiene-indicator
detections out.

THE SWAP BOUNDARY
-----------------
Everything model-specific lives in this file. Replacing today's placeholder
detectors with a purpose-trained hygiene model means editing this module and
re-seeding `hygiene_indicators.cv_labels` -- nothing in services/hygiene/,
the API layer, or the UI changes. That is the contract tests pin.

TWO PROVIDERS
-------------
`heuristic` (default) -- deterministic OpenCV signals. No model file, no
network, no download. It runs on a fresh clone, is fully reproducible, and
is therefore the only provider the test suite asserts behaviour against.

`onnx_yolo` -- YOLO-family inference through onnxruntime. Deliberately NOT
torch: `pip install ultralytics` resolves to ~2.5 GB and pulls
`opencv-python`, the non-headless build, which would sit alongside the
`opencv-python-headless` already installed and fight over the `cv2`
package. ONNX Runtime needs ~50 MB and no torch at all, and for fixed-graph
CPU inference it is typically faster.

WHAT THE PLACEHOLDER MODELS ACTUALLY ARE
----------------------------------------
The ONNX path uses YOLOv8n pretrained on COCO. COCO's 80 classes contain
**no hygiene indicators**. Mapping "cup" to visible waste gives the pipeline
real detections with real confidences so scoring, coverage, persistence, and
UI can be built and tested now -- it is not a hygiene model, and its
precision on a real stall is unknown and probably poor. The mapping lives in
the seeded `cv_labels`, so it is visible and editable rather than buried.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

import cv2
import numpy as np

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.models.enums import DetectionSource, ViewCategory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CvError(RuntimeError):
    """Base for CV failures. Carries a vendor-safe message."""

    def __init__(self, message: str, user_message: str, retryable: bool = False):
        super().__init__(message)
        self.user_message = user_message
        self.retryable = retryable


class CvModelUnavailable(CvError):
    """The configured ONNX model file is missing or unreadable.

    Raised eagerly at session creation with instructions, rather than
    surfacing as an opaque inference error on the first photo a vendor
    submits.
    """


class CvInferenceError(CvError):
    """The model ran but failed."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Detection:
    """One thing a provider says it saw."""

    label: str
    """The indicator code this maps to (e.g. "visible_waste")."""

    raw_label: str
    """What the provider actually produced, before mapping (e.g. "cup",
    "heuristic:edge_density"). Stored so a disputed finding can be traced
    back to the evidence."""

    confidence: float
    bbox: Optional[Tuple[int, int, int, int]] = None  # x1, y1, x2, y2
    source: str = DetectionSource.HEURISTIC.value

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "raw_label": self.raw_label,
            "confidence": round(self.confidence, 4),
            "bbox": list(self.bbox) if self.bbox else None,
            "source": self.source,
        }


@dataclass
class CvResult:
    detections: List[Detection] = field(default_factory=list)
    provider: str = DetectionSource.HEURISTIC.value
    metrics: Dict[str, float] = field(default_factory=dict)
    """Raw signals behind the detections. Always populated, including when
    nothing was detected -- without it, "found nothing" and "did not run"
    look identical in the data."""

    def by_label(self) -> Dict[str, List[Detection]]:
        grouped: Dict[str, List[Detection]] = {}
        for detection in self.detections:
            grouped.setdefault(detection.label, []).append(detection)
        return grouped

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "detections": [d.to_dict() for d in self.detections],
        }


class CvProvider(Protocol):
    """A detector. Implementations must be deterministic given the same
    bytes -- the API re-runs detection on retakes and a provider that
    flickered would make the score look unstable."""

    name: str

    def detect(self, image_bgr: np.ndarray, view: ViewCategory) -> CvResult: ...


def _coordinate_space_metrics(image: np.ndarray) -> Dict[str, float]:
    """Dimensions of the image the detector actually ran on.

    Both providers downscale before detecting, so every bounding box they
    emit is in *downscaled* coordinates, not the original photo's. Without
    these two numbers recorded, a consumer cannot place a box on the
    original image -- which is exactly what the reviewer dashboard's overlay
    needs to do.

    Recording it here rather than recomputing it downstream matters: the
    downscale rule lives in `downscale()` above, and a client that
    reimplemented it would break silently the day that rule changed.
    """
    height, width = image.shape[:2]
    return {"image_width": float(width), "image_height": float(height)}


# ---------------------------------------------------------------------------
# Shared image helpers
# ---------------------------------------------------------------------------


def decode_image(image_bytes: bytes) -> np.ndarray:
    """Decode upload bytes to a BGR array, or raise CvError."""
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    if buffer.size == 0:
        raise CvError("Empty image", "No image was received. Please retake.")
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise CvError(
            "Could not decode image",
            "That file could not be read as an image. Please retake the photo.",
        )
    return image


def downscale(image: np.ndarray, max_edge: int) -> np.ndarray:
    """Cap the long edge. Detection accuracy plateaus quickly on stall
    photos while cost scales with pixels."""
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_edge:
        return image
    scale = max_edge / longest
    return cv2.resize(
        image,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


# ---------------------------------------------------------------------------
# Heuristic provider
# ---------------------------------------------------------------------------

#: Indicator labels emitted by the heuristic path. They are namespaced with
#: "heuristic:" so they can never be confused with a model's class names in
#: a stored detection.
H_WASTE = "heuristic:waste_density"
H_EDGE = "heuristic:edge_density"
H_WATER = "heuristic:standing_water"
H_OPEN = "heuristic:open_surface"
H_UTENSILS = "heuristic:utensil_cluster"
H_PEST = "heuristic:pest_blob"
H_LINEAR = "heuristic:linear_dark_region"


class HeuristicProvider:
    """Deterministic OpenCV signals.

    Honest scope note: these are crude proxies. They measure *image
    statistics* that correlate with the thing named -- edge density really
    does rise with clutter -- but none of them understands what it is
    looking at. A tidy stall photographed on a patterned surface can read as
    cluttered. This provider exists so the pipeline is testable and so the
    product works before a dataset exists; it is not a substitute for a
    trained model.
    """

    name = DetectionSource.HEURISTIC.value

    #: Confidence assigned to heuristic detections. Capped well below 1.0
    #: because a rule firing is not the same as an object being recognised.
    BASE_CONFIDENCE = 0.45

    def detect(self, image_bgr: np.ndarray, view: ViewCategory) -> CvResult:
        image = downscale(image_bgr, settings.HYGIENE_MAX_IMAGE_EDGE)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        height, width = gray.shape[:2]
        total_pixels = float(height * width)

        metrics: Dict[str, float] = dict(_coordinate_space_metrics(image))
        detections: List[Detection] = []

        # --- Clutter: edge density -------------------------------------
        edges = cv2.Canny(gray, 80, 180)
        edge_ratio = float(np.count_nonzero(edges)) / total_pixels
        metrics["edge_density"] = edge_ratio

        # --- Clutter / waste: many small high-contrast blobs -----------
        # A work surface with a few objects produces a handful of large
        # contours; scattered litter produces many small ones. The band is
        # what distinguishes them.
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        small_blobs = [
            c
            for c in contours
            if 20.0 < cv2.contourArea(c) < total_pixels * 0.005
        ]
        metrics["small_blob_count"] = float(len(small_blobs))
        metrics["contour_count"] = float(len(contours))

        # --- Standing water: a BOUNDED smooth region with glints --------
        #
        # Smoothness alone is not water. A clean steel or tiled surface is
        # equally smooth, low-saturation, and mid-bright -- an earlier
        # version of this signal fired on *every* tidy stall photo, which is
        # the single worst way a hygiene score can fail. Two extra
        # conditions do the real work:
        #   1. A puddle is bounded. A region covering most of the frame is a
        #      flat surface or a wall, not standing water.
        #   2. Water reflects. A real puddle carries specular glints.
        local_mean = cv2.blur(gray.astype(np.float32), (15, 15))
        local_var = cv2.blur((gray.astype(np.float32) - local_mean) ** 2, (15, 15))
        smooth = local_var < 8.0
        low_sat = hsv[:, :, 1] < 40
        mid_bright = (gray > 60) & (gray < 220)
        candidate = (smooth & low_sat & mid_bright).astype(np.uint8)

        water_ratio = 0.0
        water_bbox: Optional[Tuple[int, int, int, int]] = None
        if candidate.any():
            num_components, comp_labels, stats, _ = cv2.connectedComponentsWithStats(
                candidate, connectivity=8
            )
            for index in range(1, num_components):
                area = float(stats[index, cv2.CC_STAT_AREA])
                fraction = area / total_pixels
                if not (0.02 <= fraction <= 0.45):
                    continue  # too small to matter, or too big to be a puddle
                component = (comp_labels == index).astype(np.uint8)
                # Sample glints from a DILATED component, for two reasons:
                #
                # 1. Specular highlights are bright, so the mid-brightness
                #    condition already excludes them from the mask. Looking
                #    for them strictly inside the mask would be circular and
                #    standing water could never be detected at all.
                # 2. The smoothness blur above also punches a hole around
                #    each glint, roughly (blur radius + glint radius) wide.
                #    The dilation kernel MUST be wider than that hole or the
                #    glints stay outside the sampled region -- which is
                #    exactly the bug that made this signal never fire. The
                #    blur is 15px, so the kernel is 31px.
                dilated = cv2.dilate(component, np.ones((31, 31), np.uint8))
                glint_ratio = float((gray[dilated > 0] >= 225).mean())
                if glint_ratio < 0.003:
                    continue  # smooth but non-reflective: a dry surface
                if fraction > water_ratio:
                    water_ratio = fraction
                    x, y, w, h = (
                        int(stats[index, cv2.CC_STAT_LEFT]),
                        int(stats[index, cv2.CC_STAT_TOP]),
                        int(stats[index, cv2.CC_STAT_WIDTH]),
                        int(stats[index, cv2.CC_STAT_HEIGHT]),
                    )
                    water_bbox = (x, y, x + w, y + h)
        metrics["uniform_region_ratio"] = water_ratio

        # --- Dark regions: shadowed leaks ------------------------------
        dark_ratio = float(np.count_nonzero(gray < 55)) / total_pixels
        metrics["dark_ratio"] = dark_ratio

        # --- Utensil cluster: many thin elongated contours -------------
        elongated = 0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 30 or area > total_pixels * 0.02:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if min(w, h) == 0:
                continue
            aspect = max(w, h) / float(min(w, h))
            if aspect >= 3.0:
                elongated += 1
        metrics["elongated_contour_count"] = float(elongated)

        # --- Pest evidence: small very dark blobs on lighter ground ----
        dark_mask = (gray < 45).astype(np.uint8)
        pest_contours, _ = cv2.findContours(
            dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        pest_blobs = [
            c for c in pest_contours if 8.0 < cv2.contourArea(c) < total_pixels * 0.002
        ]
        metrics["pest_blob_count"] = float(len(pest_blobs))

        # --- Straight dark edges: open drains, pipes -------------------
        #
        # Detected on the edges of the ORIGINAL image, then filtered by
        # sampling brightness along each line. Running Hough on a dark mask
        # instead would be blind here: a dark drain on a dark floor produces
        # a mask with no internal edges at all.
        lines = cv2.HoughLinesP(
            edges, 1, math.pi / 180, threshold=80,
            minLineLength=max(60, int(min(height, width) * 0.25)),
            maxLineGap=12,
        )
        dark_lines = 0
        if lines is not None:
            # HoughLinesP returns (N, 1, 4), but reshapes vary by OpenCV
            # version and by how many lines were found. Normalising here
            # avoids a version-dependent crash on a rarely-hit branch.
            for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                samples = 20
                xs = np.linspace(x1, x2, samples).astype(int).clip(0, width - 1)
                ys = np.linspace(y1, y2, samples).astype(int).clip(0, height - 1)
                values = gray[ys, xs]
                # Both dark and uniform along their length -- a pipe edge or
                # a drain channel, not a shadow boundary between two objects.
                if values.mean() < 75 and values.std() < 40:
                    dark_lines += 1
        metrics["long_line_count"] = float(dark_lines)

        # --- Threshold into detections ---------------------------------
        if edge_ratio >= settings.CV_HEURISTIC_EDGE_DENSITY:
            detections.append(
                self._make(
                    H_EDGE, "cluttered_surface", metrics["edge_density"],
                    (0, 0, width, height),
                )
            )

        if len(small_blobs) >= settings.CV_HEURISTIC_SMALL_BLOB_COUNT:
            detections.append(
                self._make(
                    H_WASTE, "visible_waste",
                    min(1.0, len(small_blobs) / (settings.CV_HEURISTIC_SMALL_BLOB_COUNT * 2)),
                    self._union_bbox(small_blobs),
                )
            )

        if water_ratio >= settings.CV_HEURISTIC_UNIFORM_REGION_RATIO:
            detections.append(
                self._make(
                    H_WATER, "stagnant_water", min(1.0, water_ratio * 3.0), water_bbox
                )
            )

        if elongated >= 6:
            detections.append(
                self._make(
                    H_UTENSILS, "dirty_utensils", min(1.0, elongated / 12.0), None
                )
            )

        if len(pest_blobs) >= 12:
            detections.append(
                self._make(
                    H_PEST, "pest_evidence", min(1.0, len(pest_blobs) / 24.0),
                    self._union_bbox(pest_blobs),
                )
            )

        if metrics["long_line_count"] >= 2:
            # Deliberately NOT gated on dark_ratio. An open drain is a
            # *localised* dark linear feature; requiring a large fraction of
            # the frame to be dark would mean this only ever fired on a
            # near-black photo. Two long, dark, uniform lines is the signal.
            detections.append(self._make(H_LINEAR, "open_drain", 0.4, None))

        # Uncovered food has no honest heuristic signature on a still image
        # -- a covered container and an open one are near-identical from
        # above. Deliberately not emitted rather than faked; the seed keeps
        # the indicator with COCO labels only.

        return CvResult(
            detections=detections,
            provider=self.name,
            metrics=metrics,
        )

    def _make(
        self,
        raw_label: str,
        indicator_code: str,
        confidence: float,
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> Detection:
        return Detection(
            label=indicator_code,
            raw_label=raw_label,
            confidence=round(self.BASE_CONFIDENCE + 0.4 * min(1.0, max(0.0, confidence)), 4),
            bbox=bbox,
            source=self.name,
        )

    @staticmethod
    def _union_bbox(
        contours: Sequence[np.ndarray],
    ) -> Optional[Tuple[int, int, int, int]]:
        """Bounding box covering every contour, or None if there are none."""
        if not contours:
            return None
        xs, ys, x2s, y2s = [], [], [], []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            xs.append(x); ys.append(y); x2s.append(x + w); y2s.append(y + h)
        return (min(xs), min(ys), max(x2s), max(ys))

    @staticmethod
    def _mask_bbox(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return None
        return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


# ---------------------------------------------------------------------------
# ONNX / YOLO provider
# ---------------------------------------------------------------------------

#: COCO class names in YOLOv8 index order. Duplicated here rather than
#: imported from ultralytics (which we deliberately do not depend on).
COCO_CLASSES: Tuple[str, ...] = (
    "person","bicycle","car","motorcycle","airplane","bus","train","truck","boat",
    "traffic light","fire hydrant","stop sign","parking meter","bench","bird","cat",
    "dog","horse","sheep","cow","elephant","bear","zebra","giraffe","backpack",
    "umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball",
    "kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket",
    "bottle","wine glass","cup","fork","knife","spoon","bowl","banana","apple",
    "sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair",
    "couch","potted plant","bed","dining table","toilet","tv","laptop","mouse",
    "remote","keyboard","cell phone","microwave","oven","toaster","sink",
    "refrigerator","book","clock","vase","scissors","teddy bear","hair drier",
    "toothbrush",
)

#: Padding colour used by YOLO's letterbox preprocessing.
_LETTERBOX_VALUE = 114


@dataclass
class _LetterboxTransform:
    scale: float
    pad_x: int
    pad_y: int
    original_width: int
    original_height: int


_session_lock = threading.Lock()
_cached_session = None
_cached_session_path: Optional[str] = None


def _load_onnx_session(model_path: str):
    """Load (and cache) the ONNX session.

    Cached because session creation costs ~100-300 ms and the provider may
    be invoked four times per hygiene check.
    """
    global _cached_session, _cached_session_path

    with _session_lock:
        if _cached_session is not None and _cached_session_path == model_path:
            return _cached_session

        try:
            import onnxruntime  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise CvModelUnavailable(
                "onnxruntime is not installed",
                "Hygiene photo checks are not available right now.",
                retryable=False,
            ) from exc

        _cached_session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        _cached_session_path = model_path
        return _cached_session


def reset_model_cache() -> None:
    """Drop the cached session. Exposed for tests and for model swaps."""
    global _cached_session, _cached_session_path
    with _session_lock:
        _cached_session = None
        _cached_session_path = None


class OnnxYoloProvider:
    """YOLO-family detection via ONNX Runtime.

    The model file is supplied by the operator (see
    scripts/export_yolov8_onnx.py). This provider never downloads weights:
    silently fetching an unverified binary into a service that reports on
    people's livelihoods is not a trade worth making for convenience.
    """

    name = DetectionSource.ONNX_YOLO.value

    #: Below this many pixels of image area we refuse to run -- a tiny image
    #: letterboxed to 640 is almost entirely interpolation.
    MIN_SOURCE_EDGE = 200

    def __init__(
        self,
        model_path: Optional[str] = None,
        indicator_labels: Optional[Dict[str, str]] = None,
    ):
        self.model_path = model_path or str(settings.cv_model_path)
        # raw provider label -> indicator code. Sourced from the seeded
        # hygiene_indicators.cv_labels, so a new model's class names are a
        # data change.
        self.indicator_labels = indicator_labels or {}

    def _ensure_ready(self) -> None:
        from pathlib import Path

        path = Path(self.model_path)
        if not path.exists():
            raise CvModelUnavailable(
                f"ONNX model not found at {path}",
                "Hygiene photo checks are not configured. Please contact support.",
                retryable=False,
            )
        if not path.is_file():
            raise CvModelUnavailable(
                f"ONNX model path is not a file: {path}",
                "Hygiene photo checks are not configured. Please contact support.",
                retryable=False,
            )

    def detect(self, image_bgr: np.ndarray, view: ViewCategory) -> CvResult:
        self._ensure_ready()

        image = downscale(image_bgr, settings.HYGIENE_MAX_IMAGE_EDGE)
        height, width = image.shape[:2]
        if min(height, width) < self.MIN_SOURCE_EDGE:
            raise CvInferenceError(
                f"Image too small: {width}x{height}",
                "That photo is too small to check. Please retake it.",
            )

        session = _load_onnx_session(self.model_path)
        blob, transform = self._preprocess(image)

        input_name = session.get_inputs()[0].name
        try:
            outputs = session.run(None, {input_name: blob})
        except Exception as exc:  # noqa: BLE001 - provider failure
            logger.error("ONNX inference failed: %s", exc)
            raise CvInferenceError(
                f"ONNX inference failed: {exc}",
                "The stall photo could not be checked. Please try again.",
                retryable=True,
            ) from exc

        boxes, scores, class_ids = self._postprocess(outputs, transform)

        detections = [
            Detection(
                label=self.indicator_labels.get(COCO_CLASSES[class_id], "unmapped"),
                raw_label=COCO_CLASSES[class_id],
                confidence=float(score),
                bbox=box,
                source=self.name,
            )
            for box, score, class_id in zip(boxes, scores, class_ids)
        ]
        # Anything with no indicator mapping is dropped rather than stored:
        # it would be noise in the findings and cannot affect the score.
        detections = [d for d in detections if d.label != "unmapped"]

        return CvResult(
            detections=detections,
            provider=self.name,
            metrics={
                **_coordinate_space_metrics(image),
                "detection_count": float(len(detections)),
                "letterbox_scale": transform.scale,
            },
        )

    # -- preprocessing -----------------------------------------------------

    def _letterbox(self, image: np.ndarray) -> Tuple[np.ndarray, _LetterboxTransform]:
        """Resize preserving aspect ratio and pad to a square.

        YOLO is trained on letterboxed input; stretching instead of padding
        distorts boxes and measurably degrades accuracy.
        """
        size = settings.CV_INPUT_SIZE
        height, width = image.shape[:2]

        scale = min(size / width, size / height)
        new_width, new_height = int(round(width * scale)), int(round(height * scale))

        resized = cv2.resize(
            image, (new_width, new_height), interpolation=cv2.INTER_LINEAR
        )

        canvas = np.full((size, size, 3), _LETTERBOX_VALUE, dtype=np.uint8)
        pad_x = (size - new_width) // 2
        pad_y = (size - new_height) // 2
        canvas[pad_y : pad_y + new_height, pad_x : pad_x + new_width] = resized

        return canvas, _LetterboxTransform(
            scale=scale,
            pad_x=pad_x,
            pad_y=pad_y,
            original_width=width,
            original_height=height,
        )

    def _preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, _LetterboxTransform]:
        canvas, transform = self._letterbox(image)
        # BGR -> RGB, HWC -> CHW, 0-255 -> 0-1, add batch dim.
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        blob = rgb.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
        return np.ascontiguousarray(blob), transform

    # -- postprocessing ----------------------------------------------------

    @staticmethod
    def _map_box_to_source(
        box: Tuple[float, float, float, float], transform: _LetterboxTransform
    ) -> Tuple[int, int, int, int]:
        """Undo letterbox padding and scaling, then clamp to the image."""
        x1, y1, x2, y2 = box
        x1 = (x1 - transform.pad_x) / transform.scale
        y1 = (y1 - transform.pad_y) / transform.scale
        x2 = (x2 - transform.pad_x) / transform.scale
        y2 = (y2 - transform.pad_y) / transform.scale
        return (
            int(max(0, min(x1, transform.original_width))),
            int(max(0, min(y1, transform.original_height))),
            int(max(0, min(x2, transform.original_width))),
            int(max(0, min(y2, transform.original_height))),
        )

    def _postprocess(
        self, outputs: Sequence[np.ndarray], transform: _LetterboxTransform
    ) -> Tuple[List[Tuple[int, int, int, int]], List[float], List[int]]:
        """Decode the YOLOv8 head, then apply NMS.

        YOLOv8 emits (1, 4 + num_classes, num_anchors) -- predictions are
        transposed relative to YOLOv5, which is a common source of silently
        wrong boxes.
        """
        raw = np.squeeze(outputs[0])
        if raw.ndim != 2:
            raise CvInferenceError(
                f"Unexpected model output shape: {raw.shape}",
                "The stall photo could not be checked. Please try again.",
            )

        # Orient to (num_anchors, 4 + num_classes).
        if raw.shape[0] < raw.shape[1]:
            raw = raw.T

        if raw.shape[1] < 5:
            raise CvInferenceError(
                f"Model output has too few channels: {raw.shape[1]}",
                "The stall photo could not be checked. Please try again.",
            )

        boxes_xywh = raw[:, :4]
        class_scores = raw[:, 4:]
        class_ids = np.argmax(class_scores, axis=1)
        scores = class_scores[np.arange(class_scores.shape[0]), class_ids]

        keep = scores >= settings.CV_CONFIDENCE_THRESHOLD
        boxes_xywh, scores, class_ids = boxes_xywh[keep], scores[keep], class_ids[keep]
        if len(scores) == 0:
            return [], [], []

        # cx, cy, w, h -> x1, y1, x2, y2 in letterboxed coordinates.
        cx, cy, w, h = (
            boxes_xywh[:, 0], boxes_xywh[:, 1], boxes_xywh[:, 2], boxes_xywh[:, 3]
        )
        xyxy = np.stack(
            [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1
        ).tolist()

        # NMS is per class: suppressing a "cup" because a "bowl" overlaps it
        # would erase a genuinely different finding.
        kept_indices: List[int] = []
        for class_id in np.unique(class_ids):
            class_mask = np.where(class_ids == class_id)[0]
            class_boxes = [xyxy[i] for i in class_mask]
            class_scores = [float(scores[i]) for i in class_mask]
            selected = cv2.dnn.NMSBoxes(
                class_boxes,
                class_scores,
                settings.CV_CONFIDENCE_THRESHOLD,
                settings.CV_NMS_IOU_THRESHOLD,
            )
            if selected is None or len(selected) == 0:
                continue
            kept_indices.extend(int(class_mask[i]) for i in np.array(selected).flatten())

        if not kept_indices:
            return [], [], []

        final_boxes = [
            self._map_box_to_source(tuple(xyxy[i]), transform) for i in kept_indices
        ]
        final_scores = [float(scores[i]) for i in kept_indices]
        final_classes = [int(class_ids[i]) for i in kept_indices]
        return final_boxes, final_scores, final_classes


# ---------------------------------------------------------------------------
# Gemini Provider
# ---------------------------------------------------------------------------


class GeminiProvider:
    """Uses Google Gemini 1.5 Pro to analyze the image and return structured JSON."""
    name = DetectionSource.GEMINI.value

    def __init__(self, indicator_labels: Dict[str, str]):
        self.indicator_labels = indicator_labels

    def detect(self, image_bgr: np.ndarray, view: ViewCategory) -> CvResult:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise CvError(
                "google-genai not installed",
                "Hygiene photo checks are misconfigured.",
                retryable=False,
            ) from exc
        import json

        if not settings.GOOGLE_API_KEY:
            raise CvError(
                "Gemini API key missing",
                "Hygiene photo checks are misconfigured.",
                retryable=False,
            )

        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        
        success, encoded_image = cv2.imencode(".jpg", image_bgr)
        if not success:
            raise CvInferenceError("Failed to encode image", "Could not process the photo.")
            
        image_bytes = encoded_image.tobytes()
        metrics = _coordinate_space_metrics(image_bgr)
        width, height = metrics["image_width"], metrics["image_height"]
        
        prompt = (
            f"Act as a food safety hygiene inspector. Look at this {view.value} view of a street food stall.\n"
            "Analyze the image for hygiene indicators like visible waste, uncovered food, cluttered surfaces, dirty utensils, etc.\n"
            "Return a JSON array of detections. For each detection, include:\n"
            ' - "label": a short descriptive string (e.g., "visible_waste", "uncovered_food")\n'
            ' - "confidence": a float between 0.0 and 1.0\n'
            ' - "box_2d": [ymin, xmin, ymax, xmax] coordinates normalized between 0 and 1000. If no bounding box can be determined, omit this field.\n'
            "Return ONLY the JSON array."
        )

        try:

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
                        prompt,
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )

            response = _call_api()

            raw_text = getattr(response, "text", None) or "[]"
            detections_data = json.loads(raw_text)
            
            detections = []
            for d in detections_data:
                raw_label = str(d.get("label", "")).lower()
                mapped_label = self.indicator_labels.get(raw_label, raw_label)
                    
                box_2d = d.get("box_2d")
                bbox = None
                if isinstance(box_2d, list) and len(box_2d) == 4:
                    ymin, xmin, ymax, xmax = box_2d
                    x1 = int((xmin / 1000.0) * width)
                    y1 = int((ymin / 1000.0) * height)
                    x2 = int((xmax / 1000.0) * width)
                    y2 = int((ymax / 1000.0) * height)
                    bbox = (x1, y1, x2, y2)
                    
                detections.append(Detection(
                    label=mapped_label,
                    raw_label=f"gemini:{raw_label}",
                    confidence=float(d.get("confidence", 0.9)),
                    bbox=bbox,
                    source=self.name
                ))
                
            return CvResult(
                detections=detections,
                provider=self.name,
                metrics=metrics
            )
        except Exception as exc:
            logger.error("Gemini CV failed: %s", exc)
            raise CvInferenceError(
                f"Gemini CV failed: {exc}", 
                "Could not analyze the photo right now. Please try again.",
                retryable=True
            ) from exc


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def build_indicator_label_map(indicator_rows) -> Dict[str, str]:
    """raw provider label -> indicator code, from the seeded catalog.

    Built from `hygiene_indicators.cv_labels` so that swapping in a trained
    model is a seed update rather than an edit to this file.
    """
    mapping: Dict[str, str] = {}
    for row in indicator_rows:
        for label in row.cv_labels or []:
            mapping.setdefault(str(label).lower(), row.code)
    return mapping


def get_provider(indicator_rows=None) -> CvProvider:
    """Resolve the configured provider."""
    name = (settings.CV_PROVIDER or "gemini").strip().lower()

    if name == DetectionSource.GEMINI.value:
        return GeminiProvider(
            indicator_labels=build_indicator_label_map(indicator_rows or [])
        )
    if name == DetectionSource.ONNX_YOLO.value:
        return OnnxYoloProvider(
            indicator_labels=build_indicator_label_map(indicator_rows or [])
        )
    if name == DetectionSource.HEURISTIC.value:
        return HeuristicProvider()

    raise CvError(
        f"Unknown CV_PROVIDER {name!r}",
        "Hygiene photo checks are misconfigured.",
        retryable=False,
    )


def run_detection(
    image_bytes: bytes, view: ViewCategory, indicator_rows=None
) -> CvResult:
    """Detect hygiene indicators in one stall photo.

    The single entry point services/hygiene/ calls. Errors are CvError
    subclasses carrying a vendor-safe message, never a bare exception.
    """
    image = decode_image(image_bytes)
    provider = get_provider(indicator_rows)
    result = provider.detect(image, view)

    logger.info(
        "CV detection view=%s provider=%s detections=%d",
        view.value,
        result.provider,
        len(result.detections),
    )
    return result
