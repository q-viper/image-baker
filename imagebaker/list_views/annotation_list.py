from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QPixmap,
    QIcon,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSizePolicy,
    QDockWidget,
    QListWidget,
    QListWidgetItem,
)

from imagebaker.layers.annotable_layer import AnnotableLayer
from imagebaker import logger


class AnnotationList(QDockWidget):
    messageSignal = Signal(str)

    def __init__(self, layer: AnnotableLayer, parent=None):
        super().__init__("Annotations", parent)
        self.layer = layer
        self.init_ui()

    def init_ui(self):
        logger.info("Initializing AnnotationList")
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.list_widget = QListWidget()

        # Set the size policy for the list widget to expand dynamically
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout.addWidget(self.list_widget)
        self.setWidget(widget)
        self.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )

    def update_list(self):
        self.list_widget.clear()
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
            widget.mousePressEvent = lambda event, i=idx: self.on_annotation_selected(i)

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
            short_path = ann.file_path.stem
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
        self.update()

    def create_color_icon(self, color):
        pixmap = QPixmap(16, 16)
        pixmap.fill(color)
        return QIcon(pixmap)

    def on_annotation_selected(self, index):
        if 0 <= index < len(self.layer.annotations):
            ann = self.layer.annotations[index]
            ann.selected = not ann.selected
            # Set other annotations to not selected
            for i, a in enumerate(self.layer.annotations):
                if i != index:
                    a.selected = False
            self.layer.update()
            self.update_list()

    def delete_annotation(self, index):
        if 0 <= index < len(self.layer.annotations):
            logger.info(f"Deleting annotation: {self.layer.annotations[index].label}")
            del self.layer.annotations[index]
            self.layer.update()
            self.update_list()
            logger.info("Annotation deleted")

    def toggle_visibility(self, index):
        if 0 <= index < len(self.layer.annotations):
            ann = self.layer.annotations[index]
            ann.visible = not ann.visible
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
        if event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
            self.layer.copy_annotation()
        elif event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
            self.layer.paste_annotation()
        elif event.key() == Qt.Key_Delete:
            self.delete_annotation(self.layer.selected_annotation_index)
        else:
            self.parentWidget().keyPressEvent(event)
