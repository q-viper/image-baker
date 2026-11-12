from __future__ import annotations

import base64
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPixmap

from imagebaker import logger
from imagebaker.core.defs import Annotation, Label
from imagebaker.utils.annotation_formats import (
    dict_to_annotation,
    export_annotations_data,
    load_annotation_dicts_from_data,
    load_annotations_from_path,
    save_annotations_to_path,
    shift_binary_mask,
)
from imagebaker.web.models import ImageUndoHistory, WebImageEntry, hex_to_qcolor


class WebEngineLayerifyMixin:
    """Image browsing/upload, Layerify annotation CRUD/IO, and label management."""

    # -------------------------------------------------------------------------
    # Image Loading & Selection
    # -------------------------------------------------------------------------
    def _probe_image_size(self, img_path: Path) -> tuple[int, int]:
        try:
            with Image.open(img_path) as im:
                return im.size
        except Exception:
            pix = QPixmap(str(img_path))
            return pix.width(), pix.height()

    def _load_images_from_folder(self, folder_path: Path):
        self.image_entries = []
        valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
        if folder_path.exists() and folder_path.is_dir():
            if self.layer_config.full_search:
                paths = sorted(folder_path.rglob("*.*"))
            else:
                paths = sorted(folder_path.glob("*.*"))
            for p in paths:
                if p.is_file() and p.suffix.lower() in valid_exts:
                    w, h = self._probe_image_size(p)
                    if w > 0 and h > 0:
                        self.image_entries.append(
                            WebImageEntry(is_baked_result=False, file_path=p.resolve(), width=w, height=h)
                        )

        bake_folder = self.layer_config.bake_dir
        if bake_folder.exists() and bake_folder.is_dir():
            for p in sorted(bake_folder.glob("*.*")):
                if p.is_file() and p.suffix.lower() in valid_exts:
                    w, h = self._probe_image_size(p)
                    if w > 0 and h > 0:
                        self.image_entries.append(
                            WebImageEntry(is_baked_result=True, file_path=p.resolve(), width=w, height=h)
                        )

    def _select_image_by_index(self, idx: int, save_previous: bool = True):
        if not self.image_entries:
            self.curr_image_idx = 0
            self.current_annotations = []
            return
        if save_previous:
            self.save_current_image_annotations(delete_if_empty=False)
        idx = max(0, min(len(self.image_entries) - 1, int(idx)))
        self.curr_image_idx = idx
        entry = self.image_entries[idx]
        self.current_annotations = self.load_image_annotations(entry.file_path)
        self.last_message = f"Showing image {self.curr_image_idx + 1}/{len(self.image_entries)}"

    def remove_image(self, index: int) -> tuple[bool, str]:
        """Remove an image entry from the Layerify image list (without deleting the file)."""
        with self.lock:
            if not self.image_entries or index < 0 or index >= len(self.image_entries):
                return False, "Image index out of range."

            removed = self.image_entries[index]
            if index == self.curr_image_idx:
                self.save_current_image_annotations(delete_if_empty=False)

            self.image_entries.pop(index)

            if not self.image_entries:
                self.curr_image_idx = 0
                self.current_annotations = []
            elif index == self.curr_image_idx:
                next_idx = min(index, len(self.image_entries) - 1)
                self._select_image_by_index(next_idx, save_previous=False)
            elif index < self.curr_image_idx:
                self.curr_image_idx -= 1

            self.last_message = f"Removed image from list: {removed.file_path.name}"
            logger.info(self.last_message)
            return True, self.last_message

    def select_folder(self, folder_path_str: str) -> tuple[bool, str]:
        with self.lock:
            self.save_current_image_annotations(delete_if_empty=False)
            folder_path = Path(folder_path_str).expanduser().resolve()
            if not folder_path.exists() or not folder_path.is_dir():
                return False, f"Folder not found: {folder_path}"
            self._load_images_from_folder(folder_path)
            if not self.image_entries:
                self.current_annotations = []
                self.curr_image_idx = 0
                return False, f"No valid image files found in {folder_path}"
            self._select_image_by_index(0, save_previous=False)
            msg = f"Loaded {len(self.image_entries)} images from {folder_path}"
            self.last_message = msg
            return True, msg

    def browse_directory(self, path_str: str | None = None) -> dict[str, Any]:
        target = Path(path_str).expanduser().resolve() if path_str else self.project_dir
        if not target.exists() or not target.is_dir():
            target = self.project_dir
        valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
        subdirs = []
        images = []
        image_count = 0
        try:
            for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    subdirs.append({"name": item.name, "path": str(item.resolve())})
                elif item.is_file() and item.suffix.lower() in valid_exts:
                    image_count += 1
                    if len(images) < 100:
                        images.append({"name": item.name, "path": str(item.resolve())})
        except PermissionError:
            pass
        parent_str = str(target.parent) if target.parent != target else str(target)

        quick_paths = [
            {"name": "Project", "label": "Project", "path": str(self.project_dir)},
            {"name": "Assets", "label": "Assets", "path": str(self.layer_config.assets_folder.resolve())},
        ]
        home_dir = Path.home()
        if home_dir.exists():
            quick_paths.append({"name": "Home", "label": "Home", "path": str(home_dir.resolve())})
            for sub_name in ("Desktop", "Pictures", "Downloads"):
                candidate = home_dir / sub_name
                if candidate.exists() and candidate.is_dir():
                    quick_paths.append({"name": sub_name, "label": sub_name, "path": str(candidate.resolve())})

        return {
            "current": str(target),
            "current_path": str(target),
            "parent": parent_str,
            "parent_path": parent_str,
            "directories": subdirs,
            "images": images,
            "image_count": image_count,
            "quick_paths": quick_paths,
        }

    def upload_images(
        self, files: list[dict[str, str]], folder_name: str | None = None
    ) -> tuple[bool, str]:
        with self.lock:
            self.save_current_image_annotations(delete_if_empty=False)
            dest_dir = self.layer_config.assets_folder
            if folder_name:
                safe_folder = Path(folder_name).name.strip()
                if safe_folder and safe_folder not in {".", ".."}:
                    dest_dir = self.layer_config.assets_folder / safe_folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            saved_count = 0
            last_saved_path = None
            for f in files:
                name = Path(f.get("name", "uploaded.png")).name
                b64_data = f.get("data_b64", "")
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                if not b64_data:
                    continue
                raw = base64.b64decode(b64_data)
                out_path = dest_dir / name
                out_path.write_bytes(raw)
                last_saved_path = out_path.resolve()
                saved_count += 1

            if saved_count == 0:
                return False, "No valid images uploaded."

            self._load_images_from_folder(dest_dir)
            target_idx = 0
            if last_saved_path is not None and not folder_name:
                for i, entry in enumerate(self.image_entries):
                    if entry.file_path == last_saved_path:
                        target_idx = i
                        break
            self._select_image_by_index(target_idx, save_previous=False)
            msg = (
                f"Loaded {saved_count} image(s) from folder '{dest_dir.name}'"
                if folder_name
                else f"Uploaded {saved_count} image(s) to {dest_dir.name}"
            )
            self.last_message = msg
            return True, msg

    # -------------------------------------------------------------------------
    # Layerify Annotation Operations
    # -------------------------------------------------------------------------
    def _current_history(self) -> ImageUndoHistory:
        if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
            return self.image_histories["__runtime__"]
        return self.image_histories[str(self.image_entries[self.curr_image_idx].file_path)]

    def update_annotations(
        self,
        annotations_payload: list[dict[str, Any]],
        push_undo: bool = True,
        message: str | None = None,
    ):
        with self.lock:
            default_fp = (
                self.image_entries[self.curr_image_idx].file_path
                if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                else Path("Runtime")
            )
            new_anns = [
                self.deserialize_annotation(item, idx, default_fp)
                for idx, item in enumerate(annotations_payload)
            ]
            self.normalize_annotation_colors(new_anns)
            if push_undo and not ImageUndoHistory.annotations_equal(
                self.current_annotations, new_anns
            ):
                self._current_history().push(self.current_annotations)
            self.current_annotations = new_anns
            self.save_current_image_annotations()
            if message:
                self.last_message = message

    def undo_annotation(self) -> tuple[bool, str]:
        with self.lock:
            hist = self._current_history()
            if not hist.undo_stack:
                self.last_message = "Nothing to undo."
                return False, self.last_message
            hist.redo_stack.append([ann.copy() for ann in self.current_annotations])
            snapshot = hist.undo_stack.pop()
            self.current_annotations = [ann.copy() for ann in snapshot]
            for idx, ann in enumerate(self.current_annotations):
                ann.annotation_id = idx
                ann.selected = False
            self.save_current_image_annotations()
            self.last_message = "Undo applied."
            return True, self.last_message

    def redo_annotation(self) -> tuple[bool, str]:
        with self.lock:
            hist = self._current_history()
            if not hist.redo_stack:
                self.last_message = "Nothing to redo."
                return False, self.last_message
            hist.undo_stack.append([ann.copy() for ann in self.current_annotations])
            snapshot = hist.redo_stack.pop()
            self.current_annotations = [ann.copy() for ann in snapshot]
            for idx, ann in enumerate(self.current_annotations):
                ann.annotation_id = idx
                ann.selected = False
            self.save_current_image_annotations()
            self.last_message = "Redo applied."
            return True, self.last_message

    def copy_annotations(self, annotation_ids: list[int] | None = None) -> tuple[bool, str]:
        with self.lock:
            if annotation_ids:
                target_ids = {int(i) for i in annotation_ids}
                for ann in self.current_annotations:
                    ann.selected = ann.annotation_id in target_ids
            selected = [ann for ann in self.current_annotations if ann.selected]
            if not selected:
                self.last_message = "No annotation selected to copy."
                return False, self.last_message
            copied = [ann.copy() for ann in selected]
            for ann in copied:
                ann.selected = False
            self.annotation_clipboard = copied
            self.last_message = f"Copied {len(copied)} annotation(s)"
            return True, self.last_message

    def delete_annotations(self, annotation_ids: list[int] | None = None) -> tuple[bool, str]:
        with self.lock:
            if annotation_ids:
                target_ids = {int(i) for i in annotation_ids}
                targets = [ann for ann in self.current_annotations if ann.annotation_id in target_ids]
            else:
                targets = [ann for ann in self.current_annotations if ann.selected]
            if not targets:
                self.last_message = "No annotations selected to delete."
                return False, self.last_message
            self._current_history().push(self.current_annotations)
            target_ids = {ann.annotation_id for ann in targets}
            self.current_annotations = [ann for ann in self.current_annotations if ann.annotation_id not in target_ids]
            for idx, ann in enumerate(self.current_annotations):
                ann.annotation_id = idx
            self.save_current_image_annotations()
            self.last_message = f"Deleted {len(targets)} annotation(s)."
            return True, self.last_message

    def paste_annotations(self) -> tuple[bool, str]:
        with self.lock:
            if not self.annotation_clipboard:
                self.last_message = "No annotation copied to paste."
                return False, self.last_message
            self._current_history().push(self.current_annotations)
            fp = (
                self.image_entries[self.curr_image_idx].file_path
                if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                else Path("Runtime")
            )
            for a in self.current_annotations:
                a.selected = False
            for copied in self.annotation_clipboard:
                new_ann = copied.copy()
                new_ann.annotation_id = len(self.current_annotations)
                new_ann.selected = True
                new_ann.file_path = fp
                new_ann.color = self._label_color(new_ann.label)
                if new_ann.rectangle is not None:
                    new_ann.rectangle = new_ann.rectangle.translated(15.0, 15.0)
                if new_ann.polygon is not None:
                    new_ann.polygon = new_ann.polygon.translated(15.0, 15.0)
                if new_ann.points:
                    new_ann.points = [QPointF(p.x() + 15.0, p.y() + 15.0) for p in new_ann.points]
                if new_ann.mask is not None:
                    new_ann.mask = shift_binary_mask(new_ann.mask, 15, 15)
                self.current_annotations.append(new_ann)
            self.save_current_image_annotations()
            self.last_message = f"Pasted {len(self.annotation_clipboard)} annotation(s)"
            return True, self.last_message

    def clear_all_annotations_and_layers(self) -> tuple[bool, str]:
        with self.lock:
            self._current_history().push(self.current_annotations)
            self.current_annotations.clear()
            if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries):
                cache_path = self._cache_path_for_file(
                    self.image_entries[self.curr_image_idx].file_path
                )
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                    except OSError:
                        pass
            if self.current_canvas is not None:
                if self.current_canvas.layers:
                    self.current_canvas.push_undo_state()
                self.current_canvas.layers.clear()
            self.last_message = "All annotations cleared"
            return True, self.last_message

    def get_all_annotations(self) -> list[Annotation]:
        self.save_current_image_annotations()
        merged: list[Annotation] = []
        seen: set[Path] = set()
        for entry in self.image_entries:
            fp = entry.file_path
            if fp in seen:
                continue
            seen.add(fp)
            cache_path = self._cache_path_for_file(fp)
            if cache_path.exists():
                merged.extend(Annotation.load_from_json(str(cache_path)))
        return merged

    def export_annotations_json(
        self,
        all_layers: bool,
        file_path: str | None = None,
        fmt: str = "default",
    ) -> dict[str, Any]:
        with self.lock:
            anns = self.get_all_annotations() if all_layers else self.current_annotations
            if not anns:
                return {"ok": False, "message": "No annotations to save!"}
            fmt_norm = (fmt or "default").strip().lower()
            if fmt_norm not in ("default", "coco", "yolo"):
                return {"ok": False, "message": f"Unsupported format: {fmt}"}

            curr_entry = (
                self.image_entries[self.curr_image_idx]
                if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                else None
            )
            img_name = curr_entry.name if curr_entry else "image.png"
            img_w = curr_entry.width if curr_entry else 640
            img_h = curr_entry.height if curr_entry else 640
            class_names = [lbl.name for lbl in self.layer_config.predefined_labels]

            ext = ".txt" if fmt_norm == "yolo" else ".json"
            default_stem = "all_annotations" if all_layers else (Path(img_name).stem or "layer_annotations")
            if fmt_norm == "coco":
                default_stem = f"{default_stem}_coco"

            target_path = (
                Path(file_path).expanduser().resolve()
                if file_path
                else (self.layer_config.cache_dir / f"{default_stem}{ext}")
            )
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if fmt_norm == "default":
                Annotation.save_as_json(anns, str(target_path))
                content = target_path.read_text(encoding="utf-8")
                classes_txt = None
            else:
                exported = export_annotations_data(
                    annotations=anns,
                    fmt=fmt_norm,
                    image_name=img_name,
                    image_width=img_w,
                    image_height=img_h,
                    class_names=class_names,
                )
                save_annotations_to_path(
                    annotations=anns,
                    output_path=target_path,
                    fmt=fmt_norm,
                    image_name=img_name,
                    image_width=img_w,
                    image_height=img_h,
                    class_names=class_names,
                )
                content = exported["content"]
                classes_txt = exported["data"].get("classes_txt") if fmt_norm == "yolo" else None

            self.last_message = f"Saved annotations ({fmt_norm.upper()}) to {target_path.name}"
            return {
                "ok": True,
                "format": fmt_norm,
                "message": f"Merged annotations saved ({fmt_norm.upper()})!"
                if all_layers
                else f"Annotations saved ({fmt_norm.upper()})!",
                "path": str(target_path),
                "filename": target_path.name,
                "json_content": content,
                "content": content,
                "classes_txt": classes_txt,
            }

    def import_annotations_json(
        self,
        all_layers: bool,
        file_path: str | None = None,
        json_content: str | None = None,
        fmt: str = "auto",
        class_names: list[str] | None = None,
    ) -> tuple[bool, str]:
        with self.lock:
            temp_path: Path | None = None
            try:
                fmt_norm = (fmt or "auto").strip().lower()
                curr_entry = (
                    self.image_entries[self.curr_image_idx]
                    if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                    else None
                )
                img_name = curr_entry.name if curr_entry else None
                img_w = curr_entry.width if curr_entry else 640
                img_h = curr_entry.height if curr_entry else 640
                if not class_names:
                    class_names = [lbl.name for lbl in self.layer_config.predefined_labels]

                if json_content is not None:
                    is_json_default = False
                    if isinstance(json_content, str):
                        stripped = json_content.strip()
                        if fmt_norm in ("auto", "default") and stripped.startswith("["):
                            is_json_default = True
                    if is_json_default:
                        temp_path = self.layer_config.cache_dir / "_uploaded_annotations.json"
                        temp_path.write_text(json_content, encoding="utf-8")
                        loaded = Annotation.load_from_json(str(temp_path))
                    else:
                        dicts = load_annotation_dicts_from_data(
                            content=json_content,
                            fmt=fmt_norm,
                            image_name=None if all_layers else img_name,
                            image_width=img_w,
                            image_height=img_h,
                            class_names=class_names,
                        )
                        default_fp = curr_entry.file_path if curr_entry else Path("Runtime")
                        loaded = [dict_to_annotation(d, file_path=default_fp) for d in dicts]
                else:
                    if file_path:
                        load_path = Path(file_path).expanduser().resolve()
                    else:
                        load_path = self.layer_config.cache_dir / "all_annotations.json"

                    if not load_path.exists():
                        return False, f"Annotation file not found: {load_path}"

                    if fmt_norm in ("auto", "default") and load_path.suffix.lower() == ".json":
                        loaded = Annotation.load_from_json(str(load_path))
                    else:
                        loaded = load_annotations_from_path(
                            load_path,
                            fmt=fmt_norm,
                            image_name=None if all_layers else img_name,
                            image_width=img_w,
                            image_height=img_h,
                            class_names=class_names,
                        )
                if all_layers:
                    by_file = defaultdict(list)
                    by_name = defaultdict(list)
                    for ann in loaded:
                        by_file[Path(ann.file_path).resolve()].append(ann)
                        by_name[Path(ann.file_path).name].append(ann)

                    for entry in self.image_entries:
                        fp = entry.file_path.resolve()
                        matched = by_file.get(fp) or by_name.get(fp.name, [])
                        copied = [a.copy() for a in matched]
                        self.normalize_annotation_colors(copied)
                        for idx, a in enumerate(copied):
                            a.annotation_id = idx
                            a.selected = False
                            a.file_path = fp
                        cache_p = self._cache_path_for_file(fp)
                        if copied:
                            Annotation.save_as_json(copied, str(cache_p))
                        elif cache_p.exists():
                            cache_p.unlink()

                    if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries):
                        self.current_annotations = self.load_image_annotations(
                            self.image_entries[self.curr_image_idx].file_path
                        )
                    self.last_message = "Merged annotations loaded successfully!"
                    return True, self.last_message
                else:
                    self._current_history().push(self.current_annotations)
                    fp = (
                        self.image_entries[self.curr_image_idx].file_path
                        if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                        else Path("Runtime")
                    )
                    for idx, a in enumerate(loaded):
                        a.annotation_id = idx
                        a.file_path = fp
                        self.ensure_label_available(a.label, a.color)
                    self.normalize_annotation_colors(loaded, add_missing_labels=False)
                    self.current_annotations = loaded
                    self.save_current_image_annotations()
                    self.last_message = "Annotations loaded successfully!"
                    return True, self.last_message
            except Exception as err:
                logger.exception(err)
                return False, f"Failed to load annotations: {err}"
            finally:
                if temp_path and temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

    # -------------------------------------------------------------------------
    # Label Management
    # -------------------------------------------------------------------------
    def manage_labels(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            action = payload.get("action")
            if action == "select":
                label_name = (payload.get("label") or "").strip() or "Undefined"
                self.ensure_label_available(label_name)
                self.current_label = label_name
                color = self._label_color(label_name)
                needs_change = any(
                    ann.selected and ann.label != label_name
                    for ann in self.current_annotations
                )
                if needs_change:
                    self._current_history().push(self.current_annotations)
                updated_selected = False
                for ann in self.current_annotations:
                    if ann.selected:
                        ann.label = label_name
                        ann.color = color
                        updated_selected = True
                if updated_selected:
                    self.save_current_image_annotations()
                self.last_message = f"Label changed to {label_name}"
                return True, self.last_message

            elif action in {"add", "create"}:
                name = (payload.get("name") or payload.get("label") or "").strip()
                color_hex = payload.get("color") or "#ffffff"
                if not name:
                    return False, "Label name cannot be empty."
                existing = [lbl.name for lbl in self.layer_config.predefined_labels]
                if name in existing:
                    return False, "Label name already exists!"
                qcol = hex_to_qcolor(color_hex)
                self.ensure_label_available(name, qcol)
                self.layer_config.save_labels_to_cache()
                self.current_label = name
                self.last_message = f"Added label: {name}"
                return True, self.last_message

            elif action == "color":
                label_name = (payload.get("label") or self.current_label or "Undefined").strip()
                color_hex = payload.get("color") or "#ffffff"
                qcol = hex_to_qcolor(color_hex)
                for lbl in self.layer_config.predefined_labels:
                    if lbl.name == label_name:
                        lbl.color = qcol
                        break
                self.layer_config.save_labels_to_cache()
                self._propagate_label_color(label_name, qcol)
                self.last_message = f"Updated color for label {label_name}"
                return True, self.last_message

            elif action in {"rename", "update"}:
                old_name = (
                    payload.get("old_name")
                    or payload.get("old_label")
                    or payload.get("label")
                    or ""
                ).strip()
                new_name = (
                    payload.get("new_name")
                    or payload.get("new_label")
                    or old_name
                ).strip()
                color_val = payload.get("color")
                if not old_name or not new_name:
                    return False, "Invalid label update."
                if old_name == "Undefined" and new_name != "Undefined":
                    return False, "The 'Undefined' label cannot be renamed."
                existing = [
                    lbl.name
                    for lbl in self.layer_config.predefined_labels
                    if lbl.name != old_name
                ]
                if new_name != old_name and new_name in existing:
                    return False, "Label name already exists!"
                found_lbl = None
                for lbl in self.layer_config.predefined_labels:
                    if lbl.name == old_name:
                        lbl.name = new_name
                        if color_val is not None:
                            lbl.color = hex_to_qcolor(color_val)
                        found_lbl = lbl
                        break
                if found_lbl is None:
                    return False, f"Label '{old_name}' not found."
                self.layer_config.save_labels_to_cache()
                if old_name != new_name:
                    self._propagate_label_rename(old_name, new_name)
                    if self.current_label == old_name:
                        self.current_label = new_name
                if color_val is not None:
                    self._propagate_label_color(new_name, found_lbl.color)
                self.last_message = (
                    f"Renamed label {old_name} to {new_name}"
                    if old_name != new_name
                    else f"Updated label {new_name}"
                )
                return True, self.last_message

            elif action == "delete":
                raw_labels = payload.get("labels")
                if not raw_labels and payload.get("label"):
                    raw_labels = [payload.get("label")]
                names = [n for n in (raw_labels or []) if n]
                if not names:
                    return False, "Select one or more labels to delete."
                default_lbl = self.get_default_label()
                if default_lbl.name in names or "Undefined" in names:
                    return False, "The 'Undefined' label cannot be removed."
                self.layer_config.predefined_labels = [
                    lbl for lbl in self.layer_config.predefined_labels if lbl.name not in set(names)
                ]
                self.layer_config.save_labels_to_cache()
                for name in names:
                    self._propagate_label_delete(name, default_lbl)
                if self.current_label in set(names):
                    self.current_label = default_lbl.name
                self.last_message = f"Deleted {len(names)} label(s)"
                return True, self.last_message

            elif action == "cleanup_defaults":
                placeholders = {"Label 1", "Label 2", "Label 3", "Custom", "Unlabeled"}
                targets = [
                    lbl.name
                    for lbl in self.layer_config.predefined_labels
                    if lbl.name in placeholders
                ]
                if not targets:
                    self.last_message = "No default placeholder labels remain."
                    return True, self.last_message
                return self.manage_labels({"action": "delete", "labels": targets})

            return False, f"Unknown label action: {action}"

    def _propagate_label_rename(self, old_label: str, new_label: str):
        for ann in self.current_annotations:
            if ann.label == old_label:
                ann.label = new_label
        self.save_current_image_annotations()

        for entry in self.image_entries:
            cp = self._cache_path_for_file(entry.file_path)
            if cp.exists():
                anns = Annotation.load_from_json(str(cp))
                changed = False
                for a in anns:
                    if a.label == old_label:
                        a.label = new_label
                        changed = True
                if changed:
                    Annotation.save_as_json(anns, str(cp))

    def _propagate_label_color(self, label_name: str, color: QColor):
        for ann in self.current_annotations:
            if ann.label == label_name:
                ann.color = QColor(color.red(), color.green(), color.blue())
        self.save_current_image_annotations()

        for entry in self.image_entries:
            cp = self._cache_path_for_file(entry.file_path)
            if cp.exists():
                anns = Annotation.load_from_json(str(cp))
                changed = False
                for a in anns:
                    if a.label == label_name:
                        a.color = QColor(color.red(), color.green(), color.blue())
                        changed = True
                if changed:
                    Annotation.save_as_json(anns, str(cp))

    def _propagate_label_delete(self, deleted_label: str, replacement: Label):
        for ann in self.current_annotations:
            if ann.label == deleted_label:
                ann.label = replacement.name
                ann.color = QColor(replacement.color)
        self.save_current_image_annotations()

        for entry in self.image_entries:
            cp = self._cache_path_for_file(entry.file_path)
            if cp.exists():
                anns = Annotation.load_from_json(str(cp))
                changed = False
                for a in anns:
                    if a.label == deleted_label:
                        a.label = replacement.name
                        a.color = QColor(replacement.color)
                        changed = True
                if changed:
                    Annotation.save_as_json(anns, str(cp))
