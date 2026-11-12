import json
import zipfile
from pathlib import Path
from typing import Any

from imagebaker.core.defs.defs import AnnotationFormat
from imagebaker.utils.annotation_normalize import (
    UNDEFINED_LABEL,
    _infer_image_dimensions,
    _polygon_area,
    normalize_annotation_dict,
)
from imagebaker.utils.transform_mask import merge_contours_with_bridge


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
                    "type": ann.get("type"),
                    "format": ann.get("format"),
                    "brushlabels": ann.get("brushlabels"),
                    "rle": ann.get("rle"),
                    "mask_size": ann.get("mask_size"),
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
            rect = ann.get("rectangle") or ann.get("_mask_rectangle")
            poly = ann.get("polygon") or ann.get("_mask_polygon") or []
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
            segmentation: list[list[float]] = []
            mask_polys = ann.get("_mask_polygons") or []
            explicit_poly = ann.get("polygon") or []
            if explicit_poly and len(explicit_poly) >= 3 and ann.get("type") != "brushlabels":
                flat_poly = []
                for p in explicit_poly:
                    flat_poly.extend([round(float(p[0]), 2), round(float(p[1]), 2)])
                segmentation = [flat_poly]
                area = _polygon_area(explicit_poly)
            elif mask_polys:
                for mp in mask_polys:
                    if len(mp) >= 3:
                        flat_poly = []
                        for p in mp:
                            flat_poly.extend(
                                [round(float(p[0]), 2), round(float(p[1]), 2)]
                            )
                        segmentation.append(flat_poly)
                area = float(
                    ann.get("_mask_area")
                    or sum(_polygon_area(mp) for mp in mask_polys)
                )
            elif len(poly) >= 3:
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
        mask_polys = ann.get("_mask_polygons") or []
        explicit_poly = ann.get("polygon") or []
        if explicit_poly and ann.get("type") != "brushlabels":
            poly = explicit_poly
        elif len(mask_polys) > 1:
            poly = merge_contours_with_bridge(mask_polys).tolist()
        elif mask_polys:
            poly = mask_polys[0]
        else:
            poly = ann.get("_mask_polygon") or []
        rect = ann.get("rectangle") or ann.get("_mask_rectangle")
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
