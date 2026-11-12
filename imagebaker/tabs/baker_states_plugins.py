from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from imagebaker import logger
from imagebaker.plugins.discovery import discover_plugin_classes
from imagebaker.utils.transform_mask import mask_to_polygons, mask_to_rectangles


class BakerStatesPluginsMixin:
    """Timeline states, export, geometry conversion, grouping, and plugin helpers for BakerTab."""

    def generate_state_previews(self):
        """Generate previews for each state."""
        # Clear existing previews
        for i in reversed(range(self.preview_layout.count())):
            widget = self.preview_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        # Generate a preview for each state
        for step, _states in sorted(self.current_canvas.states.items()):
            # Create a container widget for the preview
            preview_widget = QWidget()
            preview_layout = QVBoxLayout(preview_widget)
            preview_layout.setContentsMargins(0, 0, 0, 0)
            preview_layout.setSpacing(2)

            # Placeholder thumbnail
            placeholder = QPixmap(50, 50)
            placeholder.fill(Qt.gray)  # Gray placeholder
            thumbnail_label = QLabel()
            thumbnail_label.setPixmap(placeholder)
            thumbnail_label.setFixedSize(50, 50)  # Set a fixed size for the thumbnail
            thumbnail_label.setScaledContents(True)

            # Add the step number on top of the thumbnail
            step_label = QLabel(f"Step {step}")
            step_label.setAlignment(Qt.AlignCenter)
            step_label.setStyleSheet("font-weight: bold; font-size: 10px;")

            # Add a button to make the preview clickable
            preview_button = QPushButton()
            preview_button.setFixedSize(
                50, 70
            )  # Match the size of the thumbnail + step label
            preview_button.setStyleSheet("background: transparent; border: none;")
            preview_button.clicked.connect(lambda _, s=step: self.seek_state(s))

            # Add the thumbnail and step label to the layout
            preview_layout.addWidget(thumbnail_label)
            preview_layout.addWidget(step_label)

            # Add the preview widget to the button
            preview_button.setLayout(preview_layout)

            # Add the button to the preview panel
            self.preview_layout.addWidget(preview_button)

            # Update the thumbnail dynamically when it becomes available
            self.current_canvas.thumbnailsAvailable.connect(
                lambda step=step, label=thumbnail_label: self.update_thumbnail(
                    step, label
                )
            )

        # Refresh the preview panel
        self.preview_panel.update()

    def update_thumbnail(self, step, thumbnail_label):
        """Update the thumbnail for a specific step."""
        if step in self.current_canvas.state_thumbnail:
            thumbnail = self.current_canvas.state_thumbnail[step]
            thumbnail_label.setPixmap(thumbnail)
            thumbnail_label.update()

    def export_for_annotation(self):
        """Export the baked states for annotation."""
        self.messageSignal.emit("Exporting states for prediction...")
        self.requestTabSwitch.emit(0)
        self.current_canvas.export_baked_states(export_to_annotation_tab=True)

    def _select_export_format(
        self, title: str = "Select Annotation Format"
    ) -> str | None:
        items = [
            "default (ImageBaker JSON)",
            "coco (COCO JSON)",
            "yolo (YOLO TXT)",
        ]
        choice, ok = QInputDialog.getItem(
            self, title, "Annotation Format:", items, 0, False
        )
        if not ok or not choice:
            return None
        return choice.split()[0].strip().lower()

    def export_locally(self, annotation_format: str | None = None):
        """Export the baked states locally."""
        fmt = annotation_format
        if fmt is None and self.isVisible():
            fmt = self._select_export_format("Export Baked States Format")
            if fmt is None:
                return
        fmt = fmt or "default"
        self.messageSignal.emit(f"Exporting baked states ({fmt.upper()})...")
        self.current_canvas.export_baked_states(annotation_format=fmt)

    def play_saved_states(self):
        """Play or pause the saved states in sequence."""
        if not self.current_canvas:
            return

        if getattr(self.current_canvas, "is_playing", False):
            self.current_canvas.stop_playing()
            if hasattr(self, "play_btn"):
                self.play_btn.blockSignals(True)
                self.play_btn.setChecked(False)
                self.play_btn.setText("▶ Play States")
                self.play_btn.blockSignals(False)
            return

        # Update the slider range based on the number of states
        if self.current_canvas.states:
            num_states = len(self.current_canvas.states)
            self.timeline_slider.setMaximum(num_states - 1)
            self.steps_spinbox.setValue(
                num_states
            )  # Sync the spinbox with the number of states
            self.timeline_slider.setEnabled(True)
        else:
            self.timeline_slider.setMaximum(0)
            self.steps_spinbox.setValue(1)
            self.messageSignal.emit("No saved states available.")
            self.timeline_slider.setEnabled(False)
            if hasattr(self, "play_btn"):
                self.play_btn.blockSignals(True)
                self.play_btn.setChecked(False)
                self.play_btn.setText("▶ Play States")
                self.play_btn.blockSignals(False)
            return

        self.messageSignal.emit("Playing saved state...")
        if hasattr(self, "play_btn"):
            self.play_btn.blockSignals(True)
            self.play_btn.setChecked(True)
            self.play_btn.setText("⏸ Pause")
            self.play_btn.blockSignals(False)

        self.timeline_slider.update()
        # Start playing the states
        self.current_canvas.play_states()

        if hasattr(self, "play_btn"):
            self.play_btn.blockSignals(True)
            self.play_btn.setChecked(False)
            self.play_btn.setText("▶ Play States")
            self.play_btn.blockSignals(False)

    def save_current_state(self, prompt_download: bool = True):
        """Save the current state of the canvas and optionally prompt to download/export."""
        self.messageSignal.emit("Saving current state...")
        logger.info(f"Saving current state for {self.steps_spinbox.value()}...")

        self.current_canvas.save_current_state(steps=self.steps_spinbox.value())

        self._reset_steps_input()

        total_states = len(self.current_canvas.states)
        if total_states > 0:
            self.timeline_slider.setMaximum(total_states - 1)
            self.timeline_slider.setEnabled(True)
            self.timeline_slider.setValue(
                self.current_canvas._state_step_index(self.current_canvas.current_step)
            )
        else:
            self.timeline_slider.setMaximum(0)
            self.timeline_slider.setEnabled(False)
        self.timeline_slider.update()
        self._update_timeline_step_label()
        self.save_canvas_to_cache()

        if prompt_download and self.isVisible() and total_states > 0:
            reply = QMessageBox.question(
                self,
                "Download / Export Saved States",
                "State saved! Do you want to download/export the baked states and annotations now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                fmt = self._select_export_format("Select Download Annotation Format")
                if fmt:
                    self.export_locally(annotation_format=fmt)

    def _reset_steps_input(self):
        """Reset steps control back to 1 after saving a state."""
        self.steps_spinbox.setValue(1)
        self.steps_spinbox.update()

    def clear_states(self):
        """Clear all saved states and disable the timeline slider."""
        self.messageSignal.emit("Clearing all saved states...")
        if self.current_canvas:
            self.current_canvas.stop_playing()
            self.current_canvas.previous_state = None
            self.current_canvas.current_step = 0
            self.current_canvas.states.clear()  # Clear all saved states
        if hasattr(self, "play_btn"):
            self.play_btn.blockSignals(True)
            self.play_btn.setChecked(False)
            self.play_btn.setText("▶ Play States")
            self.play_btn.blockSignals(False)
        self.timeline_slider.setEnabled(False)  # Disable the slider
        self.timeline_slider.setMaximum(0)  # Reset the slider range
        self.timeline_slider.setValue(0)  # Reset the slider position
        self.messageSignal.emit("All states cleared.")
        self.steps_spinbox.setValue(1)  # Reset the spinbox value

        self.steps_spinbox.update()
        self.timeline_slider.update()
        self._update_timeline_step_label()
        self.current_canvas.update()
        self.save_canvas_to_cache()

    def randomize_states(self):
        """Randomize states for the current canvas."""
        if not self.current_canvas or not self.current_canvas.layers:
            self.messageSignal.emit("No layers available to randomize.")
            return

        num_states = max(1, self.steps_spinbox.value())
        self.current_canvas.randomize_states(num_states=num_states)
        self.timeline_slider.setMaximum(num_states - 1)
        self.timeline_slider.setEnabled(True)
        self.timeline_slider.setValue(0)
        self._update_timeline_step_label()
        self.update_list()
        self.save_canvas_to_cache()
        self.messageSignal.emit(f"Created {num_states} randomized state(s).")

    def convert_selected_annotation_type(self):
        """
        Convert annotation type for selected layers.
        rectangle -> polygon, polygon -> rectangle
        """
        if not self.current_canvas or not self.current_canvas.layers:
            self.messageSignal.emit("No layers available.")
            return

        target_layers = [layer for layer in self.current_canvas.layers if layer.selected]
        if not target_layers:
            self.messageSignal.emit("Select one or more layers to convert annotation type.")
            return

        converted = 0
        skipped = 0

        for layer in target_layers:
            if not layer.annotations:
                skipped += 1
                continue

            ann = layer.annotations[0]
            if ann.polygon is not None and len(ann.polygon) >= 3:
                rect = ann.polygon.boundingRect()
                ann.rectangle = rect
                ann.polygon = None
                ann.points = []
                ann.mask = None
                converted += 1
            elif ann.rectangle is not None:
                rect = ann.rectangle
                ann.polygon = QPolygonF(
                    [
                        rect.topLeft(),
                        rect.topRight(),
                        rect.bottomRight(),
                        rect.bottomLeft(),
                    ]
                )
                ann.rectangle = None
                ann.points = []
                ann.mask = None
                converted += 1
            elif ann.mask is not None and np.any(ann.mask):
                polys = mask_to_polygons(
                    ann.mask, min_polygon_area=2, merge_polygons=False
                )
                if len(polys) == 1:
                    ann.polygon = QPolygonF([QPointF(p[0], p[1]) for p in polys[0]])
                    ann.rectangle = None
                    ann.mask = None
                    ann.points = []
                    converted += 1
                else:
                    rects = mask_to_rectangles(ann.mask, merge_rectangles=True)
                    if rects:
                        rx, ry, rw, rh = rects[0]
                        ann.rectangle = QRectF(rx, ry, rw, rh)
                        ann.polygon = None
                        ann.mask = None
                        ann.points = []
                        converted += 1
                    else:
                        skipped += 1
            else:
                skipped += 1

            layer._apply_edge_opacity()
            layer.update()

        self.current_canvas.update()
        self.layer_list.update_list()
        self.layer_settings.update_sliders()
        self.messageSignal.emit(
            f"Converted {converted} annotation(s). Skipped {skipped} layer(s)."
        )

    def seek_state(self, step):
        """Seek to a specific state using the timeline slider."""
        self.messageSignal.emit(f"Seeking to step {step}")
        logger.info(f"Seeking to step {step}")
        self.current_canvas.seek_state(step)
        self._update_timeline_step_label()

        # Update the canvas
        self.current_canvas.update()

    def export_current_state(self, annotation_format: str | None = None):
        """Export the current state as an image and annotations."""
        fmt = annotation_format
        if fmt is None and self.isVisible():
            fmt = self._select_export_format("Export Current State Format")
            if fmt is None:
                return
        fmt = fmt or "default"
        self.messageSignal.emit(f"Exporting current state ({fmt.upper()})...")
        self.current_canvas.export_current_state(annotation_format=fmt)

    def predict_state(self):
        """Pass the current state to predict."""
        self.messageSignal.emit("Predicting state...")

        self.current_canvas.predict_state()

    def group_layers(self):
        """Group exactly two selected layers on the current canvas."""
        if self.current_canvas is None:
            return
        grouped = self.current_canvas.group_selected_layers()
        if grouped:
            self.layer_list.update_list()
            self.layer_settings.selected_layer = self.current_canvas.selected_layer
            self.layer_settings.update_sliders()

    def ungroup_layers(self):
        """Ungroup selected grouped layer back into individual layers."""
        if self.current_canvas is None:
            return
        selected = [layer for layer in self.current_canvas.layers if layer.selected]
        if len(selected) != 1:
            self.messageSignal.emit("Select a single grouped layer to ungroup.")
            return
        if self.current_canvas._ungroup_layer(selected[0]):
            self.layer_list.update_list()
            self.layer_settings.selected_layer = self.current_canvas.selected_layer
            self.layer_settings.update_sliders()

    def undo_canvas(self):
        """Undo the last Baker canvas action."""
        if self.current_canvas is not None and self.current_canvas.undo():
            self.update_list()
            self._update_timeline_step_label()

    def redo_canvas(self):
        """Redo the previously undone Baker canvas action."""
        if self.current_canvas is not None and self.current_canvas.redo():
            self.update_list()
            self._update_timeline_step_label()

    def _update_timeline_step_label(self):
        """Keep the timeline step badge synced with canvas states."""
        label = getattr(self, "timeline_step_label", None)
        if label is None:
            return
        if self.current_canvas is None or not self.current_canvas.states:
            label.setText("0 / 0")
            return
        total = len(self.current_canvas.states)
        idx = getattr(self.current_canvas, "_current_step_index", 0) + 1
        label.setText(f"{idx} / {total}")

    def _update_plugin_button_badge(self):
        btn = getattr(self, "plugin_dropdown_btn", None)
        if btn is None:
            return
        active_count = sum(1 for item in self.plugin_actions.values() if item.isChecked())
        btn.setText(f"🧩 Plugins ({active_count})" if active_count > 0 else "🧩 Plugins ▾")

    def reload_plugins(self):
        """Reload discoverable plugins from project root."""
        self.plugin_registry = discover_plugin_classes(Path.cwd())
        self.plugin_actions.clear()
        self.plugin_menu.clear()

        reload_action = QAction("🔄 Reload Plugins", self.plugin_menu)
        reload_action.triggered.connect(self.reload_plugins)
        self.plugin_menu.addAction(reload_action)
        self.plugin_menu.addSeparator()

        if not self.plugin_registry:
            placeholder = QAction("No plugins discovered", self.plugin_menu)
            placeholder.setEnabled(False)
            self.plugin_menu.addAction(placeholder)
            self.messageSignal.emit("No plugins discovered in project root.")
            self._update_plugin_button_badge()
            return

        for plugin_name in sorted(self.plugin_registry):
            checkbox = QCheckBox(plugin_name, self.plugin_menu)
            checkbox.setStyleSheet("padding: 4px 10px;")
            checkbox.toggled.connect(self.on_plugin_selection_changed)
            widget_action = QWidgetAction(self.plugin_menu)
            widget_action.setDefaultWidget(checkbox)
            self.plugin_menu.addAction(widget_action)
            self.plugin_actions[plugin_name] = checkbox

        self.plugin_menu.addSeparator()
        clear_action = QAction("✖ Clear Plugin Selection", self.plugin_menu)
        clear_action.triggered.connect(self.clear_plugin_selection)
        self.plugin_menu.addAction(clear_action)

        self.messageSignal.emit(
            f"Discovered {len(self.plugin_registry)} plugin option(s)."
        )
        self.sync_plugin_menu_with_selection()

    def clear_plugin_selection(self):
        """Clear all plugins from selected layers (or all layers if none selected)."""
        self._updating_plugin_menu = True
        try:
            for item in self.plugin_actions.values():
                item.setChecked(False)
        finally:
            self._updating_plugin_menu = False
        self.apply_plugin_selection()

    def _selected_plugin_classes(self):
        selected = []
        for plugin_name, item in self.plugin_actions.items():
            if item.isChecked() and plugin_name in self.plugin_registry:
                selected.append(self.plugin_registry[plugin_name])
        return selected

    def on_plugin_selection_changed(self, _checked: bool):
        if self._updating_plugin_menu:
            return
        self.apply_plugin_selection()

    def apply_plugin_selection(self):
        """Apply currently checked plugin options to selected layers."""
        if self.current_canvas is None:
            return

        plugin_classes = self._selected_plugin_classes()
        selected_layers = [layer for layer in self.current_canvas.layers if layer.selected]
        if selected_layers:
            self.current_canvas.set_plugins_for_layers(selected_layers, plugin_classes)
        else:
            if not self.current_canvas.layers:
                self._update_plugin_button_badge()
                return
            self.current_canvas.set_plugins_for_layers(
                list(self.current_canvas.layers), plugin_classes
            )
            self.messageSignal.emit(
                "No layer selected. Applied plugin options to all layers."
            )
        self.current_canvas.update()
        self.layer_list.update_list()
        self.layer_settings.update_sliders()
        self._update_plugin_button_badge()
        if not getattr(self, "_restoring_cache", False):
            self.save_canvas_to_cache()

    def sync_plugin_menu_with_selection(self, selected_layers=None):
        """Sync dropdown checks from selected layers' current plugin set."""
        if self.current_canvas is None or not self.plugin_actions:
            self._update_plugin_button_badge()
            return

        if selected_layers is None:
            selected_layers = [
                layer for layer in self.current_canvas.layers if layer.selected
            ]

        if not selected_layers:
            intersection = set()
        else:
            intersection = None
            for layer in selected_layers:
                layer_types = {
                    type(plugin)
                    for plugin in getattr(layer, "plugins", [])
                    if getattr(plugin, "enabled", True)
                }
                if intersection is None:
                    intersection = set(layer_types)
                else:
                    intersection &= layer_types
            intersection = intersection or set()

        self._updating_plugin_menu = True
        try:
            for plugin_name, item in self.plugin_actions.items():
                plugin_class = self.plugin_registry.get(plugin_name)
                item.setChecked(plugin_class in intersection)
        finally:
            self._updating_plugin_menu = False
        self._update_plugin_button_badge()
