import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QProgressDialog,
)

from imagebaker import logger
from imagebaker.core.defs import Annotation
from imagebaker.layers.annotable_layer import AnnotableLayer


@dataclass
class ImageEntry:
    is_baked_result: bool
    data: AnnotableLayer | Path


class LayerifyAnnotationsIoMixin:
    """File, folder, cache, and annotation import/export helpers for LayerifyTab."""

    def _entry_file_path(self, image_entry: ImageEntry) -> Path:
        if image_entry.is_baked_result and isinstance(image_entry.data, AnnotableLayer):
            return Path(image_entry.data.file_path)
        return Path(image_entry.data)

    def _find_image_entry_index(self, image_entry: ImageEntry) -> int:
        """
        Resolve an image entry index robustly.

        Qt list item payloads can occasionally come back as equal-value objects
        that do not share identity with the original list object.
        """
        for idx, entry in enumerate(self.image_entries):
            if entry is image_entry:
                return idx

        for idx, entry in enumerate(self.image_entries):
            if entry == image_entry:
                return idx

        target_path = str(self._entry_file_path(image_entry))
        target_kind = bool(getattr(image_entry, "is_baked_result", False))
        for idx, entry in enumerate(self.image_entries):
            if bool(entry.is_baked_result) != target_kind:
                continue
            if str(self._entry_file_path(entry)) == target_path:
                return idx

        return -1

    def _load_image_into_layer_with_progress(
        self, layer: AnnotableLayer, file_path: Path
    ):
        progress = QProgressDialog(
            f"Loading {Path(file_path).name}...", None, 0, 0, self
        )
        progress.setWindowTitle("Loading Image")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            layer.file_path = file_path
            layer.set_image(file_path)
            layer.file_path = file_path
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

    def on_image_selected(self, image_entry: ImageEntry):
        """Handle image selection from the image list panel."""
        logger.info(f"Image selected: {image_entry}")

        # Persist current layer before remapping the visible slot.
        if (
            self.layer is not None
            and self.layer.file_path
            and Path(self.layer.file_path) != Path("Runtime")
        ):
            self.save_layer_annotations(self.layer, delete_if_empty=False)

        # Hide all layers first
        for _idx, layer in enumerate(self.annotable_layers):
            layer.setVisible(False)
            # logger.info(f"Layer {idx} hidden.")
        current_label = self.layer.current_label or self.current_label or "Undefined"
        current_color = self.layer.current_color or self._label_color(current_label)

        # Render selected entry into a deterministic visible slot to avoid
        # page-index/modulo remapping bugs.
        selected_layer = self.annotable_layers[0]
        self.curr_image_idx = self._find_image_entry_index(image_entry)
        if self.curr_image_idx < 0:
            # Still continue using the selected entry path so switching works.
            logger.warning("Selected image entry index not found, using direct entry path.")
            self.curr_image_idx = 0
        selected_layer.setVisible(True)

        selected_path = self._entry_file_path(image_entry)
        self._load_image_into_layer_with_progress(selected_layer, selected_path)

        self.load_layer_annotations(selected_layer)
        if self.layer:
            selected_layer.set_mode(self.layer.mouse_mode)
        self.layer = selected_layer  # Update the currently selected layer

        # Set the current label and color
        self.layer.current_label = current_label
        self.layer.current_color = current_color
        self.sync_labels_from_annotations(self.layer.annotations)
        self.annotation_list.layer = self.layer
        self.annotation_list.update_list()
        self.update_label_combo()
        self.sync_mode_buttons()
        self.sync_label_combo_to_selection()

        self.messageSignal.emit(
            f"Showing image {self.curr_image_idx + 1}/{len(self.image_entries)}"
        )
        self.update()

    def load_default_images(self):
        """Load the first set of images as the default."""
        # If no images are loaded, try to load from the assets folder
        if not self.image_entries:
            assets_folder = self.config.assets_folder
            if assets_folder.exists() and assets_folder.is_dir():
                self._load_images_from_folder(assets_folder)

        # Load images into layers if any are found
        if self.image_entries:
            for i, layer in enumerate(self.annotable_layers):
                if i == 0:
                    entry_path = self._entry_file_path(self.image_entries[0])
                    self._load_image_into_layer_with_progress(layer, entry_path)
                    self.load_layer_annotations(layer)
                    self.sync_labels_from_annotations(layer.annotations)
                    layer.layer_name = "Layer_1"
                    layer.setVisible(True)
                    self.layer = layer
                    if self.image_list_panel.list_widget.count() > 0:
                        self.image_list_panel.list_widget.setCurrentRow(0)
                else:
                    layer.setVisible(False)
                    layer.file_path = Path("Runtime")

            self.messageSignal.emit(f"Showing image 1/{len(self.image_entries)}")
        else:
            # If no images are found, log a message
            logger.warning("No images found in the assets folder.")
            self.messageSignal.emit("No images found in the assets folder.")

        # Update the image list panel
        self.image_list_panel.update_image_list(self.image_entries)
        self.update()

    def remove_image_entry(self, entry):
        """Remove an image entry from the Layerify list without deleting the file."""
        if entry is None:
            return
        try:
            idx = self.image_entries.index(entry)
        except ValueError:
            return

        was_current = (
            self.layer is not None
            and self.layer.file_path is not None
            and hasattr(entry, "data")
            and Path(self.layer.file_path) == Path(entry.data)
        )
        if was_current and self.layer is not None:
            self.save_layer_annotations(self.layer)

        self.image_entries.pop(idx)
        entry_name = (
            Path(entry.data).name
            if hasattr(entry, "data") and isinstance(entry.data, (str, Path))
            else "image"
        )
        total_pages = max(
            1,
            (len(self.image_entries) + self.image_list_panel.images_per_page - 1)
            // self.image_list_panel.images_per_page,
        )
        if self.image_list_panel.current_page >= total_pages:
            self.image_list_panel.current_page = total_pages - 1

        self.image_list_panel.image_entries = self.image_entries
        self.image_list_panel.update_image_list(self.image_entries)

        if not self.image_entries:
            if self.layer is not None:
                self.layer.setVisible(False)
                self.layer.annotations = []
                self.layer.update()
            self.annotation_list.update_list()
        elif was_current:
            next_idx = min(idx, len(self.image_entries) - 1)
            self.on_image_selected(self.image_entries[next_idx])

        self.messageSignal.emit(f"Removed image from list: {entry_name}")
        logger.info(f"Removed image from list: {entry_name}")

    def save_layer_annotations(
        self,
        layer: AnnotableLayer,
        save_dir: Path | None = None,
        delete_if_empty: bool = True,
    ):
        """Save annotations for a specific layer"""
        file_path = layer.file_path
        if not file_path or Path(file_path) == Path("Runtime"):
            return
        if save_dir is None:
            # Save to the cache directory
            save_dir = self.config.cache_dir
        save_dir = self._cache_path_for_file(file_path, save_dir)

        # Keep annotation metadata aligned to the owning image without clearing live selection.
        to_save = []
        for index, annotation in enumerate(layer.annotations):
            annotation.annotation_id = index
            annotation.file_path = Path(file_path)
            saved_copy = annotation.copy()
            saved_copy.selected = False
            to_save.append(saved_copy)

        # if there are annotations
        if len(to_save) > 0:
            Annotation.save_as_json(to_save, save_dir)
            logger.info(f"Saved annotations for {layer.layer_name} to {save_dir}")
        elif delete_if_empty and save_dir.exists():
            # Remove the existing annotation file if no annotations
            os.remove(save_dir)
            logger.info(f"Removed empty annotation file: {save_dir}")

    def _cache_path_for_file(self, file_path: Path, base_dir: Path | None = None) -> Path:
        """Create a stable cache path for an image path using full-path identity."""
        if base_dir is None:
            base_dir = self.config.cache_dir
        normalized = str(Path(file_path))
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        safe_name = Path(file_path).name
        return base_dir / f"{safe_name}.{digest}.json"

    def cleanup_stale_annotation_cache(self) -> tuple[int, int]:
        """
        Remove stale/orphan cache files and migrate legacy cache names.

        Returns:
            tuple[int, int]: (removed_count, migrated_count)
        """
        cache_dir = self.config.cache_dir
        if not cache_dir.exists():
            return 0, 0

        runtime_path = Path("Runtime")
        expected_cache_paths: set[Path] = set()

        for image_entry in self.image_entries:
            try:
                expected_cache_paths.add(
                    self._cache_path_for_file(self._entry_file_path(image_entry)).resolve()
                )
            except Exception:
                continue

        for layer in self.annotable_layers:
            layer_path = Path(getattr(layer, "file_path", runtime_path))
            if layer_path == runtime_path:
                continue
            expected_cache_paths.add(self._cache_path_for_file(layer_path).resolve())

        removed = 0
        migrated = 0

        for cache_file in cache_dir.glob("*.json"):
            cache_file = cache_file.resolve()
            if cache_file.name in {"all_annotations.json", "labels.json"}:
                continue
            if cache_file in expected_cache_paths:
                continue

            try:
                annotations = Annotation.load_from_json(cache_file)
            except Exception:
                # Corrupted or invalid JSON cache file.
                try:
                    cache_file.unlink()
                    removed += 1
                except Exception:
                    pass
                continue

            if not annotations:
                try:
                    cache_file.unlink()
                    removed += 1
                except Exception:
                    pass
                continue

            ann_paths = []
            for annotation in annotations:
                ann_path = Path(getattr(annotation, "file_path", runtime_path))
                if ann_path != runtime_path:
                    ann_paths.append(ann_path)

            if not ann_paths:
                try:
                    cache_file.unlink()
                    removed += 1
                except Exception:
                    pass
                continue

            existing_paths = [path for path in ann_paths if path.exists()]
            if not existing_paths:
                try:
                    cache_file.unlink()
                    removed += 1
                except Exception:
                    pass
                continue

            # Migrate legacy per-image cache filenames to current hashed format.
            unique_paths = set(existing_paths)
            if len(unique_paths) == 1:
                source_path = next(iter(unique_paths))
                target_cache = self._cache_path_for_file(source_path).resolve()
                if target_cache != cache_file:
                    for idx, annotation in enumerate(annotations):
                        annotation.annotation_id = idx
                        annotation.selected = False
                        annotation.file_path = source_path
                    if not target_cache.exists():
                        Annotation.save_as_json(annotations, target_cache)
                    try:
                        cache_file.unlink()
                        removed += 1
                        migrated += 1
                    except Exception:
                        pass

        if removed > 0:
            logger.info(
                f"Cache cleanup complete. Removed {removed} stale cache file(s), migrated {migrated}."
            )
        return removed, migrated

    def get_all_annotations(self) -> list[Annotation]:
        for layer in self.annotable_layers:
            self.save_layer_annotations(layer)

        merged_annotations = []
        seen_files = set()

        for image_entry in self.image_entries:
            file_path = self._entry_file_path(image_entry)

            if file_path in seen_files:
                continue
            seen_files.add(file_path)

            cache_path = self._cache_path_for_file(file_path)
            if cache_path.exists():
                merged_annotations.extend(Annotation.load_from_json(cache_path))

        return merged_annotations

    def load_merged_annotations(self, annotations: list[Annotation]):
        annotations_by_file = defaultdict(list)
        for annotation in annotations:
            annotations_by_file[Path(annotation.file_path)].append(annotation)

        # Persist merged annotations to cache for every image entry, not only visible layers.
        for image_entry in self.image_entries:
            file_path = self._entry_file_path(image_entry)
            cache_path = self._cache_path_for_file(file_path)
            file_annotations = [ann.copy() for ann in annotations_by_file.get(file_path, [])]
            self.normalize_annotation_colors(file_annotations)
            for index, annotation in enumerate(file_annotations):
                annotation.annotation_id = index
                annotation.selected = False
                annotation.file_path = file_path

            if file_annotations:
                Annotation.save_as_json(file_annotations, cache_path)
            elif cache_path.exists():
                os.remove(cache_path)

        # Refresh currently active canvas layers from cache.
        for layer in self.annotable_layers:
            self.load_layer_annotations(layer)
            layer.selected_annotation = None
            layer.current_annotation = None
            layer.update()

    def load_layer_annotations(
        self, layer: AnnotableLayer, load_dir: Path | None = None
    ):
        """Load annotations for a specific layer"""
        if layer.file_path:
            file_path = layer.file_path
            if load_dir is None:
                load_dir = self.config.cache_dir
            load_dir = self._cache_path_for_file(file_path, load_dir)
            if load_dir.exists():
                layer.annotations = Annotation.load_from_json(load_dir)
                self.sync_labels_from_annotations(layer.annotations)
                if self.normalize_annotation_colors(layer.annotations):
                    Annotation.save_as_json(layer.annotations, load_dir)
                logger.info(
                    f"Loaded annotations for {layer.layer_name} from {load_dir}"
                )
            else:
                layer.annotations = []
                layer.selected_annotation = None
                layer.current_annotation = None
                logger.warning(f"No annotations found for {layer.layer_name}")

    def update_active_entries(self, image_entries: list[ImageEntry]):
        """Update the active entries in the image list panel."""
        # Persist all currently mapped layers before remapping page slots.
        for layer in self.annotable_layers:
            if layer.file_path:
                self.save_layer_annotations(layer, delete_if_empty=False)
        self.curr_image_idx = 0
        page_start = self.image_list_panel.current_page * self.image_list_panel.images_per_page
        for i, layer in enumerate(self.annotable_layers):
            layer.annotations = []

            if i == 0 and len(image_entries) > 0:
                idx = page_start
                if idx >= len(self.image_entries):
                    layer.setVisible(False)
                    continue
                entry = self.image_entries[idx]
                entry_path = self._entry_file_path(entry)
                self._load_image_into_layer_with_progress(layer, entry_path)
                self.load_layer_annotations(layer)

                layer.layer_name = f"Layer_{idx + 1}"
                layer.setVisible(True)
                self.layer = layer
                self.annotation_list.layer = self.layer
                self.annotation_list.update_list()
            else:
                layer.setVisible(False)
                layer.file_path = Path("Runtime")
        logger.info("Updated active entries in image list panel.")

    def load_default_image(self):
        """
        Load a default image from the assets folder.
        """
        default_path = self.config.assets_folder / "desk.png"
        if not default_path.exists():
            default_path, _ = QFileDialog.getOpenFileName()
            default_path = Path(default_path)

        if default_path.exists():
            self.layer.set_image(default_path)

    def _select_annotation_format(
        self, title: str = "Select Annotation Format", allow_auto: bool = False
    ) -> str | None:
        items = (
            ["auto (Detect)", "default (ImageBaker JSON)", "coco (COCO JSON)", "yolo (YOLO TXT/ZIP)"]
            if allow_auto
            else ["default (ImageBaker JSON)", "coco (COCO JSON)", "yolo (YOLO TXT/ZIP)"]
        )
        choice, ok = QInputDialog.getItem(
            self, title, "Format:", items, 0, False
        )
        if not ok or not choice:
            return None
        return choice.split()[0].strip().lower()

    def save_annotations(self, fmt: str | None = None):
        """Save annotations to Default (ImageBaker JSON), COCO, or YOLO format."""
        from imagebaker.utils.annotation_formats import save_annotations_to_path

        if not self.layer.annotations and not any(
            layer.annotations for layer in self.annotable_layers
        ):
            QMessageBox.warning(self, "Warning", "No annotations to save!")
            return

        selected_fmt = fmt or self._select_annotation_format("Export Annotation Format")
        if not selected_fmt:
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Save Annotations")
        msg_box.setText("Do you want to save annotations from all layers?")
        yes_button = msg_box.addButton("All Layers", QMessageBox.YesRole)
        msg_box.addButton("Just This Layer", QMessageBox.NoRole)
        msg_box.setDefaultButton(yes_button)
        msg_box.exec()
        save_all = msg_box.clickedButton() == yes_button

        file_filter = (
            "YOLO Files (*.txt *.zip);;All Files (*)"
            if selected_fmt == "yolo"
            else "JSON Files (*.json);;All Files (*)"
        )
        default_ext = ".txt" if selected_fmt == "yolo" else ".json"
        class_names = [lbl.name for lbl in self.config.predefined_labels]
        img_w = self.layer.image.width() if self.layer and not self.layer.image.isNull() else None
        img_h = self.layer.image.height() if self.layer and not self.layer.image.isNull() else None
        img_name = self.layer.file_path.name if self.layer and self.layer.file_path else "image.png"

        if save_all:
            options = QFileDialog.Options()
            default_name = f"all_annotations_{selected_fmt}{default_ext}"
            file_name, _ = QFileDialog.getSaveFileName(
                self,
                f"Save Merged Annotations ({selected_fmt.upper()})",
                str(self.config.cache_dir / default_name),
                file_filter,
                options=options,
            )
            if not file_name:
                QMessageBox.warning(self, "Warning", "No file selected!")
                return
            merged_annotations = self.get_all_annotations()
            if selected_fmt == "default":
                Annotation.save_as_json(merged_annotations, file_name)
            else:
                save_annotations_to_path(
                    merged_annotations,
                    file_name,
                    fmt=selected_fmt,
                    image_name=img_name,
                    image_width=img_w,
                    image_height=img_h,
                    class_names=class_names,
                )
            QMessageBox.information(
                self, "Success", f"Merged annotations saved ({selected_fmt.upper()})!"
            )
            return

        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            f"Save Annotations ({selected_fmt.upper()})",
            str(Path(img_name).stem + default_ext),
            file_filter,
            options=options,
        )

        if file_name:
            try:
                if selected_fmt == "default":
                    Annotation.save_as_json(self.layer.annotations, file_name)
                else:
                    save_annotations_to_path(
                        self.layer.annotations,
                        file_name,
                        fmt=selected_fmt,
                        image_name=img_name,
                        image_width=img_w,
                        image_height=img_h,
                        class_names=class_names,
                    )

                QMessageBox.information(
                    self, "Success", f"Annotations saved ({selected_fmt.upper()})!"
                )

            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to save annotations: {str(e)}"
                )

    def load_annotations(self, fmt: str | None = None):
        """
        Load annotations from Default (ImageBaker JSON), COCO JSON, or YOLO (.txt/.zip).
        """
        from imagebaker.utils.annotation_formats import load_annotations_from_path

        selected_fmt = fmt or self._select_annotation_format(
            "Load Annotation Format", allow_auto=True
        )
        if not selected_fmt:
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Load Annotations")
        msg_box.setText("Do you want to load annotations from all layers?")
        yes_button = msg_box.addButton("All Layers", QMessageBox.YesRole)
        msg_box.addButton("Just This Layer", QMessageBox.NoRole)
        msg_box.setDefaultButton(yes_button)
        msg_box.exec()
        load_all = msg_box.clickedButton() == yes_button

        file_filter = "Annotation Files (*.json *.txt *.zip);;JSON Files (*.json);;YOLO Files (*.txt *.zip);;All Files (*)"
        class_names = [lbl.name for lbl in self.config.predefined_labels]
        img_w = self.layer.image.width() if self.layer and not self.layer.image.isNull() else None
        img_h = self.layer.image.height() if self.layer and not self.layer.image.isNull() else None
        img_name = self.layer.file_path.name if self.layer and self.layer.file_path else None

        if load_all:
            options = QFileDialog.Options()
            file_name, _ = QFileDialog.getOpenFileName(
                self,
                "Load Merged Annotations",
                str(self.config.cache_dir),
                file_filter,
                options=options,
            )
            if not file_name:
                QMessageBox.warning(self, "Warning", "No file selected!")
                return
            if selected_fmt == "default" and file_name.lower().endswith(".json"):
                annotations = Annotation.load_from_json(file_name)
            else:
                annotations = load_annotations_from_path(
                    file_name,
                    fmt=selected_fmt,
                    image_name=None,
                    image_width=img_w,
                    image_height=img_h,
                    class_names=class_names,
                )
            self.load_merged_annotations(annotations)
            self.update_annotation_list()
            QMessageBox.information(
                self, "Success", "Merged annotations loaded successfully!"
            )
            return

        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Load Annotations", "", file_filter, options=options
        )

        if file_name:
            try:
                if selected_fmt == "default" and file_name.lower().endswith(".json"):
                    self.layer.annotations = Annotation.load_from_json(file_name)
                else:
                    self.layer.annotations = load_annotations_from_path(
                        file_name,
                        fmt=selected_fmt,
                        image_name=img_name,
                        image_width=img_w,
                        image_height=img_h,
                        class_names=class_names,
                    )
                self.sync_labels_from_annotations(self.layer.annotations)
                self.normalize_annotation_colors(self.layer.annotations, add_missing_labels=False)
                self.save_layer_annotations(self.layer)
                self.layer.update()
                self.update_annotation_list()
                QMessageBox.information(
                    self, "Success", "Annotations loaded successfully!"
                )

            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to load annotations: {str(e)}"
                )
                self.layer.annotations = []
                self.layer.update()

    def _load_images_from_folder(self, folder_path: Path):
        """Load images from a folder and update the image list."""
        self.image_entries = []  # Clear the existing image paths

        if self.config.full_search:
            image_paths = list(folder_path.rglob("*.*"))
        else:
            image_paths = list(folder_path.glob("*.*"))

        for img_path in image_paths:
            if img_path.suffix.lower() in [
                ".jpg",
                ".jpeg",
                ".png",
                ".bmp",
                ".tiff",
            ]:
                self.image_entries.append(
                    ImageEntry(is_baked_result=False, data=img_path)
                )

        # load from bake folder if it exists
        bake_folder = self.config.bake_dir
        if bake_folder.exists() and bake_folder.is_dir():
            for img_path in bake_folder.glob("*.*"):
                if img_path.suffix.lower() in [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".bmp",
                    ".tiff",
                ]:
                    self.image_entries.append(
                        ImageEntry(is_baked_result=False, data=img_path)
                    )

    def select_folder(self):
        """Allow the user to select a folder and load images from it."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            folder_path = Path(folder_path)

            self._load_images_from_folder(folder_path)

            self.curr_image_idx = 0  # Reset the current image index

            if len(self.image_entries) > 0:
                msg = f"Loaded {len(self.image_entries)} images from {folder_path}"
                logger.info(msg)
                self.messageSignal.emit(msg)

                # Update the image list panel with the new image paths
                self.image_list_panel.image_entries = self.image_entries
                self.image_list_panel.update_image_list(self.image_entries)

                # Load the first set of images into the layers
                self.load_default_images()

            else:
                QMessageBox.warning(
                    self,
                    "No Images Found",
                    "No valid image files found in the selected folder.",
                )
