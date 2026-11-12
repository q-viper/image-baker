from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagebaker import logger
from imagebaker.layers.annotable_layer import AnnotableLayer


class AnnotationList(QDockWidget):
    messageSignal = Signal(str)
    layerifySelectedRequested = Signal()
    layerifyAllRequested = Signal()
    saveRequested = Signal()
    loadRequested = Signal()
    clearRequested = Signal()

    def __init__(self, layer: AnnotableLayer, parent=None, max_name_length=15):
        super().__init__("Annotations", parent)
        self.layer = layer
        self.max_name_length = max_name_length
        self.init_ui()

    def init_ui(self):
        logger.info("Initializing AnnotationList")
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        widget = QWidget()
        widget.setMinimumWidth(140)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        self.count_label = QLabel("Regions: 0")
        self.count_label.setStyleSheet("font-weight: bold;")
        header_row.addWidget(self.count_label)
        header_row.addStretch()

        self.select_all_btn = QPushButton("☑")
        self.select_all_btn.setFixedWidth(28)
        self.select_all_btn.setToolTip("Select / Deselect All Annotations (Ctrl+A)")
        self.select_all_btn.clicked.connect(self.toggle_select_all)
        header_row.addWidget(self.select_all_btn)

        self.toggle_all_vis_btn = QPushButton("👀")
        self.toggle_all_vis_btn.setFixedWidth(28)
        self.toggle_all_vis_btn.setToolTip("Show / Hide All Annotations")
        self.toggle_all_vis_btn.clicked.connect(self.toggle_all_visibility)
        header_row.addWidget(self.toggle_all_vis_btn)
        layout.addLayout(header_row)

        self.list_widget = QListWidget()

        # Set the size policy for the list widget to expand dynamically
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout.addWidget(self.list_widget)

        btn_row = QWidget()
        btn_row.setMinimumWidth(0)
        btn_layout = QGridLayout(btn_row)
        btn_layout.setContentsMargins(0, 2, 0, 0)
        btn_layout.setSpacing(4)

        self.layerify_selected_btn = QPushButton("✂️ Extract")
        self.layerify_selected_btn.setToolTip(
            "Extract selected visible annotations into Baker layers (L)"
        )
        self.layerify_selected_btn.clicked.connect(self.layerifySelectedRequested.emit)

        self.layerify_all_btn = QPushButton("🧅 Layerify All")
        self.layerify_all_btn.setToolTip("Extract all visible annotations into Baker layers")
        self.layerify_all_btn.clicked.connect(self.layerifyAllRequested.emit)

        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setToolTip("Save annotations to file")
        self.save_btn.clicked.connect(self.saveRequested.emit)

        self.load_btn = QPushButton("📂 Load")
        self.load_btn.setToolTip("Load annotations from file")
        self.load_btn.clicked.connect(self.loadRequested.emit)

        self.clear_btn = QPushButton("🗑️ Clear")
        self.clear_btn.setToolTip("Clear all annotations")
        self.clear_btn.clicked.connect(self.clearRequested.emit)

        for btn in (
            self.layerify_selected_btn,
            self.layerify_all_btn,
            self.save_btn,
            self.load_btn,
            self.clear_btn,
        ):
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        btn_layout.addWidget(self.layerify_selected_btn, 0, 0, 1, 3)
        btn_layout.addWidget(self.layerify_all_btn, 0, 3, 1, 3)
        btn_layout.addWidget(self.save_btn, 1, 0, 1, 2)
        btn_layout.addWidget(self.load_btn, 1, 2, 1, 2)
        btn_layout.addWidget(self.clear_btn, 1, 4, 1, 2)

        layout.addWidget(btn_row)
        self.setWidget(widget)
        self.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )

    def toggle_select_all(self):
        if self.layer is None or not self.layer.annotations:
            return
        all_selected = all(ann.selected for ann in self.layer.annotations)
        next_selected = not all_selected
        for ann in self.layer.annotations:
            ann.selected = next_selected
        self.layer.selected_annotation = (
            self.layer.annotations[-1] if next_selected else None
        )
        self.layer.update()
        self.update_list()

    def toggle_all_visibility(self):
        if self.layer is None or not self.layer.annotations:
            return
        all_visible = all(ann.visible for ann in self.layer.annotations)
        next_visible = not all_visible
        for ann in self.layer.annotations:
            ann.visible = next_visible
        self.layer.update()
        self.update_list()

    def update_list(self):
        scroll_bar = self.list_widget.verticalScrollBar()
        scroll_value = scroll_bar.value()
        current_selected_ids = {
            ann.annotation_id for ann in self.layer.annotations if ann.selected
        } if self.layer is not None else set()

        self.list_widget.clear()
        if hasattr(self, "count_label"):
            total = len(self.layer.annotations) if self.layer is not None else 0
            self.count_label.setText(f"Regions: {total}")
        if self.layer is None:
            return
        for idx, ann in enumerate(self.layer.annotations):

            item = QListWidgetItem(self.list_widget)

            # Create container widget
            widget = QWidget()
            widget.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))

            layout = QHBoxLayout(widget)
            layout.setContentsMargins(1, 1, 2, 2)

            # on clicking this element, select the annotation
            widget.mousePressEvent = lambda event, i=idx: self.on_annotation_selected(i, event)

            widget.setCursor(Qt.PointingHandCursor)

            # Color indicator
            color_label = QLabel()
            color = QColor(ann.color)
            if not ann.visible:
                color.setAlpha(128)
            pixmap = QPixmap(20, 20)
            pixmap.fill(ann.color)
            color_label.setPixmap(pixmap)
            layout.addWidget(color_label)

            # Text container
            text_container = QWidget()
            text_layout = QVBoxLayout(text_container)
            text_layout.setContentsMargins(0, 0, 0, 0)

            # Main label with conditional color
            main_label = QLabel(f"{ann.name}")
            main_color = "#666" if not ann.visible else "black"
            main_label.setStyleSheet(f"font-weight: bold; color: {main_color};")
            text_layout.addWidget(main_label)

            # Change the text color of the selected annotation
            if ann.selected:
                main_label.setStyleSheet("font-weight: bold; color: blue;")
            else:
                main_label.setStyleSheet(f"font-weight: bold; color: {main_color};")

            # Secondary info
            secondary_text = []
            score_text = (
                f"{ann.annotator}: {ann.score:.2f}"
                if ann.score is not None
                else ann.annotator
            )
            secondary_text.append(score_text)
            short_path = ann.file_path.stem[: self.max_name_length]
            secondary_text.append(f"<span style='color:#666;'>{short_path}</span>")

            if secondary_text:
                info_color = "#888" if not ann.visible else "#444"
                info_label = QLabel("<br>".join(secondary_text))
                info_label.setStyleSheet(f"color: {info_color}; font-size: 10px;")
                text_layout.addWidget(info_label)

            text_layout.addStretch()
            layout.addWidget(text_container)
            layout.addStretch()

            # Buttons
            btn_container = QWidget()
            btn_layout = QHBoxLayout(btn_container)

            layerify_btn = QPushButton("🖨")
            layerify_btn.setFixedWidth(30)
            layerify_btn.setToolTip("Make AnnotableLayer from annotation")
            layerify_btn.clicked.connect(lambda _, i=idx: self.layerify_annotation(i))
            btn_layout.addWidget(layerify_btn)

            vis_btn = QPushButton("👀" if ann.visible else "👁️")
            vis_btn.setFixedWidth(30)
            vis_btn.setCheckable(True)
            vis_btn.setChecked(ann.visible)
            vis_btn.setToolTip("Visible" if ann.visible else "Hidden")
            vis_btn.clicked.connect(lambda _, i=idx: self.toggle_visibility(i))
            btn_layout.addWidget(vis_btn)

            del_btn = QPushButton("🗑️")
            del_btn.setFixedWidth(30)
            del_btn.setToolTip("Delete annotation")
            del_btn.clicked.connect(lambda _, i=idx: self.delete_annotation(i))
            btn_layout.addWidget(del_btn)

            layout.addWidget(btn_container)

            item.setSizeHint(widget.sizeHint())
            self.list_widget.setItemWidget(item, widget)
            if ann.annotation_id in current_selected_ids:
                item.setSelected(True)
        scroll_bar.setValue(
            min(scroll_value, scroll_bar.maximum())
        )
        self.update()

    def create_color_icon(self, color):
        pixmap = QPixmap(16, 16)
        pixmap.fill(color)
        return QIcon(pixmap)

    def on_annotation_selected(self, index, event=None):
        if 0 <= index < len(self.layer.annotations):
            ann = self.layer.annotations[index]
            is_multi_select = (
                event is not None and bool(event.modifiers() & Qt.ControlModifier)
            )
            if is_multi_select:
                ann.selected = not ann.selected
                self.layer.selected_annotation = ann if ann.selected else self.layer._get_selected_annotation()
            else:
                ann.selected = not ann.selected
                self.layer.selected_annotation = ann if ann.selected else None
                # Set other annotations to not selected
                for i, a in enumerate(self.layer.annotations):
                    if i != index:
                        a.selected = False
            self.layer.annotationUpdated.emit(ann)
            self.layer.update()
            self.update_list()

    def delete_annotation(self, index):
        if 0 <= index < len(self.layer.annotations):
            logger.info(f"Deleting annotation: {self.layer.annotations[index].label}")
            self.layer.annotations[index].selected = True
            self.layer.selected_annotation = self.layer.annotations[index]
            self.layer.delete_selected_annotations()
            self.update_list()
            logger.info("Annotation deleted")

    def toggle_visibility(self, index):
        if 0 <= index < len(self.layer.annotations):
            self.layer._push_undo_state()
            ann = self.layer.annotations[index]
            ann.visible = not ann.visible
            self.layer.annotationUpdated.emit(ann)
            self.layer.update()
            self.update_list()
            logger.info(f"Annotation visibility toggled: {ann.label}, {ann.visible}")

    def layerify_annotation(self, index):
        if 0 <= index < len(self.layer.annotations):
            ann = self.layer.annotations[index]
            logger.info(f"Layerifying annotation: {ann.label}")

            self.update_list()
            self.layer.layerify_annotation([ann])
            self.layer.update()

    def sizeHint(self):
        """Calculate the preferred size based on the content."""
        base_size = super().sizeHint()
        content_width = self.list_widget.sizeHintForColumn(0) + 40  # Add padding
        return QSize(max(base_size.width(), content_width), base_size.height())

    def keyPressEvent(self, event):
        key = event.key()
        logger.info(f"Key pressed in AnnotationList: {key}")
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Z:
            if event.modifiers() & Qt.ShiftModifier:
                self.layer.redo()
            else:
                self.layer.undo()
            self.update_list()
            event.accept()
            return
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Y:
            self.layer.redo()
            self.update_list()
            event.accept()
            return
        elif event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
            self.layer.copy_annotation()
            event.accept()
            return
        elif event.key() == Qt.Key_A and event.modifiers() == Qt.ControlModifier:
            self.layer.select_all_annotations()
            self.update_list()
            event.accept()
            return
        elif event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
            self.layer.paste_annotation()
            event.accept()
            return
        elif event.key() == Qt.Key_Delete:
            self.delete_annotation(self.layer.selected_annotation_index)
            event.accept()
            return
        elif event.key() == Qt.Key_H:
            self.layer.toggle_annotation_visibility()
            event.accept()
            return
        # self.parentWidget().keyPressEvent(event)
