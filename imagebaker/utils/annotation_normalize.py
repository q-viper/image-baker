from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPolygonF

from imagebaker.core.defs.defs import Annotation, AnnotationFormat
from imagebaker.utils.rle import _extract_mask_geometry, mask_to_rle, rle_to_mask

UNDEFINED_LABEL = "Undefined"
SUPPORTED_ANNOTATION_FORMATS = tuple(f.value for f in AnnotationFormat)


def _deterministic_color_rgb(label: str) -> list[int]:
    if not label or label == UNDEFINED_LABEL:
        return [180, 180, 180]
    h = sum(ord(ch) * (idx + 1) for idx, ch in enumerate(label))
    return [
        60 + (h * 53) % 180,
        60 + (h * 97) % 180,
        60 + (h * 193) % 180,
    ]


def normalize_annotation_dict(ann: Any, idx: int = 1) -> dict[str, Any]:
    """Convert an Annotation object or dict into a canonical dictionary."""
    if isinstance(ann, Annotation):
        rect = None
        if ann.rectangle is not None and not ann.rectangle.isNull():
            rect = [
                int(ann.rectangle.x()),
                int(ann.rectangle.y()),
                int(ann.rectangle.width()),
                int(ann.rectangle.height()),
            ]
        poly = []
        if ann.polygon is not None and not ann.polygon.isEmpty():
            poly = [[float(pt.x()), float(pt.y())] for pt in ann.polygon]
        pts = []
        if ann.points:
            pts = [[float(pt.x()), float(pt.y())] for pt in ann.points]
        mask_polys: list[list[list[float]]] = []
        mask_poly = []
        mask_rect = None
        mask_area = 0.0
        rle: list[int] = []
        mask_size: list[int] | None = None
        if ann.mask is not None and ann.mask.size > 0 and np.any(ann.mask):
            mask_arr = np.asarray(ann.mask)
            if mask_arr.ndim == 3:
                mask_arr = mask_arr[:, :, -1] if mask_arr.shape[2] == 4 else mask_arr[:, :, 0]
            rle = mask_to_rle(mask_arr)
            mask_size = [int(mask_arr.shape[0]), int(mask_arr.shape[1])]
            mask_polys, mask_poly, mask_rect, mask_area = _extract_mask_geometry(mask_arr)
        if rect is None and poly:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            min_x, max_x = int(min(xs)), int(max(xs))
            min_y, max_y = int(min(ys)), int(max(ys))
            rect = [min_x, min_y, max(1, max_x - min_x), max(1, max_y - min_y)]
        label = ann.label or UNDEFINED_LABEL
        color = [ann.color.red(), ann.color.green(), ann.color.blue()]
        is_brush = bool(rle and not poly and rect is None)
        return {
            "annotation_id": int(getattr(ann, "annotation_id", idx) or idx),
            "label_id": int(getattr(ann, "label_id", 0) or 0),
            "label": label,
            "type": "brushlabels" if is_brush else (
                "polygon" if poly else ("rectangle" if rect else "point")
            ),
            "format": "rle" if rle else None,
            "brushlabels": [label] if rle else None,
            "rle": rle if rle else None,
            "mask_size": mask_size,
            "score": getattr(ann, "score", None),
            "caption": getattr(ann, "caption", "") or "",
            "visible": bool(getattr(ann, "visible", True)),
            "is_crowd": bool(getattr(ann, "iscrowd", False)),
            "color": color,
            "points": pts,
            "rectangle": rect,
            "polygon": poly,
            "mask": None,
            "_mask_polygon": mask_poly,
            "_mask_polygons": mask_polys,
            "_mask_rectangle": mask_rect,
            "_mask_area": mask_area,
            "image_path": str(getattr(ann, "file_path", "") or ""),
            "layer_id": str(getattr(ann, "layer_id", "") or ""),
            "allow_export": bool(getattr(ann, "allow_annotation_export", True)),
        }

    if isinstance(ann, dict):
        val_dict = ann.get("value") if isinstance(ann.get("value"), dict) else {}
        brushlabels = (
            ann.get("brushlabels")
            or val_dict.get("brushlabels")
            or []
        )
        raw_label = (
            ann.get("label")
            or (brushlabels[0] if isinstance(brushlabels, list) and brushlabels else None)
            or UNDEFINED_LABEL
        )
        label = str(raw_label)
        color = ann.get("color")
        if not isinstance(color, (list, tuple)) or len(color) < 3:
            color = _deterministic_color_rgb(label)
        else:
            color = [int(color[0]), int(color[1]), int(color[2])]

        pts_raw = ann.get("points") or []
        pts = []
        for p in pts_raw:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append([float(p[0]), float(p[1])])
            elif hasattr(p, "x") and hasattr(p, "y"):
                pts.append([float(p.x()), float(p.y())])

        poly_raw = ann.get("polygon") or []
        poly = []
        for p in poly_raw:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                poly.append([float(p[0]), float(p[1])])
            elif hasattr(p, "x") and hasattr(p, "y"):
                poly.append([float(p.x()), float(p.y())])

        rect_raw = ann.get("rectangle") or ann.get("bbox")
        rect = None
        if isinstance(rect_raw, (list, tuple)) and len(rect_raw) == 4:
            rect = [
                int(round(float(rect_raw[0]))),
                int(round(float(rect_raw[1]))),
                int(round(float(rect_raw[2]))),
                int(round(float(rect_raw[3]))),
            ]
        elif hasattr(rect_raw, "x") and hasattr(rect_raw, "width"):
            rect = [
                int(rect_raw.x()),
                int(rect_raw.y()),
                int(rect_raw.width()),
                int(rect_raw.height()),
            ]

        rle_raw = ann.get("rle") or val_dict.get("rle")
        mask_size_raw = (
            ann.get("mask_size")
            or ann.get("size")
            or val_dict.get("mask_size")
            or (
                [int(ann["original_height"]), int(ann["original_width"])]
                if "original_height" in ann and "original_width" in ann
                else None
            )
        )
        mask_raw = ann.get("mask")
        mask_arr = None
        if rle_raw and mask_size_raw and len(mask_size_raw) == 2:
            mask_arr = rle_to_mask(rle_raw, int(mask_size_raw[0]), int(mask_size_raw[1]))
        elif mask_raw is not None:
            mask_arr = np.array(mask_raw, dtype=np.uint8)
            if mask_arr.ndim >= 2 and mask_arr.size > 0 and np.any(mask_arr):
                rle_raw = mask_to_rle(mask_arr)
                mask_size_raw = [int(mask_arr.shape[0]), int(mask_arr.shape[1])]

        mask_polys, mask_poly, mask_rect, mask_area = _extract_mask_geometry(mask_arr)

        if rect is None and poly:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            min_x, max_x = int(min(xs)), int(max(xs))
            min_y, max_y = int(min(ys)), int(max(ys))
            rect = [min_x, min_y, max(1, max_x - min_x), max(1, max_y - min_y)]

        is_brush = bool(
            (rle_raw or mask_arr is not None)
            and not poly
            and rect is None
        )
        return {
            "annotation_id": int(ann.get("annotation_id", idx) or idx),
            "label_id": int(ann.get("label_id", 0) or 0),
            "label": label,
            "type": "brushlabels" if is_brush else (
                ann.get("type")
                or ("polygon" if poly else ("rectangle" if rect else "point"))
            ),
            "format": "rle" if rle_raw else ann.get("format"),
            "brushlabels": [label] if rle_raw else None,
            "rle": [int(c) for c in rle_raw] if rle_raw else None,
            "mask_size": [int(mask_size_raw[0]), int(mask_size_raw[1])]
            if (mask_size_raw and len(mask_size_raw) == 2)
            else None,
            "score": ann.get("score"),
            "caption": str(ann.get("caption") or ""),
            "visible": bool(ann.get("visible", True)),
            "is_crowd": bool(ann.get("is_crowd", ann.get("iscrowd", False))),
            "color": color,
            "points": pts,
            "rectangle": rect,
            "polygon": poly,
            "mask": None,
            "_mask_polygon": mask_poly,
            "_mask_polygons": mask_polys,
            "_mask_rectangle": mask_rect,
            "_mask_area": mask_area,
            "image_path": str(ann.get("image_path") or ann.get("file_path") or ""),
            "layer_id": str(ann.get("layer_id") or ""),
            "allow_export": bool(ann.get("allow_export", True)),
        }

    raise TypeError(f"Unsupported annotation type: {type(ann)}")


