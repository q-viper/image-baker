from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSizePolicy,
    QDockWidget,
    QSlider,
)

from imagebaker.core.defs import LayerState
from imagebaker.tab_views import Layer
from imagebaker import logger


class LayerSettings(QDockWidget):
    layerState = Signal(LayerState)
    messageSignal = Signal(str)

    def __init__(self, parent=None, layer_list=None):
        super().__init__("Layer Settings", parent)
        self.selected_layer: Layer = None
        self.layer_list = layer_list
        self.init_ui()
        self.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self._disable_updates = False
        self.last_updated_time = 0
        self.update_sliders()

    def init_ui(self):
        logger.info("Initializing LayerSettings")
        self.widget = QWidget()
        self.setWidget(self.widget)
        self.main_layout = QVBoxLayout(self.widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)  # Add some padding
        self.main_layout.setSpacing(10)

        # Layer name label
        self.layer_name_label = QLabel("No Layer Selected")
        self.layer_name_label.setAlignment(Qt.AlignCenter)
        self.layer_name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.main_layout.addWidget(self.layer_name_label)

        # Opacity slider
        self.opacity_slider = self.create_slider("Opacity:", 0, 255, 255)
        self.main_layout.addWidget(self.opacity_slider["widget"])
        self.x_slider = self.create_slider("X:", -1000, 10000, 0, 1)
        self.main_layout.addWidget(self.x_slider["widget"])
        self.y_slider = self.create_slider("Y:", -1000, 1000, 0, 1)
        self.main_layout.addWidget(self.y_slider["widget"])
        self.scale_x_slider = self.create_slider(
            "Scale X:", 1, 500, 100, 100
        )  # 1-500 becomes 0.01-5.0
        self.main_layout.addWidget(self.scale_x_slider["widget"])
        self.scale_y_slider = self.create_slider("Scale Y:", 1, 500, 100, 100)
        self.main_layout.addWidget(self.scale_y_slider["widget"])
        self.rotation_slider = self.create_slider("Rotation:", 0, 360, 0, 1)
        self.main_layout.addWidget(self.rotation_slider["widget"])

        # Bake button
        self.store_state_btn = QPushButton("Store States")
        self.store_state_btn.clicked.connect(self.emit_bake_settings)
        self.main_layout.addWidget(self.store_state_btn)

        # Add stretch to push content to the top
        self.main_layout.addStretch()

        # Ensure the dock widget resizes properly
        self.setMinimumWidth(250)  # Minimum width for usability
        self.widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def create_slider(self, label, min_val, max_val, default, scale_factor=1):
        """Create a slider with a label and value display."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove inner margins

        # Label
        lbl = QLabel(label)
        lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Slider
        slider = QSlider(Qt.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default)
        slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Value label
        value_lbl = QLabel(f"{default / scale_factor:.1f}")
        value_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Connect slider to value label (still updates during drag)
        slider.valueChanged.connect(
            lambda v: value_lbl.setText(f"{v / scale_factor:.1f}")
        )

        # Only update layer on slider release
        slider.sliderReleased.connect(self.on_slider_released)

        # Add widgets to layout
        layout.addWidget(lbl)
        layout.addWidget(slider)
        layout.addWidget(value_lbl)

        return {
            "widget": container,
            "slider": slider,
            "label": value_lbl,
            "scale_factor": scale_factor,
        }

    def on_slider_released(self):
        """Update layer only when slider is released"""
        if self._disable_updates or not self.selected_layer:
            return

        sender = self.sender()  # Get which slider was released
        value = sender.value()

        try:
            self._disable_updates = True

            if sender == self.x_slider["slider"]:
                self.selected_layer.position.setX(value / self.x_slider["scale_factor"])
            elif sender == self.y_slider["slider"]:
                self.selected_layer.position.setY(value / self.y_slider["scale_factor"])
            elif sender == self.scale_x_slider["slider"]:
                self.selected_layer.scale_x = value / 100.0
            elif sender == self.scale_y_slider["slider"]:
                self.selected_layer.scale_y = value / 100.0
            elif sender == self.rotation_slider["slider"]:
                self.selected_layer.rotation = value
            elif sender == self.opacity_slider["slider"]:
                self.selected_layer.opacity = (
                    value / self.opacity_slider["scale_factor"]
                )
                self.selected_layer.apply_opacity()

            self.selected_layer.update()
        finally:
            self._disable_updates = False

    def emit_bake_settings(self):
        """Emit the bake settings signal."""
        bake_settings = LayerState(
            layer_id=self.selected_layer.id,
            layer_order=self.selected_layer.order,
            layer_name=self.selected_layer.name,
            x_pos=self.selected_layer.position.x(),
            y_pos=self.selected_layer.position.y(),
            rotation=self.selected_layer.rotation,
            scale_x=self.selected_layer.scale_x,
            scale_y=self.selected_layer.scale_y,
        )
        logger.info(f"Storing state {bake_settings}")
        self.messageSignal.emit(f"Stored state for {bake_settings.layer_name}")
        self.LayerState.emit(bake_settings)

    def set_selected_layer(self, layer):
        """Set the currently selected layer."""
        self.selected_layer = layer
        self.update_sliders()

    def update_sliders(self):
        """Update slider values based on the selected layer."""
        self.widget.setEnabled(False)
        if self._disable_updates or not self.selected_layer:
            return

        try:
            self._disable_updates = True

            if self.selected_layer.selected:
                if self.selected_layer.config.allow_slider_usage:
                    self.widget.setEnabled(True)
                self.layer_name_label.setText(f"Layer: {self.selected_layer.name}")
                new_max_xpos = self.selected_layer.config.max_xpos
                new_max_ypos = self.selected_layer.config.max_ypos

                if new_max_xpos - abs(self.selected_layer.position.x()) < 50:
                    new_max_xpos = abs(self.selected_layer.position.x()) + 50
                if new_max_ypos - abs(self.selected_layer.position.y()) < 50:
                    new_max_ypos = abs(self.selected_layer.position.y()) + 50

                # Update slider ranges
                self.x_slider["slider"].setRange(
                    -new_max_xpos,
                    new_max_xpos,
                )
                self.y_slider["slider"].setRange(
                    -new_max_ypos,
                    new_max_ypos,
                )

                # Update slider values
                self.opacity_slider["slider"].setValue(int(self.selected_layer.opacity))
                self.x_slider["slider"].setValue(int(self.selected_layer.position.x()))
                self.y_slider["slider"].setValue(int(self.selected_layer.position.y()))
                self.scale_x_slider["slider"].setValue(
                    int(self.selected_layer.scale_x * 100)
                )
                self.scale_y_slider["slider"].setValue(
                    int(self.selected_layer.scale_y * 100)
                )
                self.rotation_slider["slider"].setValue(
                    int(self.selected_layer.rotation)
                )
            else:
                self.widget.setEnabled(False)
                self.layer_name_label.setText("No Layer")
        finally:
            self._disable_updates = False
