from PySide6.QtCore import QPointF, Qt, QRectF
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
    QMainWindow,
    QSizePolicy,
    QFileDialog,
    QComboBox,
    QMessageBox,
    QDockWidget,
    QTabWidget,
)
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QProgressDialog
from pathlib import Path

from imagebaker.core.configs import LayerConfig
from imagebaker.core.defs import Label, MouseMode, Annotation, PredictionResult
from imagebaker.tab_views import Layer, Canvas
from imagebaker.list_views import LayerList, LayerSettings, AnnotationList
from imagebaker.models.base_model import DefaultModel
from imagebaker import logger
from imagebaker.workers import ModelPredictionWorker
from imagebaker.utils.image import qpixmap_to_numpy


from loaded_models import LOADED_MODELS


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = LayerConfig()
        self.annotation_list: AnnotationList = None
        self.layer_list: LayerList = None
        self.canvas: Canvas
        self.all_models: dict[str, DefaultModel] = LOADED_MODELS
        self.current_model: DefaultModel = list(self.all_models.values())[0]
        self.current_label = self.config.default_label.name
        self.image_paths = []
        self.curr_image_idx = 0
        self.init_ui()
        self.load_default_image()

    def init_ui(self):
        """Initialize the main window and set up tabs."""
        self.setWindowTitle("Image Annotator")
        self.setGeometry(100, 100, 1200, 800)

        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")

        # Create main tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self.handle_tab_change)
        self.setCentralWidget(self.tab_widget)

        # Create shared tools dock
        self.tools_dock = QDockWidget("Tools", self)
        self.tools_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.tools_dock)

        # Initialize tabs
        self.init_layerify_ui()
        self.init_baker_ui()

        # Handle initial tab state
        self.handle_tab_change(0)

    def init_layerify_ui(self):
        """Initialize the Layerify tab UI."""
        # Create tab and main layout
        layerify_tab = QWidget()
        self.tab_widget.addTab(layerify_tab, "Layerify")
        main_layout = QVBoxLayout(layerify_tab)

        # Create Layerify-specific toolbar
        self.layerify_toolbar = QWidget()
        toolbar_layout = QHBoxLayout(self.layerify_toolbar)

        # Add Layerify tools
        modes = [
            ("📍", "Point", MouseMode.POINT),
            ("🔷", "Polygon", MouseMode.POLYGON),
            ("🔳", "Rectangle", MouseMode.RECTANGLE),
            ("⏳", "Idle", MouseMode.IDLE),
            ("💾", "Annotations", self.save_annotations),
            ("📂", "Annotations", self.load_annotations),
            ("🔮", "Predict", self.handle_predict),
            ("🎨", "Color", self.choose_color),
            ("🧅", "Layerify All", self.layerify_all),
            ("🏷️", "Add Label", self.add_new_label),
            ("🗑️", "Clear", self.clear_annotations),
        ]

        self.select_folder_btn = QPushButton("Select Folder")
        self.select_folder_btn.clicked.connect(self.select_folder)
        toolbar_layout.addWidget(self.select_folder_btn)
        self.next_image_btn = QPushButton("Next")
        self.next_image_btn.clicked.connect(self.show_next_image)
        toolbar_layout.addWidget(self.next_image_btn)
        self.prev_image_btn = QPushButton("Prev")
        self.prev_image_btn.clicked.connect(self.show_prev_image)
        toolbar_layout.addWidget(self.prev_image_btn)
        # hide next, prev buttons
        self.next_image_btn.setVisible(False)
        self.prev_image_btn.setVisible(False)

        for icon, text, mode in modes:
            btn_txt = icon + text
            btn = QPushButton(btn_txt)
            btn.setToolTip(btn_txt)
            btn.setMaximumWidth(80)  # Set max width to 30
            if isinstance(mode, MouseMode):
                btn.clicked.connect(lambda _, m=mode: self.layer.set_mode(m))
            else:
                btn.clicked.connect(mode)
            toolbar_layout.addWidget(btn)

        # Add spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar_layout.addWidget(spacer)

        # Label dropdown
        self.label_combo = QComboBox()
        self.label_combo.setStyleSheet("QComboBox { min-width: 120px; }")
        for label in self.config.predefined_labels:
            pixmap = QPixmap(16, 16)
            pixmap.fill(label.color)
            self.label_combo.addItem(QIcon(pixmap), label.name)
        self.label_combo.currentIndexChanged.connect(self.handle_label_change)
        toolbar_layout.addWidget(self.label_combo)

        # Model dropdown
        self.model_combo = QComboBox()
        self.model_combo.setStyleSheet("QComboBox { min-width: 120px; }")
        for model_name in self.all_models.keys():
            self.model_combo.addItem(model_name)
        self.model_combo.currentIndexChanged.connect(self.handle_model_change)
        toolbar_layout.addWidget(self.model_combo)

        # Canvas setup
        self.layer = Layer(config=self.config)
        main_layout.addWidget(self.layer)

        # Annotation list dock
        self.annotation_list = AnnotationList(self.layer, parent=self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.annotation_list)

        # Connections
        self.layer.messageSignal.connect(self.update_status)
        self.layer.annotationAdded.connect(self.on_annotation_added)
        self.layer.annotationUpdated.connect(self.on_annotation_updated)
        self.layer.layerSignal.connect(self.add_layer)
        self.layer.annotationAdded.connect(self.update_annotation_list)
        self.layer.annotationUpdated.connect(self.update_annotation_list)

    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            self.image_paths = []
            folder_path = Path(folder_path)
            # use rglob to get all images in subfolders too
            for img_path in folder_path.rglob("*.*"):
                if img_path.suffix.lower() in [".jpg", ".jpeg", ".png", ".bmp"]:
                    self.image_paths.append(img_path)

            self.curr_image_idx = 0
        if len(self.image_paths) > 0:
            msg = f"Loaded {len(self.image_paths)} images from {folder_path}"
            logger.info(msg)
            self.update_status(msg)
            # unhide next, prev buttons
            self.next_image_btn.setVisible(True)
            self.prev_image_btn.setVisible(True)

    def show_next_image(self):
        """Show next image in the list. If at the end, show first image."""
        if self.curr_image_idx < len(self.image_paths) - 1:
            self.curr_image_idx += 1
        else:
            self.curr_image_idx = 0
        self.layer.set_image(self.image_paths[self.curr_image_idx])
        self.update_status(
            f"Showing image {self.curr_image_idx + 1}/{len(self.image_paths)}"
        )

    def show_prev_image(self):
        """Show previous image in the list. If at the start, show last image."""
        if self.curr_image_idx > 0:
            self.curr_image_idx -= 1
        else:
            self.curr_image_idx = len(self.image_paths) - 1
        self.layer.set_image(self.image_paths[self.curr_image_idx])
        self.update_status(
            f"Showing image {self.curr_image_idx + 1}/{len(self.image_paths)}"
        )

    def init_baker_ui(self):
        """Initialize the Baker tab UI."""
        # Canvas setup
        self.canvas = Canvas(parent=self)
        self.layer_settings = LayerSettings(parent=self)
        self.layer_list = LayerList(
            canvas=self.canvas, parent=self, layer_settings=self.layer_settings
        )
        self.layer_settings.setVisible(False)

        # Create tab and main layout
        baker_tab = QWidget()
        self.tab_widget.addTab(baker_tab, "Baker")
        main_layout = QVBoxLayout(baker_tab)

        # Create Baker-specific toolbar
        self.baker_toolbar = QWidget()
        baker_toolbar_layout = QHBoxLayout(self.baker_toolbar)

        # Add Baker tools
        baker_modes = [
            ("Export Current State", self.export_current_state),
            ("Save State", lambda: self.update_status("Save State comming soon...")),
        ]

        for text, callback in baker_modes:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            baker_toolbar_layout.addWidget(btn)

        # Add spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        baker_toolbar_layout.addWidget(spacer)

        self.addDockWidget(Qt.RightDockWidgetArea, self.layer_list)
        self.addDockWidget(Qt.RightDockWidgetArea, self.layer_settings)

        # Load initial layers (example - modify with your actual layer loading logic)

        main_layout.addWidget(self.canvas)

        self.canvas.layerRemoved.connect(self.canvas.clear_layers)
        self.canvas.layerSelected.connect(self.layer_list.select_layer)
        self.canvas.layersChanged.connect(self.layer_list.update_list)
        self.layer_settings.messageSignal.connect(self.update_status)
        self.layer_settings.layerState.connect(self.canvas.bake_settings)

    def handle_model_change(self, index):
        model_name = self.model_combo.currentText()
        self.current_model = self.all_models[model_name]
        msg = f"Model changed to {model_name}"
        logger.info(msg)
        self.update_status(msg)

    def handle_tab_change(self, index):
        """Control annotation panel visibility based on tab"""
        if self.annotation_list:
            current_tab = self.tab_widget.tabText(index)

            if current_tab == "Layerify":
                # Show Layerify tools and components
                self.tools_dock.setWindowTitle("Annotation Tools")
                self.tools_dock.setWidget(self.layerify_toolbar)
                self.annotation_list.setVisible(True)
                self.layer_settings.setVisible(False)
                # show layers too
                self.layer_list.setVisible(True)
            else:
                # Show Baker tools and components
                self.tools_dock.setWindowTitle("Baking Tools")
                self.tools_dock.setWidget(self.baker_toolbar)
                self.annotation_list.setVisible(False)
                self.layer_list.setVisible(True)
                self.layer_settings.setVisible(True)

            # Always keep the tools dock visible
            self.tools_dock.setVisible(True)
        else:
            logger.warning("Annotation list not found!")

    def handle_predict(self):
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
            self.update_status("No annotations to predict passing image to model")
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
            label_hints.append([1])
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
                        filepath=self.layer.file_path,
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

    def handle_model_error(self, error):
        logger.error(f"Model error: {error}")
        QMessageBox.critical(self, "Error", f"Model error: {error}")

    def save_annotations(self):
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
        self.annotation_list.update_list()

    def choose_color(self):
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

    def clear_annotations(self):
        self.layer.annotations.clear()
        self.layer.selected_annotation = None
        self.layer.update()
        self.annotation_list.update_list()

        self.canvas.layers.clear()
        self.canvas.selected_layer = None
        self.canvas.update()
        self.layer_list.layers.clear()
        self.layer_list.update_list()

        logger.info("Annotations cleared")
        self.update_status("Annotations cleared")

    def update_status(self, msg):
        """Update status bar that's visible in all tabs"""
        # if current tab is layerify
        if self.tab_widget.currentIndex() == 0:
            status_text = f"{msg} | Label: {self.current_label} | Model: {self.current_model.name} | Mode: {self.layer.mode.name} | Annotations: {len(self.layer.annotations)} | Layers: {len(self.canvas.layers)}"
        elif self.tab_widget.currentIndex() == 1:
            status_text = f"{msg} | Num Layers: {len(self.canvas.layers)}"
        self.status_bar.showMessage(status_text)

    def on_annotation_added(self, annotation: Annotation):
        if annotation.label not in self.config.predefined_labels:

            self.config.predefined_labels.append(
                Label(annotation.label, annotation.color)
            )
            self.update_label_combo()
        logger.info(f"Added annotation: {annotation.label}")
        self.update_status(f"Added annotation: {annotation.label}")

    def load_default_image(self):
        default_path = self.config.assets_folder / "desk.png"
        if not default_path.exists():
            default_path, _ = QFileDialog.getOpenFileName()
            default_path = Path(default_path)

        if default_path.exists():
            self.layer.set_image(default_path)

    def handle_label_change(self, index):
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
        self.update_status(msg)

    def on_annotation_updated(self, annotation):
        logger.info(f"Updated annotation: {annotation.label}")
        self.update_status(f"Updated annotation: {annotation.label}")

    def update_label_combo(self):
        self.label_combo.clear()
        for label in self.config.predefined_labels:
            pixmap = QPixmap(16, 16)
            pixmap.fill(label.color)
            self.label_combo.addItem(QIcon(pixmap), label.name)

    def add_layer(self, layer):
        # this layer i.e. canvas will have only one annotation
        logger.info(f"Layer added: {layer.annotations[0].label}")
        self.layer_list.add_layer(layer)

        self.layer.update()
        self.canvas.update()

    def layerify_all(self):
        if len(self.layer.annotations) == 0:
            logger.warning("No annotations to layerify")
            self.update_status("No annotations to layerify")

            return
        logger.info("Layerifying all annotations")

        # else appends already added too
        self.layer.layerify_annotation(self.layer.annotations)

    def export_current_state(self):
        self.update_status("Exporting baked image")
        self.canvas.export_current_state()

    def load_baked_state(self):
        self.update_status("Loading baked image")
        self.update_status("Loading baked state comming soon...")


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
