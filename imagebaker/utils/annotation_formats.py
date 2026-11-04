import io
import json
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPolygonF

from imagebaker.core.defs.defs import Annotation, AnnotationFormat

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
        mask_poly = []
        if ann.mask is not None and ann.mask.size > 0:
            mask_uint8 = (ann.mask > 0).astype(np.uint8) * 255
            contours, _ = cv2.findContours(
                mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if contours:
                largest = max(contours, key=cv2.contourArea)
                if len(largest) >= 3:
                    mask_poly = [[float(p[0][0]), float(p[0][1])] for p in largest]
        if not poly and mask_poly:
            poly = mask_poly
        if rect is None and poly:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            min_x, max_x = int(min(xs)), int(max(xs))
            min_y, max_y = int(min(ys)), int(max(ys))
            rect = [min_x, min_y, max(1, max_x - min_x), max(1, max_y - min_y)]
        label = ann.label or UNDEFINED_LABEL
        color = [ann.color.red(), ann.color.green(), ann.color.blue()]
        return {
            "annotation_id": int(getattr(ann, "annotation_id", idx) or idx),
            "label_id": int(getattr(ann, "label_id", 0) or 0),
            "label": label,
            "score": getattr(ann, "score", None),
            "caption": getattr(ann, "caption", "") or "",
            "visible": bool(getattr(ann, "visible", True)),
            "is_crowd": bool(getattr(ann, "iscrowd", False)),
            "color": color,
            "points": pts,
            "rectangle": rect,
            "polygon": poly,
            "mask": ann.mask.tolist() if ann.mask is not None else None,
            "image_path": str(getattr(ann, "file_path", "") or ""),
            "layer_id": str(getattr(ann, "layer_id", "") or ""),
            "allow_export": bool(getattr(ann, "allow_annotation_export", True)),
        }

    if isinstance(ann, dict):
        label = str(ann.get("label") or UNDEFINED_LABEL)
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

        mask_raw = ann.get("mask")
        if not poly and mask_raw is not None:
            mask_arr = np.array(mask_raw, dtype=np.uint8)
            if mask_arr.ndim >= 2 and mask_arr.size > 0:
                mask_uint8 = (mask_arr > 0).astype(np.uint8) * 255
                contours, _ = cv2.findContours(
                    mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                if contours:
                    largest = max(contours, key=cv2.contourArea)
                    if len(largest) >= 3:
                        poly = [[float(p[0][0]), float(p[0][1])] for p in largest]

        if rect is None and poly:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            min_x, max_x = int(min(xs)), int(max(xs))
            min_y, max_y = int(min(ys)), int(max(ys))
            rect = [min_x, min_y, max(1, max_x - min_x), max(1, max_y - min_y)]

        return {
            "annotation_id": int(ann.get("annotation_id", idx) or idx),
            "label_id": int(ann.get("label_id", 0) or 0),
            "label": label,
            "score": ann.get("score"),
            "caption": str(ann.get("caption") or ""),
            "visible": bool(ann.get("visible", True)),
            "is_crowd": bool(ann.get("is_crowd", ann.get("iscrowd", False))),
            "color": color,
            "points": pts,
            "rectangle": rect,
            "polygon": poly,
            "mask": mask_raw,
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
    mask = np.array(norm["mask"], dtype=np.uint8) if norm["mask"] is not None else None
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
        rect = ann.get("rectangle")
        if rect:
            max_x = max(max_x, int(rect[0] + rect[2]))
            max_y = max(max_y, int(rect[1] + rect[3]))
        for pt in ann.get("polygon") or []:
            max_x = max(max_x, int(pt[0]) + 1)
            max_y = max(max_y, int(pt[1]) + 1)
        for pt in ann.get("points") or []:
            max_x = max(max_x, int(pt[0]) + 1)
            max_y = max(max_y, int(pt[1]) + 1)
    return max_x, max_y


def export_annotations_data(
    annotations: list[Any],
    fmt: AnnotationFormat | str = AnnotationFormat.DEFAULT,
    image_name: str = "image.png",
    image_width: int | None = None,
    image_height: int | None = None,
    class_names: list[str] | None = None,
    image_id: int = 1,
) -> dict[str, Any]:
    """
    Export annotations to the specified format ('default', 'coco', or 'yolo').

    Returns a dictionary containing:
      - 'format': normalized format string
      - 'data': JSON-serializable structure (for default/coco) or dict with 'txt' & 'classes' (for yolo)
      - 'content': serialized string (JSON string for default/coco, YOLO lines for yolo)
      - 'classes': ordered list of class names
    """
    format_enum = AnnotationFormat.from_value(fmt)
    fmt_norm = format_enum.value

    norm_list = [
        normalize_annotation_dict(a, idx + 1) for idx, a in enumerate(annotations)
    ]
    norm_list = [a for a in norm_list if a.get("allow_export", True)]

    # Build ordered class list
    ordered_classes: list[str] = []
    if class_names:
        for c in class_names:
            if c and c not in ordered_classes:
                ordered_classes.append(c)
    for ann in norm_list:
        lbl = ann["label"] or UNDEFINED_LABEL
        if lbl not in ordered_classes:
            ordered_classes.append(lbl)
    if not ordered_classes:
        ordered_classes = [UNDEFINED_LABEL]

    w, h = _infer_image_dimensions(norm_list, image_width, image_height)

    if fmt_norm == "default":
        default_payload = []
        for idx, ann in enumerate(norm_list, start=1):
            lbl = ann["label"] or UNDEFINED_LABEL
            cid = ordered_classes.index(lbl) if lbl in ordered_classes else 0
            default_payload.append(
                {
                    "annotation_id": ann.get("annotation_id", idx),
                    "label_id": cid,
                    "label": lbl,
                    "score": ann.get("score"),
                    "caption": ann.get("caption", ""),
                    "visible": ann.get("visible", True),
                    "is_crowd": ann.get("is_crowd", False),
                    "color": ann.get("color", [0, 255, 0]),
                    "points": ann.get("points", []),
                    "rectangle": ann.get("rectangle"),
                    "polygon": ann.get("polygon", []),
                    "mask": ann.get("mask"),
                    "image_path": ann.get("image_path") or image_name,
                    "layer_id": ann.get("layer_id", ""),
                }
            )
        return {
            "format": "default",
            "data": default_payload,
            "content": json.dumps(default_payload, indent=2),
            "classes": ordered_classes,
        }

    if fmt_norm == "coco":
        categories = [
            {"id": idx + 1, "name": name, "supercategory": "object"}
            for idx, name in enumerate(ordered_classes)
        ]
        cat_lookup = {c["name"]: c["id"] for c in categories}
        coco_anns = []
        for idx, ann in enumerate(norm_list, start=1):
            lbl = ann["label"] or UNDEFINED_LABEL
            cat_id = cat_lookup.get(lbl, 1)
            rect = ann.get("rectangle")
            poly = ann.get("polygon") or []
            pts = ann.get("points") or []

            if rect is None and pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                min_x, max_x = float(min(xs)), float(max(xs))
                min_y, max_y = float(min(ys)), float(max(ys))
                rect = [
                    min_x,
                    min_y,
                    max(4.0, max_x - min_x),
                    max(4.0, max_y - min_y),
                ]

            bbox = [float(x) for x in rect] if rect else [0.0, 0.0, 0.0, 0.0]
            segmentation = []
            if len(poly) >= 3:
                flat_poly = []
                for p in poly:
                    flat_poly.extend([round(float(p[0]), 2), round(float(p[1]), 2)])
                segmentation = [flat_poly]
                area = _polygon_area(poly)
            else:
                area = float(bbox[2] * bbox[3])

            coco_entry: dict[str, Any] = {
                "id": idx,
                "image_id": int(image_id),
                "category_id": int(cat_id),
                "bbox": [round(v, 2) for v in bbox],
                "area": round(area, 2),
                "segmentation": segmentation,
                "iscrowd": 1 if ann.get("is_crowd") else 0,
            }
            if pts:
                keypoints = []
                for p in pts:
                    keypoints.extend([round(float(p[0]), 2), round(float(p[1]), 2), 2])
                coco_entry["keypoints"] = keypoints
                coco_entry["num_keypoints"] = len(pts)
            if ann.get("caption"):
                coco_entry["caption"] = ann["caption"]
            coco_anns.append(coco_entry)

        coco_payload = {
            "info": {"description": "ImageBaker COCO Export", "version": "1.0"},
            "licenses": [],
            "images": [
                {
                    "id": int(image_id),
                    "file_name": Path(image_name).name if image_name else "image.png",
                    "width": int(w),
                    "height": int(h),
                }
            ],
            "categories": categories,
            "annotations": coco_anns,
        }
        return {
            "format": "coco",
            "data": coco_payload,
            "content": json.dumps(coco_payload, indent=2),
            "classes": ordered_classes,
        }

    # YOLO format
    yolo_lines = []
    for ann in norm_list:
        lbl = ann["label"] or UNDEFINED_LABEL
        class_idx = ordered_classes.index(lbl) if lbl in ordered_classes else 0
        poly = ann.get("polygon") or []
        rect = ann.get("rectangle")
        pts = ann.get("points") or []

        if len(poly) >= 3:
            coords = []
            for p in poly:
                nx = min(1.0, max(0.0, float(p[0]) / float(w)))
                ny = min(1.0, max(0.0, float(p[1]) / float(h)))
                coords.append(f"{nx:.6f} {ny:.6f}")
            yolo_lines.append(f"{class_idx} " + " ".join(coords))
        elif rect is not None and rect[2] > 0 and rect[3] > 0:
            rx, ry, rw, rh = [float(v) for v in rect]
            cx = min(1.0, max(0.0, (rx + rw / 2.0) / float(w)))
            cy = min(1.0, max(0.0, (ry + rh / 2.0) / float(h)))
            nw = min(1.0, max(0.0, rw / float(w)))
            nh = min(1.0, max(0.0, rh / float(h)))
            yolo_lines.append(f"{class_idx} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
        elif pts:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            rw = max(4.0, max_x - min_x)
            rh = max(4.0, max_y - min_y)
            cx = min(1.0, max(0.0, ((min_x + max_x) / 2.0) / float(w)))
            cy = min(1.0, max(0.0, ((min_y + max_y) / 2.0) / float(h)))
            nw = min(1.0, max(0.0, rw / float(w)))
            nh = min(1.0, max(0.0, rh / float(h)))
            yolo_lines.append(f"{class_idx} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")

    yolo_txt = "\n".join(yolo_lines)
    classes_txt = "\n".join(ordered_classes)
    return {
        "format": "yolo",
        "data": {
            "txt": yolo_txt,
            "classes_txt": classes_txt,
            "classes": ordered_classes,
            "width": w,
            "height": h,
        },
        "content": yolo_txt,
        "classes": ordered_classes,
    }


def save_annotations_to_path(
    annotations: list[Any],
    output_path: str | Path,
    fmt: AnnotationFormat | str = AnnotationFormat.DEFAULT,
    image_name: str = "image.png",
    image_width: int | None = None,
    image_height: int | None = None,
    class_names: list[str] | None = None,
) -> Path:
    """Save annotations to disk in 'default', 'coco', or 'yolo' format."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    format_enum = AnnotationFormat.from_value(fmt)
    exported = export_annotations_data(
        annotations=annotations,
        fmt=format_enum,
        image_name=image_name,
        image_width=image_width,
        image_height=image_height,
        class_names=class_names,
    )
    fmt_norm = exported["format"]
    if fmt_norm in ("default", "coco"):
        out.write_text(exported["content"], encoding="utf-8")
        return out

    # YOLO
    if out.suffix.lower() == ".zip":
        stem = Path(image_name).stem or "annotations"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"labels/{stem}.txt", exported["data"]["txt"])
            zf.writestr("classes.txt", exported["data"]["classes_txt"])
        return out

    out.write_text(exported["data"]["txt"], encoding="utf-8")
    classes_file = out.parent / "classes.txt"
    classes_file.write_text(exported["data"]["classes_txt"], encoding="utf-8")
    return out


def load_annotation_dicts_from_data(
    content: str | bytes | dict | list,
    fmt: str = "auto",
    image_name: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    class_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Parse annotations from 'default', 'coco', or 'yolo' content into canonical dicts.
    Supports auto-detection when fmt='auto'.
    """
    fmt_norm = (fmt or "auto").strip().lower()
    w = int(image_width) if image_width and image_width > 0 else 640
    h = int(image_height) if image_height and image_height > 0 else 640

    parsed_obj: Any = None
    raw_text: str = ""

    if isinstance(content, (dict, list)):
        parsed_obj = content
    elif isinstance(content, bytes):
        # Check if ZIP archive
        if content[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                names = zf.namelist()
                if "classes.txt" in names and not class_names:
                    class_names = [
                        line.strip()
                        for line in zf.read("classes.txt")
                        .decode("utf-8", errors="ignore")
                        .splitlines()
                        if line.strip()
                    ]
                target_txt = None
                if image_name:
                    stem = Path(image_name).stem
                    for n in names:
                        if Path(n).stem == stem and n.endswith(".txt") and Path(n).name != "classes.txt":
                            target_txt = n
                            break
                if target_txt is None:
                    txts = [
                        n
                        for n in names
                        if n.endswith(".txt") and Path(n).name != "classes.txt"
                    ]
                    if txts:
                        target_txt = txts[0]
                if target_txt:
                    raw_text = zf.read(target_txt).decode("utf-8", errors="ignore")
                    fmt_norm = "yolo"
        else:
            raw_text = content.decode("utf-8", errors="ignore")
    else:
        raw_text = str(content)

    if parsed_obj is None and raw_text.strip():
        stripped = raw_text.strip()
        if fmt_norm in ("auto", "default", "coco") and stripped[0] in ("[", "{"):
            try:
                parsed_obj = json.loads(stripped)
            except json.JSONDecodeError:
                if fmt_norm in ("default", "coco"):
                    raise

    # Detect format if auto
    if fmt_norm == "auto":
        if isinstance(parsed_obj, list):
            fmt_norm = "default"
        elif isinstance(parsed_obj, dict):
            if "annotations" in parsed_obj and (
                "categories" in parsed_obj or "images" in parsed_obj
            ):
                fmt_norm = "coco"
            else:
                fmt_norm = "default"
        else:
            fmt_norm = "yolo"

    if fmt_norm == "default":
        if isinstance(parsed_obj, dict):
            raw_anns = parsed_obj.get("annotations", [])
        elif isinstance(parsed_obj, list):
            raw_anns = parsed_obj
        else:
            raw_anns = []
        return [
            normalize_annotation_dict(a, idx + 1) for idx, a in enumerate(raw_anns)
        ]

    if fmt_norm == "coco":
        if not isinstance(parsed_obj, dict):
            raise ValueError("COCO annotations must be a JSON object.")
        categories = {
            int(c["id"]): str(c.get("name") or UNDEFINED_LABEL)
            for c in parsed_obj.get("categories", [])
            if "id" in c
        }
        images_map = {
            int(img["id"]): img
            for img in parsed_obj.get("images", [])
            if "id" in img
        }
        target_image_ids: set[int] | None = None
        if image_name and images_map:
            target_basename = Path(image_name).name
            matched_ids = {
                img_id
                for img_id, img_info in images_map.items()
                if Path(str(img_info.get("file_name", ""))).name == target_basename
            }
            if matched_ids:
                target_image_ids = matched_ids

        results: list[dict[str, Any]] = []
        for idx, coco_ann in enumerate(parsed_obj.get("annotations", []), start=1):
            img_id = coco_ann.get("image_id")
            if (
                target_image_ids is not None
                and img_id is not None
                and int(img_id) not in target_image_ids
            ):
                continue

            cat_id = int(coco_ann.get("category_id", 0) or 0)
            label = categories.get(cat_id, coco_ann.get("label") or UNDEFINED_LABEL)
            color = _deterministic_color_rgb(label)

            bbox = coco_ann.get("bbox")
            rect = None
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                rect = [
                    int(round(float(bbox[0]))),
                    int(round(float(bbox[1]))),
                    max(1, int(round(float(bbox[2])))),
                    max(1, int(round(float(bbox[3])))),
                ]

            poly: list[list[float]] = []
            seg = coco_ann.get("segmentation")
            if isinstance(seg, list) and seg:
                first_seg = seg[0]
                if isinstance(first_seg, list) and len(first_seg) >= 6:
                    poly = [
                        [float(first_seg[i]), float(first_seg[i + 1])]
                        for i in range(0, len(first_seg) - 1, 2)
                    ]
                elif isinstance(first_seg, (list, tuple)) and len(first_seg) == 2:
                    poly = [[float(p[0]), float(p[1])] for p in seg]

            pts: list[list[float]] = []
            kps = coco_ann.get("keypoints")
            if isinstance(kps, list) and len(kps) >= 3:
                for i in range(0, len(kps) - 2, 3):
                    v = kps[i + 2]
                    if v > 0:
                        pts.append([float(kps[i]), float(kps[i + 1])])

            img_info = images_map.get(int(img_id), {}) if img_id is not None else {}
            file_name = img_info.get("file_name") or image_name or ""

            results.append(
                normalize_annotation_dict(
                    {
                        "annotation_id": int(coco_ann.get("id", idx) or idx),
                        "label_id": cat_id,
                        "label": label,
                        "caption": str(coco_ann.get("caption") or ""),
                        "visible": True,
                        "is_crowd": bool(coco_ann.get("iscrowd", 0)),
                        "color": color,
                        "points": pts,
                        "rectangle": rect,
                        "polygon": poly,
                        "image_path": file_name,
                    },
                    idx=idx,
                )
            )
        return results

    if fmt_norm == "yolo":
        if isinstance(parsed_obj, dict) and "txt" in parsed_obj:
            raw_text = str(parsed_obj["txt"])
            if not class_names and "classes" in parsed_obj:
                class_names = list(parsed_obj["classes"])

        results = []
        for idx, line in enumerate(raw_text.splitlines(), start=1):
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#"):
                continue
            parts = stripped_line.split()
            if len(parts) < 5:
                continue
            try:
                class_id = int(float(parts[0]))
                coords = [float(x) for x in parts[1:]]
            except ValueError:
                continue

            if class_names and 0 <= class_id < len(class_names):
                label = class_names[class_id]
            else:
                label = f"class_{class_id}" if class_id >= 0 else UNDEFINED_LABEL

            color = _deterministic_color_rgb(label)
            rect = None
            poly = []

            if len(coords) == 4:
                cx, cy, nw, nh = coords
                # Check if normalized [0, 1] or already pixel coordinates
                if max(cx, cy, nw, nh) <= 1.5:
                    bw = max(1, int(round(nw * w)))
                    bh = max(1, int(round(nh * h)))
                    bx = int(round(cx * w - bw / 2.0))
                    by = int(round(cy * h - bh / 2.0))
                else:
                    bw = max(1, int(round(nw)))
                    bh = max(1, int(round(nh)))
                    bx = int(round(cx - bw / 2.0))
                    by = int(round(cy - bh / 2.0))
                rect = [bx, by, bw, bh]
            elif len(coords) >= 6 and len(coords) % 2 == 0:
                is_normalized = max(coords) <= 1.5
                for i in range(0, len(coords), 2):
                    px = coords[i] * w if is_normalized else coords[i]
                    py = coords[i + 1] * h if is_normalized else coords[i + 1]
                    poly.append([round(float(px), 2), round(float(py), 2)])

            results.append(
                normalize_annotation_dict(
                    {
                        "annotation_id": idx,
                        "label_id": class_id,
                        "label": label,
                        "visible": True,
                        "is_crowd": False,
                        "color": color,
                        "points": [],
                        "rectangle": rect,
                        "polygon": poly,
                        "image_path": image_name or "",
                    },
                    idx=idx,
                )
            )
        return results

    raise ValueError(f"Unsupported annotation format: {fmt}")


def load_annotations_from_path(
    file_path: str | Path,
    fmt: str = "auto",
    image_name: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    class_names: list[str] | None = None,
) -> list[Annotation]:
    """Load Annotation instances from a file on disk ('default', 'coco', or 'yolo')."""
    path = Path(file_path)
    if not path.exists():
        return []

    if class_names is None:
        classes_txt = path.parent / "classes.txt"
        if classes_txt.exists():
            class_names = [
                line.strip()
                for line in classes_txt.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    if path.suffix.lower() == ".zip":
        content: bytes | str = path.read_bytes()
    else:
        content = path.read_text(encoding="utf-8")

    dicts = load_annotation_dicts_from_data(
        content=content,
        fmt=fmt,
        image_name=image_name,
        image_width=image_width,
        image_height=image_height,
        class_names=class_names,
    )
    return [dict_to_annotation(d, file_path=path) for d in dicts]
