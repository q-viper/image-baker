import base64
import io
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPolygonF

from imagebaker.core.defs import Annotation
from imagebaker.utils.transform_mask import mask_to_polygons
from imagebaker.web.models import qcolor_to_hex


def serialize_annotation(ann: Annotation) -> dict[str, Any]:
    """Serialize an Annotation instance into a JSON-compatible dictionary."""
    rect = None
    if ann.rectangle is not None:
        rect = [
            float(ann.rectangle.x()),
            float(ann.rectangle.y()),
            float(ann.rectangle.x() + ann.rectangle.width()),
            float(ann.rectangle.y() + ann.rectangle.height()),
        ]
    poly = None
    if ann.polygon is not None and len(ann.polygon) > 0:
        poly = [[float(p.x()), float(p.y())] for p in ann.polygon]
    pts = None
    if ann.points:
        pts = [[float(p.x()), float(p.y())] for p in ann.points]

    has_mask = ann.mask is not None and np.any(ann.mask)
    mask_b64 = None
    if has_mask:
        mask_arr = np.asarray(ann.mask, dtype=np.uint8)
        if mask_arr.max() <= 1:
            mask_arr = mask_arr * 255
        pil_m = Image.fromarray(mask_arr, mode="L")
        buf = io.BytesIO()
        pil_m.save(buf, format="PNG")
        mask_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    ann_type = "point"
    if rect is not None:
        ann_type = "rectangle"
    elif poly is not None:
        ann_type = "polygon"
    elif has_mask:
        ann_type = "mask"

    rgb = [ann.color.red(), ann.color.green(), ann.color.blue()]
    return {
        "annotation_id": int(ann.annotation_id),
        "name": ann.name,
        "type": ann_type,
        "label": ann.label,
        "color": rgb,
        "color_hex": qcolor_to_hex(ann.color),
        "rgb": rgb,
        "points": pts or [],
        "rectangle": rect,
        "polygon": poly or [],
        "has_mask": bool(has_mask),
        "mask_png_b64": mask_b64,
        "is_complete": bool(ann.is_complete),
        "selected": bool(ann.selected),
        "score": float(ann.score) if ann.score is not None else None,
        "annotator": ann.annotator or "User",
        "annotation_time": ann.annotation_time or "",
        "visible": bool(ann.visible),
        "file_path": str(ann.file_path),
        "file_stem": Path(ann.file_path).stem[:15],
        "is_model_generated": bool(ann.is_model_generated),
        "model_name": ann.model_name,
        "caption": ann.caption or "",
    }


def deserialize_annotation(
    d: dict[str, Any],
    index: int,
    default_file_path: Path,
    fallback_label: str = "Undefined",
    get_label_color_fn: Callable[[str], QColor] | None = None,
    ensure_label_fn: Callable[[str], bool] | None = None,
) -> Annotation:
    """Deserialize a dictionary payload into a live Annotation instance."""
    label = (d.get("label") or fallback_label or "Undefined").strip() or "Undefined"
    if ensure_label_fn is not None:
        ensure_label_fn(label)

    if get_label_color_fn is not None:
        color = get_label_color_fn(label)
    else:
        color = QColor(0, 255, 0)

    ann = Annotation(
        annotation_id=index,
        label=label,
        color=color,
        is_complete=bool(d.get("is_complete", True)),
        selected=bool(d.get("selected", False)),
        score=d.get("score"),
        annotator=d.get("annotator") or "User",
        annotation_time=d.get("annotation_time")
        or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        visible=bool(d.get("visible", True)),
        file_path=Path(d.get("file_path") or default_file_path),
        is_model_generated=bool(d.get("is_model_generated", False)),
        model_name=d.get("model_name"),
        caption=d.get("caption") or "",
    )
    if d.get("points"):
        ann.points = [QPointF(float(p[0]), float(p[1])) for p in d["points"]]
    if d.get("rectangle"):
        r = d["rectangle"]
        if len(r) == 4:
            x1, y1, x2, y2 = float(r[0]), float(r[1]), float(r[2]), float(r[3])
            ann.rectangle = QRectF(
                min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
            )
    if d.get("polygon"):
        ann.polygon = QPolygonF(
            [QPointF(float(p[0]), float(p[1])) for p in d["polygon"]]
        )
    if d.get("mask_png_b64"):
        raw = base64.b64decode(d["mask_png_b64"])
        pil_m = Image.open(io.BytesIO(raw)).convert("L")
        ann.mask = (np.array(pil_m, dtype=np.uint8) > 0).astype(np.uint8)
    elif d.get("mask") is not None:
        ann.mask = np.array(d["mask"], dtype=np.uint8)

    # Apply any client-side mask translation offsets
    offset_x = int(round(float(d.get("mask_offset_x", 0.0) or 0.0)))
    offset_y = int(round(float(d.get("mask_offset_y", 0.0) or 0.0)))
    if ann.mask is not None and (offset_x != 0 or offset_y != 0):
        h, w = ann.mask.shape[:2]
        shifted = np.zeros_like(ann.mask)
        sx1 = max(0, -offset_x)
        sy1 = max(0, -offset_y)
        sx2 = min(w, w - offset_x)
        sy2 = min(h, h - offset_y)
        dx1 = max(0, offset_x)
        dy1 = max(0, offset_y)
        dx2 = min(w, offset_x + (sx2 - sx1))
        dy2 = min(h, offset_y + (sy2 - sy1))
        if sx2 > sx1 and sy2 > sy1 and dx2 > dx1 and dy2 > dy1:
            shifted[dy1:dy2, dx1:dx2] = ann.mask[sy1:sy2, sx1:sx2]
        ann.mask = shifted

    if ann.mask is not None and (ann.polygon is None or len(ann.polygon) == 0):
        polys = mask_to_polygons(
            (ann.mask > 0).astype(np.uint8) * 255, merge_polygons=True
        )
        if polys and len(polys[0]) >= 3:
            ann.polygon = QPolygonF(
                [QPointF(float(p[0]), float(p[1])) for p in polys[0]]
            )
    if ann.mask is not None and ann.rectangle is None:
        mask_uint8 = (ann.mask > 0).astype(np.uint8) * 255
        bx, by, bw, bh = cv2.boundingRect(mask_uint8)
        if bw > 0 and bh > 0:
            ann.rectangle = QRectF(bx, by, bw, bh)
    return ann
