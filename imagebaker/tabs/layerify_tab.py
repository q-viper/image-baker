from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig, LayerConfig
from imagebaker.core.defs import Annotation, MouseMode
from imagebaker.layers.annotable_layer import AnnotableLayer
from imagebaker.list_views import AnnotationList
from imagebaker.list_views.image_list import ImageListPanel
from imagebaker.tabs.layerify_annotations_io import (
    ImageEntry,
    LayerifyAnnotationsIoMixin,
)
from imagebaker.tabs.layerify_inference_actions import LayerifyInferenceActionsMixin
from imagebaker.tabs.layerify_labels import LayerifyLabelsMixin

__all__ = ["ImageEntry", "LayerifyTab"]


class LayerifyTab(
    LayerifyAnnotationsIoMixin,
    LayerifyLabelsMixin,
    LayerifyInferenceActionsMixin,
    QWidget,
):
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

        self.all_models = loaded_models or {}
        self.current_model = (
            list(self.all_models.values())[0] if self.all_models else None
        )
        self.config.load_labels_from_cache()
        self.current_label = self.config.default_label.name
        self.image_entries = []
        self.curr_image_idx = 0
        self.processed_images = set()
        self.mode_buttons = {}
        self.annotable_layers: deque[AnnotableLayer] = deque(
            maxlen=self.config.deque_maxlen
        )
        self.baked_results: deque[AnnotableLayer] = deque(
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
            layer.annotationRemoved.connect(self.on_annotation_removed)
            layer.modeChanged.connect(lambda _mode, self=self: self.sync_mode_buttons())
            layer.brushSizeChanged.connect(self._sync_brush_size_ui)
            layer.messageSignal.connect(self.messageSignal)
            layer.layerSignal.connect(self.add_layer)
            layer.labelUpdated.connect(self.on_label_update)

        # Connect image list panel signals
        self.image_list_panel.imageSelected.connect(self.on_image_selected)
        self.image_list_panel.imageRemoved.connect(self.remove_image_entry)
        self.image_list_panel.activeImageEntries.connect(self.update_active_entries)

        # Connect annotation list bottom action buttons
        self.annotation_list.layerifySelectedRequested.connect(self.layerify_selected)
        self.annotation_list.layerifyAllRequested.connect(self.layerify_all)
        self.annotation_list.saveRequested.connect(self.save_annotations)
        self.annotation_list.loadRequested.connect(self.load_annotations)
        self.annotation_list.clearRequested.connect(self.clear_annotations)

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
            self.layer.current_label = self.current_label
            self.layer.current_color = self._label_color(self.current_label)
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

    def create_toolbar(self):
        """Create Layerify-specific toolbar organized in two compact, flexible rows."""
        self.toolbar = QWidget()
        main_toolbar_layout = QVBoxLayout(self.toolbar)
        main_toolbar_layout.setContentsMargins(6, 4, 6, 4)
        main_toolbar_layout.setSpacing(4)

        # ----------------- Row 1: Dataset, Labels & AI Predict -----------------
        row1 = QWidget()
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(6)

        # Folder selection
        self.select_folder_btn = QPushButton("📁 Folder")
        self.select_folder_btn.setToolTip("Select folder of images to annotate")
        self.select_folder_btn.clicked.connect(self.select_folder)
        row1_layout.addWidget(self.select_folder_btn)

        # Label controls
        self.label_combo = QComboBox()
        self.label_combo.setToolTip("Select active annotation label")
        for label in self.config.predefined_labels:
            pixmap = QPixmap(14, 14)
            pixmap.fill(label.color)
            self.label_combo.addItem(QIcon(pixmap), label.name)
        self.label_combo.currentIndexChanged.connect(self.handle_label_change)
        row1_layout.addWidget(self.label_combo)

        self.color_btn = QPushButton("🎨")
        self.color_btn.setToolTip("Change color of active label")
        if self.config.predefined_labels:
            c_pix = QPixmap(14, 14)
            c_pix.fill(self.config.predefined_labels[0].color)
            self.color_btn.setIcon(QIcon(c_pix))
        self.color_btn.clicked.connect(self.choose_color)
        row1_layout.addWidget(self.color_btn)

        self.manage_label_btn = QPushButton("⚙️ Labels")
        self.manage_label_btn.setToolTip("Manage, recolor, or delete labels")
        self.manage_label_btn.clicked.connect(self.open_label_manager)
        row1_layout.addWidget(self.manage_label_btn)

        sep1 = QLabel("|")
        sep1.setStyleSheet("color: #718096;")
        row1_layout.addWidget(sep1)

        # Model & Prediction with text prompt
        model_tag = QLabel("Model:")
        model_tag.setStyleSheet("font-weight: bold;")
        row1_layout.addWidget(model_tag)

        self.model_combo = QComboBox()
        for model_name in self.all_models.keys():
            self.model_combo.addItem(model_name)
        self.model_combo.currentIndexChanged.connect(self.handle_model_change)
        row1_layout.addWidget(self.model_combo)

        self.predict_prompt_input = QLineEdit()
        self.predict_prompt_input.setPlaceholderText("Text prompt (optional)...")
        self.predict_prompt_input.setToolTip("Text prompt for open-vocabulary / prompt-guided models (e.g. dog, car)")
        self.predict_prompt_input.setMinimumWidth(110)
        self.predict_prompt_input.setMaximumWidth(180)
        row1_layout.addWidget(self.predict_prompt_input)

        predict_btn = QPushButton("🔮 Predict")
        predict_btn.setStyleSheet("font-weight: bold;")
        predict_btn.setToolTip("Run model prediction on current image with prompt")
        predict_btn.clicked.connect(self.handle_predict)
        row1_layout.addWidget(predict_btn)

        row1_spacer = QWidget()
        row1_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row1_layout.addWidget(row1_spacer)

        main_toolbar_layout.addWidget(row1)

        # ----------------- Row 2: Modes & Canvas View -----------------
        row2 = QWidget()
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(6)

        mode_tag = QLabel("Tools:")
        mode_tag.setStyleSheet("font-weight: bold;")
        row2_layout.addWidget(mode_tag)

        modes = [
            ("↖", "Select", MouseMode.IDLE, "Select, move, or resize regions (V or Esc)"),
            ("🔳", "Rectangle", MouseMode.RECTANGLE, "Draw rectangle region (E)"),
            ("🔷", "Polygon", MouseMode.POLYGON, "Draw polygon region (W)"),
            ("📍", "Point", MouseMode.POINT, "Add point region (Q)"),
            ("🖌️", "Brush", MouseMode.DRAW, "Brush segmentation mask (B)"),
        ]

        for icon, text, mode, tip in modes:
            btn_txt = f"{icon} {text}"
            btn = QPushButton(btn_txt)
            btn.setToolTip(tip)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton:checked {"
                " background-color: #2f80ed;"
                " color: white;"
                " border: 2px solid #1456b8;"
                " font-weight: bold;"
                "}"
            )
            btn.clicked.connect(lambda _, m=mode: self.set_annotation_mode(m))
            self.mode_buttons[mode] = btn
            row2_layout.addWidget(btn)

        # Brush sub-controls (Paint / Erase / +New Instance / Size) shown in Brush mode
        self.brush_controls_widget = QWidget()
        brush_layout = QHBoxLayout(self.brush_controls_widget)
        brush_layout.setContentsMargins(6, 0, 0, 0)
        brush_layout.setSpacing(4)

        brush_btn_style = (
            "QPushButton:checked {"
            " background-color: #2f80ed;"
            " color: white;"
            " border: 2px solid #1456b8;"
            " font-weight: bold;"
            "}"
        )
        self.brush_paint_btn = QPushButton("Paint")
        self.brush_paint_btn.setCheckable(True)
        self.brush_paint_btn.setStyleSheet(brush_btn_style)
        self.brush_paint_btn.setToolTip(
            "Paint onto selected brush instance (paints across occluders as 1 object)"
        )
        self.brush_paint_btn.clicked.connect(
            lambda: self.set_annotation_mode(MouseMode.DRAW)
        )
        brush_layout.addWidget(self.brush_paint_btn)

        self.brush_erase_btn = QPushButton("Erase")
        self.brush_erase_btn.setCheckable(True)
        self.brush_erase_btn.setStyleSheet(brush_btn_style)
        self.brush_erase_btn.setToolTip(
            "Erase from selected/clicked brush mask (or hold Alt while dragging)"
        )
        self.brush_erase_btn.clicked.connect(
            lambda: self.set_annotation_mode(MouseMode.ERASE)
        )
        brush_layout.addWidget(self.brush_erase_btn)

        self.brush_new_btn = QPushButton("+ New")
        self.brush_new_btn.setToolTip(
            "Deselect current brush mask to start a separate instance"
        )
        self.brush_new_btn.clicked.connect(self.start_new_brush_annotation)
        brush_layout.addWidget(self.brush_new_btn)

        size_lbl = QLabel("Size:")
        brush_layout.addWidget(size_lbl)
        self.brush_size_slider = QSlider(Qt.Horizontal)
        self.brush_size_slider.setRange(2, 120)
        initial_bs = int(getattr(self.layer, "brush_size", 18) or 18) if self.layer else 18
        self.brush_size_slider.setValue(initial_bs)
        self.brush_size_slider.setFixedWidth(90)
        self.brush_size_slider.setToolTip("Brush / Eraser size (or Mouse Wheel in Brush mode)")
        self.brush_size_slider.valueChanged.connect(self.on_brush_size_changed)
        brush_layout.addWidget(self.brush_size_slider)

        self.brush_size_value_label = QLabel(f"{initial_bs}px")
        self.brush_size_value_label.setMinimumWidth(34)
        brush_layout.addWidget(self.brush_size_value_label)

        row2_layout.addWidget(self.brush_controls_widget)
        self.brush_controls_widget.setVisible(False)

        row2_spacer = QWidget()
        row2_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row2_layout.addWidget(row2_spacer)

        self.grid_btn = QPushButton("Grid")
        self.grid_btn.setCheckable(True)
        self.grid_btn.setChecked(self.config.show_gridlines)
        self.grid_btn.clicked.connect(self.toggle_gridlines)
        row2_layout.addWidget(self.grid_btn)

        self.theme_btn = QPushButton("Theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        row2_layout.addWidget(self.theme_btn)

        main_toolbar_layout.addWidget(row2)
        self.sync_mode_buttons()

    def __del__(self):
        logger.warning(f"Tab {id(self)} deleted")
