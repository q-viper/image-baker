from imagebaker.layers.annotable_layer import AnnotableLayer
from imagebaker.list_views import AnnotationList
from imagebaker.list_views.image_list import ImageListPanel
from imagebaker import logger
from imagebaker.workers import ModelPredictionWorker
from imagebaker.utils.image import qpixmap_to_numpy

from PySide6.QtCore import QPointF, Qt, QRectF, Signal
from PySide6.QtGui import (
    QColor,
    QPixmap,
    QPolygonF,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QColorDialog,
    QSizePolicy,
    QFileDialog,
    QComboBox,
    QMessageBox,
    QDockWidget,
)
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QProgressDialog
from pathlib import Path
from imagebaker.core.configs import LayerConfig, CanvasConfig
from imagebaker.core.defs import (
    Label,
    MouseMode,
    Annotation,
    PredictionResult,
    BakingResult,
)
from collections import deque
from typing import Deque
from dataclasses import dataclass
import os


@dataclass
class ImageEntry:
    is_baked_result: bool
    data: AnnotableLayer | Path


class LayerifyTab(QWidget):
    """Layerify Tab implementation"""

    annotationRemoved = Signal(Annotation)
    layerAdded = Signal(AnnotableLayer)
    clearAnnotations = Signal()
    messageSignal = Signal(str)
    annotationAdded = Signal(Annotation)
    annotationUpdated = Signal(Annotation)
    gotToTab = Signal(int)

    def __init__(
        self,
        main_window,
        config: LayerConfig,
        canvas_config: CanvasConfig,
        loaded_models,
    ):
        """
        A tab for layerifying annotations and managing multiple layers.

        Args:
            main_window: The main window instance.
            config: LayerConfig instance with settings for the tab.
            canvas_config: CanvasConfig instance with settings for the canvas.
            loaded_models: Dictionary of loaded models.
        """
        super().__init__(parent=main_window)

        self.setFocusPolicy(Qt.StrongFocus)
        self.main_window = main_window
        self.config = config
        self.canvas_config = canvas_config
        self.main_layout = QVBoxLayout(self)

        self.all_models = loaded_models
        self.current_model = list(self.all_models.values())[0]
        self.current_label = self.config.default_label.name
        self.image_entries = []
        self.curr_image_idx = 0
        self.processed_images = set()
        self.annotable_layers: Deque[AnnotableLayer] = deque(
            maxlen=self.config.deque_maxlen
        )
        self.baked_results: Deque[AnnotableLayer] = deque(
            maxlen=self.config.deque_maxlen
        )
        self.layer = None
        self.init_ui()
        self._connect_signals()

    def _connect_signals(self):
        """Connect all necessary signals"""
        # Connect all layers in the deque to annotation list
        for layer in self.annotable_layers:
            # layer.annotationAdded.connect(self.annotation_list.update_list)
            layer.annotationAdded.connect(self.on_annotation_added)
            # layer.annotationUpdated.connect(self.annotation_list.update_list)
            layer.annotationUpdated.connect(self.on_annotation_updated)
            layer.messageSignal.connect(self.messageSignal)
            layer.layerSignal.connect(self.add_layer)
            layer.labelUpdated.connect(self.on_label_update)

        # Connect image list panel signals
        self.image_list_panel.imageSelected.connect(self.on_image_selected)
        self.image_list_panel.activeImageEntries.connect(self.update_active_entries)

    def init_ui(self):
        """Initialize the UI components"""
        # Create annotation list and image list panel
        self.annotation_list = AnnotationList(
            None, parent=self.main_window, max_name_length=self.config.max_name_length
        )
        self.image_list_panel = ImageListPanel(
            self.image_entries,
            self.processed_images,
            images_per_page=self.config.deque_maxlen,
        )

        self.main_window.addDockWidget(Qt.LeftDockWidgetArea, self.image_list_panel)

        # Add multiple layers (canvas) to the main layout
        for _ in range(self.annotable_layers.maxlen):
            layer = AnnotableLayer(
                parent=self.main_window,
                config=self.config,
                canvas_config=self.canvas_config,
            )
            layer.setVisible(False)  # Initially hide all layers
            self.annotable_layers.append(layer)
            self.main_layout.addWidget(layer)

        # Set the annotation list to the first layer by default
        if self.annotable_layers:
            self.layer = self.annotable_layers[0]
            self.layer.set_mode(MouseMode.RECTANGLE)
            self.annotation_list.layer = self.layer

        self.create_toolbar()

        # Create a dock widget for the toolbar
        self.toolbar_dock = QDockWidget("Tools", self)
        self.toolbar_dock.setWidget(self.toolbar)
        self.toolbar_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.main_window.addDockWidget(Qt.BottomDockWidgetArea, self.toolbar_dock)

        # Add annotation list to main window's docks
        self.main_window.addDockWidget(Qt.RightDockWidgetArea, self.annotation_list)
        self.load_default_images()

    def on_image_selected(self, image_entry: ImageEntry):
        """Handle image selection from the image list panel."""
        logger.info(f"Image selected: {image_entry}")

        # Hide all layers first
        for idx, layer in enumerate(self.annotable_layers):
            layer.setVisible(False)
            # logger.info(f"Layer {idx} hidden.")
        current_label = self.layer.current_label
        current_color = self.layer.current_color
        
        if not image_entry.is_baked_result:  # Regular image
            image_path = image_entry.data
            self.curr_image_idx = self.image_entries.index(image_entry)
            # convert curr_image_idx to correct index
            self.curr_image_idx = self.curr_image_idx % len(self.annotable_layers)

            # Make the corresponding layer visible and set the image
            selected_layer = self.annotable_layers[self.curr_image_idx]
            selected_layer.setVisible(True)
            # logger.info(f"Layer {self.curr_image_idx} made visible for regular image.")
            selected_layer.set_image(image_path)  # Set the selected image
            if self.layer:
                selected_layer.set_mode(self.layer.mouse_mode)
            self.layer = selected_layer  # Update the currently selected layer

        else:  # Baked result
            baked_result_layer = image_entry.data
            self.curr_image_idx = self.image_entries.index(image_entry)

            # Make the baked result layer visible
            baked_result_layer.setVisible(True)
            # logger.info(f"Layer {self.curr_image_idx} made visible for baked result.")
            self.layer = baked_result_layer  # Set the baked result as the current layer

        # Set the current label and color
        self.layer.current_label = current_label
        self.layer.current_color = current_color
        self.annotation_list.layer = self.layer
        self.annotation_list.update_list()

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
                if i < len(self.image_entries):
                    layer.set_image(self.image_entries[i].data)
                    self.load_layer_annotations(layer)
                    layer.layer_name = f"Layer_{i + 1}"
                    layer.setVisible(
                        i == 0
                    )  # Only the first layer is visible by default
                    if i == 0:
                        self.layer = layer  # Set the first layer as the current layer
                else:
                    layer.setVisible(False)

            self.messageSignal.emit(f"Showing image 1/{len(self.image_entries)}")
        else:
            # If no images are found, log a message
            logger.warning("No images found in the assets folder.")
            self.messageSignal.emit("No images found in the assets folder.")

        # Update the image list panel
        self.image_list_panel.update_image_list(self.image_entries)
        self.update()

    def save_layer_annotations(self, layer: AnnotableLayer):
        """Save annotations for a specific layer"""
        if len(layer.annotations) > 0:
            file_path = layer.file_path
            file_name = file_path.name
            save_dir = self.config.cache_dir / f"{file_name}.json"
            Annotation.save_as_json(layer.annotations, save_dir)
            logger.info(f"Saved annotations for {layer.layer_name} to {save_dir}")

    def load_layer_annotations(self, layer: AnnotableLayer):
        """Load annotations for a specific layer"""
        if layer.file_path:
            file_path = layer.file_path
            file_name = file_path.name
            load_dir = self.config.cache_dir / f"{file_name}.json"
            if load_dir.exists():
                layer.annotations = Annotation.load_from_json(load_dir)
                logger.info(
                    f"Loaded annotations for {layer.layer_name} from {load_dir}"
                )
            else:
                logger.warning(f"No annotations found for {layer.layer_name}")

    def update_active_entries(self, image_entries: list[ImageEntry]):
        """Update the active entries in the image list panel."""
        self.curr_image_idx = 0
        for i, layer in enumerate(self.annotable_layers):
            self.save_layer_annotations(layer)
            layer.annotations = []

            if i < len(image_entries):
                # get index on the self.image_entries
                idx = self.image_entries.index(image_entries[i])
                if self.image_entries[idx].is_baked_result:
                    # if the image is a baked result, set the layer to the baked result
                    layer = self.image_entries[idx].data
                    layer.file_path = layer.file_path
                else:
                    layer.set_image(self.image_entries[idx].data)
                self.load_layer_annotations(layer)

                layer.layer_name = f"Layer_{idx + 1}"
                layer.setVisible(i == 0)
                if i == 0:
                    self.layer = layer
            else:
                layer.setVisible(False)
        logger.info("Updated active entries in image list panel.")

    def clear_annotations(self):
        """Safely clear all annotations"""
        try:
            # Clear layer annotations
            self.clearAnnotations.emit()
            self.messageSignal.emit("Annotations cleared")
            # clear cache annotation of layer
            annotation_path = (
                self.config.cache_dir / f"{self.layer.file_path.name}.json"
            )
            if annotation_path.exists():
                os.remove(annotation_path)
                logger.info(f"Cleared annotations from {annotation_path}")

        except Exception as e:
            logger.error(f"Clear error: {str(e)}")
            self.messageSignal.emit(f"Error clearing: {str(e)}")

    def on_annotation_added(self, annotation: Annotation):
        """Handle annotation added event

        Args:
            annotation (Annotation): The annotation that was added.
        """

        # if annotation.label is not in the predefined labels, add it
        if annotation.label not in [lbl.name for lbl in self.config.predefined_labels]:
            logger.info(f"Label {annotation.label} created.")
            self.config.predefined_labels.append(
                Label(annotation.label, annotation.color)
            )
            self.update_label_combo()
        logger.info(f"Added annotation: {annotation.label}")
        self.messageSignal.emit(f"Added annotation: {annotation.label}")
        self.save_layer_annotations(self.layer)

        # Refresh the annotation list
        self.annotation_list.update_list()

    def on_annotation_updated(self, annotation: Annotation):
        """
        A slot to handle the annotation updated signal.

        Args:
            annotation (Annotation): The updated annotation.
        """
        # logger.info(f"Updated annotation: {annotation}")
        self.messageSignal.emit(f"Updated annotation: {annotation.label}")

        # Refresh the annotation list
        self.annotation_list.update_list()
        self.save_layer_annotations(self.layer)

    def update_label_combo(self):
        """
        Add predefined labels to the label combo box.

        This method is called when a new label is added.
        """
        self.label_combo.clear()
        for label in self.config.predefined_labels:
            pixmap = QPixmap(16, 16)
            pixmap.fill(label.color)
            self.label_combo.addItem(QIcon(pixmap), label.name)
        logger.info("Updated label combo box with predefined labels.")
        self.label_combo.setCurrentText(self.current_label)

    def on_label_update(self, old_new_label: tuple[str, str]):
        new_labels = []
        index = 0
        for i, label in enumerate(self.config.predefined_labels):
            if label.name == old_new_label[0]:
                label.name = old_new_label[1]
                index = i
            new_labels.append(label)

        self.config.predefined_labels = new_labels
        logger.info(f"Updated label from {old_new_label[0]} to {old_new_label[1]}")
        self.messageSignal.emit(
            f"Updated label from {old_new_label[0]} to {old_new_label[1]}."
        )

        self.update_label_combo()
        self.handle_label_change(index=index)
        self.label_combo.update()

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

    def handle_predict(self):
        """
        Handle the predict button click event.

        """
        if self.current_model is None:
            logger.warning("No model selected to predict")
            self.messageSignal.emit("No model selected/or loaded to predict")
            return
        # get image as an numpy array from canvas
        image = qpixmap_to_numpy(self.layer.image)
        if image is None:
            return
        # get annotations from canvas
        annotations = [
            ann
            for ann in self.layer.annotations
            if not ann.is_model_generated and ann.visible
        ]

        if len(annotations) == 0:
            logger.warning("No annotations to predict passing image to model")
            self.messageSignal.emit("No annotations to predict passing image to model")
            # return

        points = []
        polygons = []
        rectangles = []
        label_hints = []
        for ann in annotations:
            if ann.points:
                points.append([[p.x(), p.y()] for p in ann.points])
            if ann.polygon:
                polygons.append([[p.x(), p.y()] for p in ann.polygon])
            if ann.rectangle:
                rectangles.append(
                    [
                        ann.rectangle.x(),
                        ann.rectangle.y(),
                        ann.rectangle.x() + ann.rectangle.width(),
                        ann.rectangle.y() + ann.rectangle.height(),
                    ]
                )
            label_hints.append([0])
            ann.visible = False

        points = points if len(points) > 0 else None
        polygons = polygons if len(polygons) > 0 else None
        rectangles = [rectangles] if len(rectangles) > 0 else None
        label_hints = label_hints if len(label_hints) > 0 else None

        self.loading_dialog = QProgressDialog(
            "Processing annotation...",
            "Cancel",  # Optional cancel button
            0,
            0,
            self.parentWidget(),  # Or your main window reference
        )
        self.loading_dialog.setWindowTitle("Please Wait")
        self.loading_dialog.setWindowModality(Qt.WindowModal)
        self.loading_dialog.setCancelButton(None)  # Remove cancel button if not needed
        self.loading_dialog.show()

        # Force UI update
        QApplication.processEvents()

        # Setup worker thread
        self.worker_thread = QThread()
        self.worker = ModelPredictionWorker(
            self.current_model, image, points, polygons, rectangles, label_hints
        )
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(self.handle_model_result)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.handle_model_error)

        # Cleanup connections
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.loading_dialog.close)

        # Start processing
        self.worker_thread.start()

    def handle_model_result(self, predictions: list[PredictionResult]):
        """
        A slot to handle the model prediction results.

        Args:
            predictions (list[PredictionResult]): The list of prediction results.
        """
        # update canvas with predictions
        for prediction in predictions:
            if prediction.class_name not in self.config.predefined_labels:
                self.config.predefined_labels.append(Label(prediction.class_name))
                self.update_label_combo()
            if prediction.rectangle:
                # make sure the returned rectangle is within the image

                self.layer.annotations.append(
                    Annotation(
                        annotation_id=len(self.layer.annotations),
                        label=prediction.class_name,
                        color=self.config.get_label_color(prediction.class_name)
                        or QColor(255, 255, 255),
                        rectangle=QRectF(*prediction.rectangle),
                        is_complete=True,
                        score=prediction.score,
                        annotator=self.current_model.name,
                        annotation_time=str(
                            prediction.annotation_time
                            if prediction.annotation_time
                            else ""
                        ),
                        file_path=self.layer.file_path,
                    )
                )
            elif prediction.polygon is not None:

                self.layer.annotations.append(
                    Annotation(
                        annotation_id=len(self.layer.annotations),
                        label=prediction.class_name,
                        color=self.config.get_label_color(prediction.class_name)
                        or QColor(255, 255, 255),
                        polygon=QPolygonF([QPointF(*p) for p in prediction.polygon]),
                        is_complete=True,
                        score=prediction.score,
                        annotator=self.current_model.name,
                        annotation_time=str(prediction.annotation_time),
                        file_path=self.layer.file_path,
                    )
                )
            else:
                # points as center of canvas
                x, y = self.layer.width() // 2, self.layer.height() // 2
                self.layer.annotations.append(
                    Annotation(
                        annotation_id=len(self.layer.annotations),
                        label=prediction.class_name,
                        color=self.config.get_label_color(prediction.class_name)
                        or QColor(255, 255, 255),
                        points=[QPointF(x, y)],
                        is_complete=True,
                        score=prediction.score,
                        annotator=self.current_model.name,
                        annotation_time=str(prediction.annotation_time),
                        file_path=self.layer.file_path,
                    )
                )

        self.layer.update()
        self.annotation_list.update_list()
        self.update_annotation_list()

    def handle_model_change(self, index):
        """
        Handle the model change event.

        Args:
            index (int): The index of the selected model.
        """
        model_name = self.model_combo.currentText()
        self.current_model = self.all_models[model_name]
        msg = f"Model changed to {model_name}"
        logger.info(msg)
        self.messageSignal.emit(msg)

    def handle_model_error(self, error):
        logger.error(f"Model error: {error}")
        QMessageBox.critical(self, "Error", f"Model error: {error}")
        self.loading_dialog.close()

    def save_annotations(self):
        """Save annotations to a JSON file."""
        if not self.layer.annotations:
            QMessageBox.warning(self, "Warning", "No annotations to save!")
            return

        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Save Annotations", "", "JSON Files (*.json)", options=options
        )

        if file_name:
            try:
                Annotation.save_as_json(self.layer.annotations, file_name)

                QMessageBox.information(
                    self, "Success", "Annotations saved successfully!"
                )

            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to save annotations: {str(e)}"
                )

    def load_annotations(self):
        """
        Load annotations from a JSON file.
        """
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Load Annotations", "", "JSON Files (*.json)", options=options
        )

        if file_name:
            try:
                self.layer.annotations = Annotation.load_from_json(file_name)
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

    def update_annotation_list(self):
        """Update the annotation list with the current annotations."""
        self.annotation_list.update_list()

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
                # Update combo box display
                index = self.label_combo.currentIndex()
                pixmap = QPixmap(16, 16)
                pixmap.fill(color)
                self.label_combo.setItemIcon(index, QIcon(pixmap))
                # Update canvas color
                self.layer.current_color = color
                self.layer.update()
        for annotation in self.layer.annotations:
            if annotation.label == current_label:
                annotation.color = color
                self.layer.update()

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
        self.config.predefined_labels.append(Label(name=name, color=color))

        # Update combo box
        self.update_label_combo()

        # Select the new label
        index = self.label_combo.findText(name)
        self.label_combo.setCurrentIndex(index)

    def handle_label_change(self, index):
        """Handle the label change event."""
        label_info = self.config.predefined_labels[index]
        self.current_label = label_info.name
        # sort the labels by putting selected label on top
        self.config.predefined_labels.remove(label_info)
        self.config.predefined_labels.insert(0, label_info)
        # self.update_label_combo()

        self.layer.current_color = label_info.color
        self.layer.current_label = (
            self.current_label if self.current_label != "Custom" else None
        )
        msg = f"Label changed to {self.current_label}"
        self.messageSignal.emit(msg)
        self.layer.selected_annotation = self.layer._get_selected_annotation()
        if self.layer.selected_annotation:
            annotations = []
            for ann in self.layer.annotations:
                if ann == self.layer.selected_annotation:
                    ann.label = label_info.name
                    ann.color = label_info.color
                annotations.append(ann)

            self.layer.annotations = annotations
            self.on_annotation_updated(self.layer.selected_annotation)
            # disable label change callback
            self.label_combo.currentIndexChanged.disconnect()
            self.label_combo.currentIndexChanged.connect(lambda: None)
            self.update_label_combo()
            # set it back
            self.label_combo.currentIndexChanged.connect(self.handle_label_change)

        self.layer.update()
        self.update()

    def add_layer(self, layer):
        """Add a new layer to the tab."""
        # this layer i.e. canvas will have only one annotation
        logger.info(f"AnnotableLayer added: {layer.annotations[0].label}")
        self.layerAdded.emit(layer)

        self.layer.update()

    def layerify_all(self):
        """Layerify all annotations in the current layer."""
        if len(self.layer.annotations) == 0:
            logger.warning("No annotations to layerify")
            self.messageSignal.emit("No annotations to layerify")

            return
        logger.info("Layerifying all annotations")

        # else appends already added too
        self.layer.layerify_annotation(self.layer.annotations)

    def create_toolbar(self):
        """Create Layerify-specific toolbar"""
        self.toolbar = QWidget()
        toolbar_layout = QHBoxLayout(self.toolbar)

        modes = [
            ("📍", "Point", lambda x: self.layer.set_mode(MouseMode.POINT)),
            ("🔷", "Polygon", lambda x: self.layer.set_mode(MouseMode.POLYGON)),
            ("🔳", "Rectangle", lambda x: self.layer.set_mode(MouseMode.RECTANGLE)),
            ("⏳", "Idle", lambda x: self.layer.set_mode(MouseMode.IDLE)),
            ("💾", "Annotations", self.save_annotations),
            ("📂", "Annotations", self.load_annotations),
            ("🔮", "Predict", self.handle_predict),
            ("🎨", "Color", self.choose_color),
            ("🧅", "Layerify All", self.layerify_all),
            ("🏷️", "Add Label", self.add_new_label),
            ("🗑️", "Clear", self.clear_annotations),
        ]

        # Folder navigation buttons
        self.select_folder_btn = QPushButton("Select Folder")
        self.select_folder_btn.clicked.connect(self.select_folder)
        toolbar_layout.addWidget(self.select_folder_btn)

        # Add mode buttons
        for icon, text, mode in modes:
            btn_txt = icon + text
            btn = QPushButton(btn_txt)
            btn.setToolTip(btn_txt)
            btn.setMaximumWidth(80)
            if isinstance(mode, MouseMode):
                btn.clicked.connect(lambda _, m=mode: self.layer.set_mode(m))
            else:
                btn.clicked.connect(mode)
            toolbar_layout.addWidget(btn)

        # Add spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar_layout.addWidget(spacer)

        # Label and Model dropdowns
        self.label_combo = QComboBox()
        self.label_combo.setStyleSheet("QComboBox { min-width: 120px; }")
        for label in self.config.predefined_labels:
            pixmap = QPixmap(16, 16)
            pixmap.fill(label.color)
            self.label_combo.addItem(QIcon(pixmap), label.name)
        self.label_combo.currentIndexChanged.connect(self.handle_label_change)
        toolbar_layout.addWidget(self.label_combo)

        self.model_combo = QComboBox()
        self.model_combo.setStyleSheet("QComboBox { min-width: 120px; }")
        for model_name in self.all_models.keys():
            self.model_combo.addItem(model_name)
        self.model_combo.currentIndexChanged.connect(self.handle_model_change)
        toolbar_layout.addWidget(self.model_combo)

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

    def __del__(self):
        logger.warning(f"Tab {id(self)} deleted")

    def add_baked_result(self, baking_result: BakingResult):
        """Add a baked result to the baked results list and update the image list."""
        # Create a new layer for the baked result
        self.layer.setVisible(False)  # Hide the current layer
        layer = AnnotableLayer(
            parent=self.main_window,
            config=self.config,
            canvas_config=self.canvas_config,
        )
        # save it in cache
        filename = baking_result.filename
        filepath = self.config.bake_dir / filename.name
        baking_result.image.save(str(filepath))
        #
        Annotation.save_as_json(
            baking_result.annotations, self.config.cache_dir / f"{filename.name}.json"
        )

        layer.set_image(filepath)

        layer.annotationAdded.connect(self.on_annotation_added)
        layer.annotationUpdated.connect(self.on_annotation_updated)
        layer.labelUpdated.connect(self.on_label_update)
        layer.messageSignal.connect(self.messageSignal)
        layer.layerSignal.connect(self.add_layer)

        layer.set_image(baking_result.image)  # Set the baked result's image
        layer.setVisible(True)  # Hide the layer initially
        self.main_layout.addWidget(layer)  # Add the layer to the layout

        # Add the baked result layer to annotable_layers for proper visibility management
        self.annotable_layers.append(layer)

        # Add baked result to image_entries
        baked_result_entry = ImageEntry(is_baked_result=False, data=filepath)
        self.image_entries.append(baked_result_entry)
        # baking_result.image.save(str(baking_result.filename))
        layer.update()

        logger.info("A baked result has arrived, adding it to the image list.")

        # Update the image list panel
        # find the page index where this layer is
        page_index = (
            self.image_entries.index(baked_result_entry) // self.config.deque_maxlen
        )
        # set the current page to the page index
        self.image_list_panel.current_page = page_index
        self.image_list_panel.update_image_list(self.image_entries)
        self.image_list_panel.imageSelected.emit(baked_result_entry)

        self.messageSignal.emit("Baked result added")
        self.gotToTab.emit(0)

    def keyPressEvent(self, event):
        """Handle key press events for setting labels and deleting annotations."""
        key = event.key()

        # Debugging: Log the key press
        logger.info(f"Key pressed in LayerifyTab: {key}")

        # Handle keys 0-9 for setting labels
        if Qt.Key_0 <= key <= Qt.Key_9:
            label_index = key - Qt.Key_0  # Convert key to index (0-9)
            if label_index < len(self.config.predefined_labels):
                # Set the current label to the corresponding predefined label
                self.current_label = self.config.predefined_labels[label_index].name
                self.label_combo.setCurrentIndex(label_index)
                self.layer.current_label = self.current_label
                self.layer.update()
                logger.info(f"Label set to: {self.current_label}")
            else:
                # Show dialog to add a new label if the index is out of range
                self.add_new_label()

        # Handle Delete key for removing the selected annotation
        elif key == Qt.Key_Delete:
            self.layer.selected_annotation = self.layer._get_selected_annotation()
            if self.layer and self.layer.selected_annotation:

                self.layer.annotations.remove(self.layer.selected_annotation)
                self.layer.selected_annotation = None  # Clear the selection
                self.layer.update()
                self.annotation_list.update_list()
                logger.info("Selected annotation deleted.")

        # if clicked q, set the mode to point
        elif key == Qt.Key_Q:
            self.layer.set_mode(MouseMode.POINT)
            logger.info("Mouse mode set to POINT.")
        # if clicked w, set the mode to polygon
        elif key == Qt.Key_W:
            self.layer.set_mode(MouseMode.POLYGON)
            logger.info("Mouse mode set to POLYGON.")
        # if clicked e, set the mode to rectangle
        elif key == Qt.Key_E:
            self.layer.set_mode(MouseMode.RECTANGLE)
            logger.info("Mouse mode set to RECTANGLE.")

        # Pass the event to the annotation list if it needs to handle it
        if self.annotation_list.hasFocus():
            self.annotation_list.keyPressEvent(event)

        # Pass unhandled events to the base class
        super().keyPressEvent(event)