def dict_to_annotation(data: dict[str, Any], file_path: Path = Path()) -> Annotation:
    """Convert a canonical dictionary into an ImageBaker Annotation instance."""
    norm = normalize_annotation_dict(data)
    points = [QPointF(p[0], p[1]) for p in norm["points"]]
    rect = QRectF(*norm["rectangle"]) if norm["rectangle"] else None
    polygon = (
        QPolygonF([QPointF(p[0], p[1]) for p in norm["polygon"]])
        if norm["polygon"]
        else None
    )
    mask = None
    if norm.get("rle") and norm.get("mask_size") and len(norm["mask_size"]) == 2:
        mask = rle_to_mask(
            norm["rle"], int(norm["mask_size"][0]), int(norm["mask_size"][1])
        )
    elif norm.get("mask") is not None:
        mask = np.array(norm["mask"], dtype=np.uint8)
    resolved_path = Path(norm["image_path"]) if norm["image_path"] else file_path

    return Annotation(
        annotation_id=norm["annotation_id"],
        label_id=norm["label_id"],
        label=norm["label"],
        score=norm["score"],
        file_path=resolved_path,
        points=points,
        rectangle=rect,
        polygon=polygon,
        mask=mask,
        color=QColor(*norm["color"]),
        visible=norm["visible"],
        iscrowd=norm["is_crowd"],
        caption=norm["caption"],
        layer_id=norm["layer_id"],
        is_complete=True,
    )


