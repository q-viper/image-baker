from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMessageBox,
    QProgressDialog,
    QSizePolicy,
)

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig, LayerConfig
from imagebaker.core.defs import Annotation, MouseMode
from imagebaker.layers.annotable_history import AnnotableHistoryMixin
from imagebaker.layers.annotable_interaction import AnnotableInteractionMixin
from imagebaker.layers.annotable_rendering import AnnotableRenderMixin
from imagebaker.layers.base_layer import BaseLayer
from imagebaker.layers.canvas_layer import CanvasLayer
from imagebaker.workers import LayerifyWorker


class AnnotableLayer(
    AnnotableHistoryMixin,
    AnnotableRenderMixin,
    AnnotableInteractionMixin,
    BaseLayer,
):
    annotationAdded = Signal(Annotation)
    annotationRemoved = Signal()
    annotationUpdated = Signal(Annotation)
    annotationCleared = Signal()
    annotationMoved = Signal()
    layersChanged = Signal()
    labelUpdated = Signal(tuple)
    brushSizeChanged = Signal(int)

    def __init__(self, parent, config: LayerConfig, canvas_config: CanvasConfig):
        super().__init__(parent, config)
        self.canvas_config = canvas_config

        self.image = QPixmap()
        self.mouse_mode = MouseMode.POINT

        self.label_rects = []
        self.file_path: Path = Path("Runtime")
        self.layers: list[BaseLayer] = []
        self.is_annotable = True
        self.handle_zoom: float = 1

        self.brush_size = 18
        self._brush_mask = None
        self._brush_last_pos = None
        self._target_brush_annotation = None
        self._history_by_file: dict[str, tuple[list, list]] = {}
        self._max_history = 100
        self._drag_start_snapshot = None

    def init_ui(self):
        logger.info(f"Initializing Layer UI of {self.layer_name}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def clear_annotations(self):
        if self.annotations:
            self._push_undo_state()
        self.annotations.clear()
        self.selected_annotation = None
        self.current_annotation = None
        self.annotationCleared.emit()
        self.update()

    def toggle_annotation_visibility(self):
        """Toggle visibility of selected annotation."""
        selected_annotation = self._get_selected_annotation()
        if selected_annotation is not None:
            self._push_undo_state()
            selected_annotation.visible = not selected_annotation.visible
            self.annotationUpdated.emit(selected_annotation)
            self.update()

    def delete_selected_annotations(self):
        selected_annotations = [ann for ann in self.annotations if ann.selected]
        if not selected_annotations and self.selected_annotation is not None:
            selected_annotations = [self.selected_annotation]

        if not selected_annotations:
            self.messageSignal.emit("No annotation selected to delete.")
            return

        self._push_undo_state()
        selected_ids = {id(ann) for ann in selected_annotations}
        removed_count = len(selected_annotations)
        self.annotations = [
            ann for ann in self.annotations if id(ann) not in selected_ids
        ]

        for index, annotation in enumerate(self.annotations):
            annotation.annotation_id = index

        self.selected_annotation = None
        self.current_annotation = None
        self.annotationRemoved.emit()
        self.messageSignal.emit(f"Deleted {removed_count} annotation(s)")
        self.update()

    def edit_selected_annotation_caption(self):
        selected_annotation = self._get_selected_annotation()
        self.selected_annotation = selected_annotation
        if selected_annotation is None:
            self.messageSignal.emit("No annotation selected for caption editing.")
            return

        current_caption = getattr(selected_annotation, "caption", "")
        text, ok = QInputDialog.getMultiLineText(
            self, "Edit Caption", "Enter caption:", current_caption
        )
        if ok:
            self._push_undo_state()
            selected_annotation.caption = text
            self.annotationUpdated.emit(selected_annotation)
            self.update()

    def apply_opacity(self):
        """Apply opacity to the QPixmap image."""
        if self.image and self.opacity < 255:
            transparent_pixmap = QPixmap(self.image.size())
            transparent_pixmap.fill(Qt.transparent)
            painter = QPainter(transparent_pixmap)
            try:
                painter.setOpacity(self.opacity / 255.0)
                painter.drawPixmap(0, 0, self.image)
            finally:
                painter.end()
            self.image = transparent_pixmap

    def edit_annotation_label(self, annotation: Annotation):
        new_label, ok = QInputDialog.getText(
            self, "Edit Label", "Enter new label:", text=annotation.label
        )
        if ok and new_label:
            self.labelUpdated.emit((annotation.label, new_label))
            annotation.label = new_label
            self.annotationUpdated.emit(annotation)
            self.update()

    def finalize_annotation(self):
        if self.current_annotation is None:
            return
        self._push_undo_state()
        label_name = (self.current_label or "").strip() or self.config.default_label.name
        label_color = self.current_color or self.config.get_label_color(label_name)
        self.current_annotation.annotation_id = len(self.annotations)
        self.current_annotation.label = label_name
        self.current_annotation.color = label_color
        self.current_annotation.file_path = self.file_path
        self.current_annotation.is_complete = True
        self.annotations.append(self.current_annotation)

        self.thumbnails[self.current_annotation.annotation_id] = self.get_thumbnail(
            self.current_annotation
        )
        self.annotationAdded.emit(self.current_annotation)
        self.current_annotation = None
        self.update()

    def select_all_annotations(self):
        if not self.annotations:
            self.messageSignal.emit("No annotations to select.")
            return

        for ann in self.annotations:
            ann.selected = True
            self.annotationUpdated.emit(ann)
        self.selected_annotation = self.annotations[-1]
        self.messageSignal.emit(f"Selected {len(self.annotations)} annotations")
        self.update()

    def _get_selected_annotation(self):
        for annotation in self.annotations:
            if annotation.selected:
                return annotation

    def layerify_annotation(self, annotations: list[Annotation]):
        annotations = [ann for ann in annotations if ann.visible]

        if len(annotations) == 0:
            QMessageBox.information(
                self.parentWidget(), "Info", "No visible annotations to layerify"
            )
            return
        self.loading_dialog = QProgressDialog(
            "Processing annotation...",
            "Cancel",
            0,
            0,
            self.parentWidget(),
        )
        self.loading_dialog.setWindowTitle("Please Wait")
        self.loading_dialog.setWindowModality(Qt.WindowModal)
        self.loading_dialog.show()
        QApplication.processEvents()

        self.worker_thread = QThread()
        self.worker = LayerifyWorker(self.image, annotations, self.config)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(self.handle_layerify_result)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.handle_layerify_error)

        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.loading_dialog.close)

        self.worker_thread.start()

    def handle_layerify_result(self, annotation: Annotation, cropped_image: QPixmap):
        new_layer = CanvasLayer(parent=self.parent_obj, config=self.canvas_config)
        new_layer.set_image(cropped_image)
        new_layer.annotations = [annotation]
        new_layer.layer_name = (
            f"{annotation.label} {annotation.annotation_id} {annotation.annotator}"
        )
        new_layer.caption = annotation.caption

        new_layer._apply_edge_opacity()
        new_layer.update()
        self.messageSignal.emit(f"Layerified: {new_layer.layer_name}")
        logger.info(f"Num annotations: {len(self.annotations)}")
        self.layerSignal.emit(new_layer)

    def handle_layerify_error(self, error_msg: str):
        self.loading_dialog.close()
        QMessageBox.critical(
            self.parentWidget(), "Error", f"Processing failed: {error_msg}"
        )

    @property
    def selected_annotation_index(self):
        for idx, annotation in enumerate(self.annotations):
            if annotation.selected:
                return idx
        return -1
