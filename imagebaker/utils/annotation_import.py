import io
import json
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from imagebaker.core.defs.defs import Annotation
from imagebaker.utils.annotation_normalize import (
    UNDEFINED_LABEL,
    _deterministic_color_rgb,
    dict_to_annotation,
    normalize_annotation_dict,
)
from imagebaker.utils.rle import mask_to_rle


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

            img_info = images_map.get(int(img_id), {}) if img_id is not None else {}
            file_name = img_info.get("file_name") or image_name or ""

            poly: list[list[float]] = []
            parsed_polys: list[list[list[float]]] = []
            coco_rle: list[int] | None = None
            coco_mask_size: list[int] | None = None
            seg = coco_ann.get("segmentation")

            if isinstance(seg, list) and seg:
                first_seg = seg[0]
                if isinstance(first_seg, (list, tuple)) and len(first_seg) == 2 and all(
                    isinstance(p, (list, tuple)) and len(p) == 2 for p in seg
                ):
                    parsed_polys = [[[float(p[0]), float(p[1])] for p in seg]]
                else:
                    for ring in seg:
                        if isinstance(ring, list) and len(ring) >= 6:
                            parsed_polys.append(
                                [
                                    [float(ring[i]), float(ring[i + 1])]
                                    for i in range(0, len(ring) - 1, 2)
                                ]
                            )

                if len(parsed_polys) == 1:
                    poly = parsed_polys[0]
                elif len(parsed_polys) > 1:
                    img_w = int(img_info.get("width") or image_width or 0)
                    img_h = int(img_info.get("height") or image_height or 0)
                    if img_w <= 0 or img_h <= 0:
                        max_x = max(p[0] for ring in parsed_polys for p in ring)
                        max_y = max(p[1] for ring in parsed_polys for p in ring)
                        if rect:
                            max_x = max(max_x, float(rect[0] + rect[2]))
                            max_y = max(max_y, float(rect[1] + rect[3]))
                        img_w = max(img_w, int(np.ceil(max_x)) + 2, 1)
                        img_h = max(img_h, int(np.ceil(max_y)) + 2, 1)
                    mask_arr = np.zeros((img_h, img_w), dtype=np.uint8)
                    for ring in parsed_polys:
                        pts_i32 = np.round(np.array(ring, dtype=np.float32)).astype(np.int32)
                        if len(pts_i32) >= 3:
                            cv2.fillPoly(mask_arr, [pts_i32], 255)
                    if np.any(mask_arr):
                        coco_rle = mask_to_rle(mask_arr)
                        coco_mask_size = [img_h, img_w]
                        rect = None
            elif isinstance(seg, dict) and "counts" in seg and "size" in seg:
                counts = seg.get("counts")
                sz = seg.get("size")
                if (
                    isinstance(counts, list)
                    and isinstance(sz, (list, tuple))
                    and len(sz) == 2
                ):
                    sh, sw = int(sz[0]), int(sz[1])
                    if sh > 0 and sw > 0:
                        c_ints = [max(0, int(c)) for c in counts]
                        if sum(c_ints) == sh * sw:
                            vals = np.arange(len(c_ints), dtype=np.uint8) % 2
                            mask_arr = (
                                np.repeat(vals, c_ints).reshape((sh, sw), order="F")
                                * 255
                            )
                            if np.any(mask_arr):
                                coco_rle = mask_to_rle(mask_arr)
                                coco_mask_size = [sh, sw]
                                rect = None

            pts: list[list[float]] = []
            kps = coco_ann.get("keypoints")
            if isinstance(kps, list) and len(kps) >= 3:
                for i in range(0, len(kps) - 2, 3):
                    v = kps[i + 2]
                    if v > 0:
                        pts.append([float(kps[i]), float(kps[i + 1])])

            ann_payload: dict[str, Any] = {
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
            }
            if coco_rle and coco_mask_size:
                ann_payload["type"] = "brushlabels"
                ann_payload["format"] = "rle"
                ann_payload["brushlabels"] = [label]
                ann_payload["rle"] = coco_rle
                ann_payload["mask_size"] = coco_mask_size

            results.append(normalize_annotation_dict(ann_payload, idx=idx))
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