def _polygon_area(poly: list[list[float]]) -> float:
    if len(poly) < 3:
        return 0.0
    xs = np.array([p[0] for p in poly], dtype=np.float64)
    ys = np.array([p[1] for p in poly], dtype=np.float64)
    return float(0.5 * abs(np.dot(xs, np.roll(ys, 1)) - np.dot(ys, np.roll(xs, 1))))


def _infer_image_dimensions(
    annotations: list[dict[str, Any]],
    image_width: int | None = None,
    image_height: int | None = None,
    image_path: str | Path | None = None,
) -> tuple[int, int]:
    if image_width and image_height and image_width > 0 and image_height > 0:
        return int(image_width), int(image_height)

    if image_path:
        p = Path(image_path)
        if p.exists() and p.is_file():
            img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if img is not None:
                h, w = img.shape[:2]
                return int(w), int(h)

    max_x, max_y = 640, 640
    for ann in annotations:
        ms = ann.get("mask_size")
        if isinstance(ms, (list, tuple)) and len(ms) == 2:
            max_y = max(max_y, int(ms[0]))
            max_x = max(max_x, int(ms[1]))
        rect = ann.get("rectangle") or ann.get("_mask_rectangle")
        if rect:
            max_x = max(max_x, int(rect[0] + rect[2]))
            max_y = max(max_y, int(rect[1] + rect[3]))
        for pt in ann.get("polygon") or ann.get("_mask_polygon") or []:
            max_x = max(max_x, int(pt[0]) + 1)
            max_y = max(max_y, int(pt[1]) + 1)
        for pt in ann.get("points") or []:
            max_x = max(max_x, int(pt[0]) + 1)
            max_y = max(max_y, int(pt[1]) + 1)
    return max_x, max_y
