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
from imagebaker.utils.annotation_formats import mask_to_rle, rle_to_mask
from imagebaker.web.models import qcolor_to_hex


def serialize_annotation(ann: Annotation) -> dict[str, Any]:
    """Serialize an Annotation instance into a JSON-compatible dictionary."""
    rect = None
    if ann.rectangle is not None and not ann.rectangle.isNull():
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

    rgb = [ann.color.red(), ann.color.green(), ann.color.blue()]
    has_mask = ann.mask is not None and np.any(ann.mask)
    mask_b64 = None
    rle = None
    mask_size = None
    brush_bbox = None
    if has_mask:
        raw_mask = np.asarray(ann.mask)
        if raw_mask.ndim == 3:
            raw_mask = (
                raw_mask[:, :, -1]
                if raw_mask.shape[2] == 4
                else raw_mask[:, :, 0]
            )
        bin_mask = (raw_mask > 0).astype(np.uint8)
        h, w = bin_mask.shape[:2]
        mask_size = [int(h), int(w)]
        rle = mask_to_rle(bin_mask)
        ys, xs = np.nonzero(bin_mask)
        if len(xs) > 0 and len(ys) > 0:
            brush_bbox = [
                float(xs.min()),
                float(ys.min()),
                float(xs.max() + 1),
                float(ys.max() + 1),
            ]
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        fg = bin_mask > 0
        rgba[fg, 0] = rgb[0]
        rgba[fg, 1] = rgb[1]
        rgba[fg, 2] = rgb[2]
        rgba[fg, 3] = 215
        pil_m = Image.fromarray(rgba, mode="RGBA")
        buf = io.BytesIO()
        pil_m.save(buf, format="PNG")
        mask_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    ann_type = "point"
    if has_mask and (poly is None or len(poly) < 3) and rect is None:
        ann_type = "brush"
    elif poly is not None and len(poly) >= 3:
        ann_type = "polygon"
    elif rect is not None:
        ann_type = "rectangle"
    elif has_mask:
        ann_type = "brush"

    return {
        "annotation_id": int(ann.annotation_id),
        "name": ann.name,
        "type": ann_type,
        "format": "rle" if has_mask else None,
        "brushlabels": [ann.label] if has_mask else None,
        "rle": rle,
        "mask_size": mask_size,
        "brush_bbox": brush_bbox,
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
    val_dict = d.get("value") if isinstance(d.get("value"), dict) else {}
    brushlabels = d.get("brushlabels") or val_dict.get("brushlabels") or []
    raw_label = (
        d.get("label")
        or (brushlabels[0] if isinstance(brushlabels, list) and brushlabels else None)
        or fallback_label
        or "Undefined"
    )
    label = str(raw_label).strip() or "Undefined"
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
    is_explicit_brush = d.get("type") in ("brush", "brushlabels", "mask")
    if d.get("points") and not is_explicit_brush:
        ann.points = [QPointF(float(p[0]), float(p[1])) for p in d["points"]]
    if d.get("rectangle") and not is_explicit_brush:
        r = d["rectangle"]
        if len(r) == 4:
            x1, y1, x2, y2 = float(r[0]), float(r[1]), float(r[2]), float(r[3])
            ann.rectangle = QRectF(
                min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
            )
    if d.get("polygon") and not is_explicit_brush:
        ann.polygon = QPolygonF(
            [QPointF(float(p[0]), float(p[1])) for p in d["polygon"]]
        )

    rle_data = d.get("rle") or val_dict.get("rle")
    mask_size = (
        d.get("mask_size")
        or d.get("size")
        or val_dict.get("mask_size")
        or (
            [int(d["original_height"]), int(d["original_width"])]
            if "original_height" in d and "original_width" in d
            else None
        )
    )
    if rle_data is not None and mask_size and len(mask_size) == 2:
        ann.mask = rle_to_mask(rle_data, int(mask_size[0]), int(mask_size[1]))
    elif d.get("mask_png_b64"):
        raw = base64.b64decode(d["mask_png_b64"])
        pil_img = Image.open(io.BytesIO(raw))
        if pil_img.mode in ("RGBA", "LA"):
            arr_rgba = np.array(pil_img, dtype=np.uint8)
            alpha_ch = arr_rgba[:, :, -1]
            if np.any(alpha_ch < 255) and np.any(alpha_ch > 0):
                ann.mask = (alpha_ch > 0).astype(np.uint8)
            else:
                gray = np.array(pil_img.convert("L"), dtype=np.uint8)
                ann.mask = (gray > 0).astype(np.uint8)
        else:
            pil_m = pil_img.convert("L")
            ann.mask = (np.array(pil_m, dtype=np.uint8) > 0).astype(np.uint8)
    elif d.get("mask") is not None:
        ann.mask = (np.array(d["mask"], dtype=np.uint8) > 0).astype(np.uint8)

    # Apply optional brush_strokes list [{"points": [[x, y], ...], "size": 18, "erase": False}]
    brush_strokes = d.get("brush_strokes")
    if isinstance(brush_strokes, list) and len(brush_strokes) > 0:
        if ann.mask is None:
            mh = int(mask_size[0]) if (mask_size and len(mask_size) == 2) else 600
            mw = int(mask_size[1]) if (mask_size and len(mask_size) == 2) else 800
            if default_file_path and Path(default_file_path).is_file():
                img_check = cv2.imread(str(default_file_path), cv2.IMREAD_UNCHANGED)
                if img_check is not None:
                    mh, mw = img_check.shape[:2]
            ann.mask = np.zeros((mh, mw), dtype=np.uint8)
        else:
            ann.mask = (np.asarray(ann.mask) > 0).astype(np.uint8).copy()

        for stroke in brush_strokes:
            if not isinstance(stroke, dict):
                continue
            s_pts = stroke.get("points") or []
            s_size = max(1, int(round(float(stroke.get("size", 18) or 18))))
            s_val = 0 if stroke.get("erase") else 1
            if len(s_pts) == 1:
                px, py = int(round(float(s_pts[0][0]))), int(round(float(s_pts[0][1])))
                cv2.circle(
                    ann.mask,
                    (px, py),
                    max(1, s_size // 2),
                    s_val,
                    thickness=-1,
                    lineType=cv2.LINE_AA,
                )
            elif len(s_pts) >= 2:
                pts_np = np.array(
                    [[int(round(float(p[0]))), int(round(float(p[1])))] for p in s_pts],
                    dtype=np.int32,
                )
                cv2.polylines(
                    ann.mask,
                    [pts_np],
                    isClosed=False,
                    color=s_val,
                    thickness=s_size,
                    lineType=cv2.LINE_AA,
                )
        ann.mask = (ann.mask > 0).astype(np.uint8)

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

    return ann
