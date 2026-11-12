from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from imagebaker import logger
from imagebaker.core.defs import Annotation, Label


class LayerifyLabelsMixin:
    """Label management, color synchronization, and label manager modal for LayerifyTab."""

    def ensure_label_available(
        self, label_name: str, color: QColor | None = None
    ) -> bool:
        if not label_name:
            return False

        existing_names = [label.name for label in self.config.predefined_labels]
        if label_name in existing_names:
            return False

        self.config.predefined_labels.append(
            Label(name=label_name, color=color or QColor(255, 255, 255))
        )
        self.config.save_labels_to_cache()
        return True

    def sync_labels_from_annotations(self, annotations: list[Annotation]):
        added_any = False
        for annotation in annotations:
            added_any = (
                self.ensure_label_available(annotation.label, annotation.color)
                or added_any
            )

        if added_any:
            self.update_label_combo()

    @staticmethod
    def _rgb(color: QColor) -> tuple[int, int, int]:
        return color.red(), color.green(), color.blue()

    def _label_color(self, label_name: str) -> QColor:
        color = self.config.get_label_color(label_name)
        return QColor(color.red(), color.green(), color.blue())

    def normalize_annotation_colors(
        self, annotations: list[Annotation], add_missing_labels: bool = True
    ) -> bool:
        """Normalize annotation colors to always match their label color."""
        changed = False
        added_any = False

        for annotation in annotations:
            if not annotation.label:
                annotation.label = self.get_default_label().name
                changed = True

            if add_missing_labels:
                added_any = (
                    self.ensure_label_available(annotation.label, annotation.color)
                    or added_any
                )

            target_color = self._label_color(annotation.label)
            if self._rgb(annotation.color) != self._rgb(target_color):
                annotation.color = target_color
                changed = True

        if added_any:
            self.update_label_combo()

        return changed

    def update_label_combo(self):
        """
        Add predefined labels to the label combo box.

        This method is called when a new label is added.
        """
        with QSignalBlocker(self.label_combo):
            self.label_combo.clear()
            for label in self.config.predefined_labels:
                pixmap = QPixmap(16, 16)
                pixmap.fill(label.color)
                self.label_combo.addItem(QIcon(pixmap), label.name)
        logger.info("Updated label combo box with predefined labels.")
        self.sync_label_combo_to_selection()

    def get_default_label(self) -> Label:
        self.config.ensure_undefined_label()
        return self.config.default_label

    def update_annotations_for_label_rename(self, old_label: str, new_label: str):
        for layer in self.annotable_layers:
            changed = False
            for annotation in layer.annotations:
                if annotation.label == old_label:
                    annotation.label = new_label
                    changed = True
            if changed:
                self.save_layer_annotations(layer)
                layer.update()

        for image_entry in self.image_entries:
            file_path = self._entry_file_path(image_entry)
            cache_path = self._cache_path_for_file(file_path)
            if not cache_path.exists():
                continue

            annotations = Annotation.load_from_json(cache_path)
            changed = False
            for annotation in annotations:
                if annotation.label == old_label:
                    annotation.label = new_label
                    changed = True
            if changed:
                Annotation.save_as_json(annotations, cache_path)

    def update_annotations_for_label_color(self, label_name: str, color: QColor):
        for layer in self.annotable_layers:
            changed = False
            for annotation in layer.annotations:
                if annotation.label == label_name:
                    if self._rgb(annotation.color) != self._rgb(color):
                        annotation.color = QColor(color.red(), color.green(), color.blue())
                        changed = True
            if changed:
                self.save_layer_annotations(layer)
                layer.update()

        for image_entry in self.image_entries:
            file_path = self._entry_file_path(image_entry)
            cache_path = self._cache_path_for_file(file_path)
            if not cache_path.exists():
                continue

            annotations = Annotation.load_from_json(cache_path)
            changed = False
            for annotation in annotations:
                if annotation.label == label_name:
                    if self._rgb(annotation.color) != self._rgb(color):
                        annotation.color = QColor(color.red(), color.green(), color.blue())
                        changed = True
            if changed:
                Annotation.save_as_json(annotations, cache_path)

    def replace_deleted_label_in_annotations(
        self, deleted_label: str, replacement_label: Label
    ):
        for layer in self.annotable_layers:
            changed = False
            for annotation in layer.annotations:
                if annotation.label == deleted_label:
                    annotation.label = replacement_label.name
                    annotation.color = replacement_label.color
                    changed = True
            if changed:
                self.save_layer_annotations(layer)
                layer.update()

        for image_entry in self.image_entries:
            file_path = self._entry_file_path(image_entry)
            cache_path = self._cache_path_for_file(file_path)
            if not cache_path.exists():
                continue

            annotations = Annotation.load_from_json(cache_path)
            changed = False
            for annotation in annotations:
                if annotation.label == deleted_label:
                    annotation.label = replacement_label.name
                    annotation.color = replacement_label.color
                    changed = True
            if changed:
                Annotation.save_as_json(annotations, cache_path)

    def rename_label(self, current_label: str, new_name: str) -> bool:
        new_name = new_name.strip()
        if not current_label or not new_name or new_name == current_label:
            return False
        if current_label == "Undefined":
            QMessageBox.warning(
                self, "Protected Label", "The 'Undefined' label cannot be renamed."
            )
            return False

        existing_names = [
            label.name
            for label in self.config.predefined_labels
            if label.name != current_label
        ]
        if new_name in existing_names:
            QMessageBox.warning(self, "Duplicate", "Label name already exists!")
            return False

        target_index = next(
            (
                i
                for i, label in enumerate(self.config.predefined_labels)
                if label.name == current_label
            ),
            -1,
        )
        if target_index < 0:
            return False

        self.config.predefined_labels[target_index].name = new_name
        self.config.save_labels_to_cache()
        self.update_annotations_for_label_rename(current_label, new_name)
        self.current_label = new_name
        if self.layer:
            self.layer.current_label = new_name

        self.update_label_combo()
        new_index = self.label_combo.findText(new_name)
        if new_index >= 0:
            self.label_combo.setCurrentIndex(new_index)
        self.annotation_list.update_list()
        self.messageSignal.emit(f"Renamed label {current_label} to {new_name}")
        return True

    def rename_current_label(self):
        current_label = self.label_combo.currentText()
        if not current_label:
            return

        new_name, ok = QInputDialog.getText(
            self, "Rename Label", "Enter new label name:", text=current_label
        )
        new_name = new_name.strip() if ok and new_name else ""
        if not new_name:
            return
        self.rename_label(current_label, new_name)

    def delete_labels(self, label_names: list[str], confirm: bool = True) -> bool:
        label_names = [name for name in label_names if name]
        if not label_names:
            return False

        default_label = self.get_default_label()
        protected_labels = {default_label.name}
        if any(name in protected_labels for name in label_names):
            QMessageBox.warning(
                self,
                "Protected Label",
                "The default label cannot be removed.",
            )
            return False

        if confirm:
            label_text = ", ".join(label_names[:5])
            if len(label_names) > 5:
                label_text += ", ..."
            result = QMessageBox.question(
                self,
                "Delete Labels",
                f"Delete {len(label_names)} label(s): {label_text}?\nAffected annotations will be reassigned to '{default_label.name}'.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                return False

        self.config.predefined_labels = [
            label
            for label in self.config.predefined_labels
            if label.name not in set(label_names)
        ]
        self.config.save_labels_to_cache()
        for label_name in label_names:
            self.replace_deleted_label_in_annotations(label_name, default_label)
        self.current_label = default_label.name
        if self.layer:
            self.layer.current_label = default_label.name
            self.layer.current_color = default_label.color

        self.update_label_combo()
        default_index = self.label_combo.findText(default_label.name)
        if default_index >= 0:
            self.label_combo.setCurrentIndex(default_index)
        self.annotation_list.update_list()
        self.messageSignal.emit(f"Deleted {len(label_names)} label(s)")
        return True

    def delete_current_label(self):
        current_label = self.label_combo.currentText()
        if current_label:
            self.delete_labels([current_label])

    def open_label_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Manage Labels")
        dialog.setModal(True)
        dialog.resize(380, 440)

        layout = QVBoxLayout(dialog)

        label_info = QLabel(
            "Add, rename (double-click), recolor, or delete labels. Changes are saved directly to the label cache."
        )
        label_info.setWordWrap(True)
        layout.addWidget(label_info)

        label_list = QListWidget(dialog)
        label_list.setSelectionMode(QAbstractItemView.ExtendedSelection)

        def populate_list():
            with QSignalBlocker(label_list):
                label_list.clear()
                for label in self.config.predefined_labels:
                    pixmap = QPixmap(16, 16)
                    pixmap.fill(label.color)
                    item = QListWidgetItem(QIcon(pixmap), label.name)
                    item.setData(Qt.UserRole, label.name)
                    if label.name != "Undefined":
                        item.setFlags(item.flags() | Qt.ItemIsEditable)
                    label_list.addItem(item)

        populate_list()
        layout.addWidget(label_list)

        def handle_item_changed(item: QListWidgetItem):
            old_name = item.data(Qt.UserRole)
            new_name = item.text().strip()
            if not old_name or not new_name:
                item.setText(old_name)
                return
            if not self.rename_label(old_name, new_name):
                item.setText(old_name)
                return
            item.setData(Qt.UserRole, new_name)
            populate_list()

        label_list.itemChanged.connect(handle_item_changed)

        add_btn = QPushButton("Add New Label")
        add_btn.clicked.connect(lambda: (self.add_new_label(), populate_list()))
        layout.addWidget(add_btn)

        def recolor_selected():
            sel = label_list.selectedItems()
            if not sel:
                QMessageBox.information(
                    dialog, "No Selection", "Select a label to change its color."
                )
                return
            target_name = sel[0].data(Qt.UserRole)
            lbl_info = next(
                (lbl for lbl in self.config.predefined_labels if lbl.name == target_name),
                None,
            )
            if lbl_info is None:
                return
            color = QColorDialog.getColor(lbl_info.color, dialog)
            if color.isValid():
                lbl_info.color = color
                self.config.save_labels_to_cache()
                self.update_annotations_for_label_color(target_name, color)
                if self.layer:
                    self.normalize_annotation_colors(
                        self.layer.annotations, add_missing_labels=False
                    )
                    if self.layer.current_label == target_name:
                        self.layer.current_color = color
                    self.layer.update()
                self.update_label_combo()
                self.annotation_list.update_list()
                populate_list()

        color_btn = QPushButton("Change Selected Color")
        color_btn.clicked.connect(recolor_selected)
        layout.addWidget(color_btn)

        delete_button = QPushButton("Delete Selected")
        delete_button.clicked.connect(
            lambda: self._handle_label_manager_delete_selected(dialog, label_list)
        )
        layout.addWidget(delete_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.setLayout(layout)
        dialog.adjustSize()
        dialog.exec()

    def _handle_label_manager_delete_selected(
        self, dialog: QDialog, label_list: QListWidget
    ):
        selected_names = [
            item.data(Qt.UserRole) for item in label_list.selectedItems()
        ]
        if not selected_names:
            QMessageBox.information(
                dialog, "No Selection", "Select one or more labels to delete."
            )
            return
        if self.delete_labels(selected_names):
            dialog.accept()

    def sync_label_combo_to_selection(self):
        if not hasattr(self, "label_combo"):
            return

        selected_annotation = self.layer._get_selected_annotation() if self.layer else None
        target_label = (
            selected_annotation.label if selected_annotation is not None else self.current_label
        )
        if not target_label:
            return

        with QSignalBlocker(self.label_combo):
            combo_index = self.label_combo.findText(target_label)
            if combo_index >= 0:
                self.label_combo.setCurrentIndex(combo_index)

    def on_label_update(self, old_new_label: tuple[str, str]):
        old_name, new_name = old_new_label
        if not self.rename_label(old_name, new_name):
            self.ensure_label_available(new_name)
            self.update_label_combo()

    def choose_color(self):
        """Choose a color for the current label."""
        current_label = self.label_combo.currentText()
        label_info = next(
            (
                label
                for label in self.config.predefined_labels
                if label.name == current_label
            ),
            None,
        )

        if label_info:
            color = QColorDialog.getColor(label_info.color)
            if color.isValid():
                # Update label color
                label_info.color = color
                self.config.save_labels_to_cache()
                # Update combo box display
                index = self.label_combo.currentIndex()
                pixmap = QPixmap(16, 16)
                pixmap.fill(color)
                self.label_combo.setItemIcon(index, QIcon(pixmap))
                # Update canvas color
                self.layer.current_color = color
                self.layer.update()
                self.update_annotations_for_label_color(current_label, color)
                self.normalize_annotation_colors(self.layer.annotations, add_missing_labels=False)
                self.annotation_list.update_list()

    def add_new_label(self):
        """Add a new label to the predefined labels."""
        name, ok = QInputDialog.getText(self, "New Label", "Enter label name:")
        if not ok or not name:
            return

        # Check for existing label
        existing_names = [label.name for label in self.config.predefined_labels]
        if name in existing_names:
            QMessageBox.warning(self, "Duplicate", "Label name already exists!")
            return

        color = QColorDialog.getColor()
        if not color.isValid():
            return

        # Add new predefined label
        self.ensure_label_available(label_name=name, color=color)

        # Update combo box
        self.update_label_combo()

        # Select the new label
        index = self.label_combo.findText(name)
        self.label_combo.setCurrentIndex(index)

    def handle_label_change(self, index):
        """Handle the label change event."""
        if index < 0 or index >= len(self.config.predefined_labels):
            self.current_label = "Undefined"
            if self.layer:
                self.layer.current_label = "Undefined"
                self.layer.current_color = self._label_color("Undefined")
            return

        label_info = self.config.predefined_labels[index]
        self.current_label = label_info.name or "Undefined"

        self.layer.current_color = label_info.color
        self.layer.current_label = self.current_label
        msg = f"Label changed to {self.current_label}"
        self.messageSignal.emit(msg)
        selected_annotation = self.layer._get_selected_annotation()
        self.layer.selected_annotation = selected_annotation
        if selected_annotation and selected_annotation.label != label_info.name:
            self.layer._push_undo_state()
            selected_annotation.label = label_info.name
            selected_annotation.color = label_info.color
            self.on_annotation_updated(selected_annotation)

        self.layer.update()
        self.update()
