import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, QThread
from PySide6.QtGui import QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMessageBox,
    QProgressDialog,
)

from imagebaker import logger
from imagebaker.core.defs import (
    Annotation,
    BakingResult,
    MouseMode,
    PredictionResult,
)
from imagebaker.tabs.layerify_annotations_io import ImageEntry
from imagebaker.utils import mask_to_polygons
from imagebaker.utils.image import qpixmap_to_numpy
from imagebaker.workers import ModelPredictionWorker


class LayerifyInferenceActionsMixin:
    """Annotation events, brush/mode controls, AI inference, layerify, and shortcuts for LayerifyTab."""

    def clear_annotations(self):
        """Safely clear all annotations"""
        try:
            # Clear layer annotations
            self.clearAnnotations.emit()
            self.messageSignal.emit("Annotations cleared")
            # clear cache annotation of layer
            annotation_path = (
                self._cache_path_for_file(self.layer.file_path)
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
        skip_label_registry = getattr(annotation, "_skip_label_registry", False)
        if hasattr(annotation, "_skip_label_registry"):
            delattr(annotation, "_skip_label_registry")

        if not skip_label_registry and self.ensure_label_available(
            annotation.label, annotation.color
        ):
            logger.info(f"Label {annotation.label} created.")
            self.update_label_combo()

        annotation.color = self._label_color(annotation.label)
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
        annotation.color = self._label_color(annotation.label)
        self.messageSignal.emit(f"Updated annotation: {annotation.label}")

        # Refresh the annotation list
        self.annotation_list.update_list()
        self.sync_label_combo_to_selection()
        self.save_layer_annotations(self.layer)

    def on_annotation_removed(self):
        """Handle annotation removed event and persist the current layer state."""
        self.messageSignal.emit("Annotation removed")
        self.save_layer_annotations(self.layer)
        self.annotation_list.update_list()

    def set_annotation_mode(self, mode: MouseMode):
        if self.layer:
            self.layer.set_mode(mode)
        self.sync_mode_buttons()

    def sync_mode_buttons(self):
        if not self.mode_buttons or not self.layer:
            return

        current_mode = self.layer.mouse_mode
        for mode, button in self.mode_buttons.items():
            if mode == MouseMode.DRAW:
                button.setChecked(current_mode in (MouseMode.DRAW, MouseMode.ERASE))
            else:
                button.setChecked(mode == current_mode)
        if hasattr(self, "brush_paint_btn"):
            self.brush_paint_btn.setChecked(current_mode == MouseMode.DRAW)
        if hasattr(self, "brush_erase_btn"):
            self.brush_erase_btn.setChecked(current_mode == MouseMode.ERASE)
        if hasattr(self, "brush_controls_widget"):
            self.brush_controls_widget.setVisible(
                current_mode in (MouseMode.DRAW, MouseMode.ERASE)
            )

    def start_new_brush_annotation(self):
        """Deselect current brush mask so next strokes create a separate instance."""
        if not self.layer:
            return
        changed = False
        for ann in self.layer.annotations:
            if ann.selected:
                ann.selected = False
                changed = True
                self.layer.annotationUpdated.emit(ann)
        self.layer.selected_annotation = None
        self.set_annotation_mode(MouseMode.DRAW)
        if changed:
            self.annotation_list.update_list()
        self.layer.update()
        self.messageSignal.emit("Ready to paint a new brush instance.")

    def on_brush_size_changed(self, size_val: int):
        """Apply slider brush size to all annotable layers."""
        clamped = max(2, min(120, int(size_val)))
        for lyr in self.annotable_layers:
            lyr.brush_size = clamped
            if lyr.mouse_mode in (MouseMode.DRAW, MouseMode.ERASE):
                lyr.update_cursor()
        if hasattr(self, "brush_size_value_label"):
            self.brush_size_value_label.setText(f"{clamped}px")

    def _sync_brush_size_ui(self, size_val: int):
        clamped = max(2, min(120, int(size_val)))
        if hasattr(self, "brush_size_slider"):
            with QSignalBlocker(self.brush_size_slider):
                self.brush_size_slider.setValue(clamped)
        if hasattr(self, "brush_size_value_label"):
            self.brush_size_value_label.setText(f"{clamped}px")

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
        # get annotations from canvas: prioritize user-selected annotations if any
        selected_anns = [
            ann
            for ann in self.layer.annotations
            if ann.selected and ann.visible
        ]
        if selected_anns:
            annotations = selected_anns
        else:
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
        prompt_text = (
            self.predict_prompt_input.text().strip()
            if hasattr(self, "predict_prompt_input") and self.predict_prompt_input.text().strip()
            else None
        )
        self.worker_thread = QThread()
        self.worker = ModelPredictionWorker(
            self.current_model,
            image,
            points,
            polygons,
            rectangles,
            label_hints,
            prompt=prompt_text,
            text_prompt=prompt_text,
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
        if predictions and self.layer:
            self.layer._push_undo_state()

        selected_label = (self.current_label or "").strip() or "Undefined"
        if self.ensure_label_available(selected_label):
            self.update_label_combo()
        prediction_color = self._label_color(selected_label)

        # update canvas with predictions: prioritize instance segmentation (polygon/mask) over pure bbox
        for prediction in predictions:
            rect = None
            if prediction.rectangle and len(prediction.rectangle) == 4:
                rect = QRectF(
                    float(prediction.rectangle[0]),
                    float(prediction.rectangle[1]),
                    float(prediction.rectangle[2]),
                    float(prediction.rectangle[3]),
                )

            if prediction.polygon is not None and len(prediction.polygon) >= 3:
                self.layer.annotations.append(
                    Annotation(
                        annotation_id=len(self.layer.annotations),
                        label=selected_label,
                        color=prediction_color,
                        polygon=QPolygonF([QPointF(float(p[0]), float(p[1])) for p in prediction.polygon]),
                        rectangle=rect,
                        mask=prediction.mask,
                        is_complete=True,
                        score=prediction.score,
                        annotator=self.current_model.name,
                        annotation_time=str(
                            prediction.annotation_time
                            if prediction.annotation_time
                            else ""
                        ),
                        file_path=self.layer.file_path,
                        is_model_generated=True,
                        model_name=self.current_model.name,
                    )
                )
            elif prediction.mask is not None:
                mask_arr = np.asarray(prediction.mask)
                bin_mask = (mask_arr > 0).astype(np.uint8)
                polys = mask_to_polygons(bin_mask * 255, merge_polygons=True)
                poly = (
                    QPolygonF([QPointF(float(p[0]), float(p[1])) for p in polys[0]])
                    if polys and len(polys[0]) >= 3
                    else None
                )
                self.layer.annotations.append(
                    Annotation(
                        annotation_id=len(self.layer.annotations),
                        label=selected_label,
                        color=prediction_color,
                        polygon=poly,
                        rectangle=rect,
                        mask=bin_mask,
                        is_complete=True,
                        score=prediction.score,
                        annotator=self.current_model.name,
                        annotation_time=str(
                            prediction.annotation_time
                            if prediction.annotation_time
                            else ""
                        ),
                        file_path=self.layer.file_path,
                        is_model_generated=True,
                        model_name=self.current_model.name,
                    )
                )
            elif rect is not None:
                self.layer.annotations.append(
                    Annotation(
                        annotation_id=len(self.layer.annotations),
                        label=selected_label,
                        color=prediction_color,
                        rectangle=rect,
                        is_complete=True,
                        score=prediction.score,
                        annotator=self.current_model.name,
                        annotation_time=str(
                            prediction.annotation_time
                            if prediction.annotation_time
                            else ""
                        ),
                        file_path=self.layer.file_path,
                        is_model_generated=True,
                        model_name=self.current_model.name,
                    )
                )
            else:
                # points as center of canvas
                x, y = self.layer.width() // 2, self.layer.height() // 2
                self.layer.annotations.append(
                    Annotation(
                        annotation_id=len(self.layer.annotations),
                        label=selected_label,
                        color=prediction_color,
                        points=[QPointF(x, y)],
                        is_complete=True,
                        score=prediction.score,
                        annotator=self.current_model.name,
                        annotation_time=str(prediction.annotation_time),
                        file_path=self.layer.file_path,
                        is_model_generated=True,
                        model_name=self.current_model.name,
                    )
                )

        self.normalize_annotation_colors(self.layer.annotations, add_missing_labels=False)
        self.save_layer_annotations(self.layer)
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

    def update_annotation_list(self):
        """Update the annotation list with the current annotations."""
        self.annotation_list.update_list()

    def add_layer(self, layer):
        """Add a new layer to the tab."""
        # this layer i.e. canvas will have only one annotation
        logger.info(f"AnnotableLayer added: {layer.annotations[0].label}")
        self.layerAdded.emit(layer)

        self.layer.update()

    def layerify_selected(self):
        """Extract only selected visible annotations into Baker layers."""
        if not self.layer or not self.layer.annotations:
            self.messageSignal.emit("No annotations to extract")
            return
        selected = [
            ann for ann in self.layer.annotations if ann.selected and ann.visible
        ]
        if not selected:
            self.messageSignal.emit(
                "Select one or more visible annotations to extract, or use Layerify All."
            )
            return
        self.layer.layerify_annotation(selected)

    def layerify_all(self):
        """Layerify all annotations in the current layer."""
        if len(self.layer.annotations) == 0:
            logger.warning("No annotations to layerify")
            self.messageSignal.emit("No annotations to layerify")

            return
        logger.info("Layerifying all annotations")

        # else appends already added too
        self.layer.layerify_annotation(self.layer.annotations)

    def toggle_gridlines(self):
        """Toggle lightweight grid overlay in both tabs."""
        checked = self.grid_btn.isChecked() if hasattr(self, "grid_btn") else False
        self.config.show_gridlines = checked
        self.canvas_config.show_gridlines = checked
        if self.layer:
            self.layer.update()
        if hasattr(self.main_window, "baker_tab") and self.main_window.baker_tab.current_canvas:
            self.main_window.baker_tab.current_canvas.update()
        self.messageSignal.emit(f"Gridlines {'enabled' if checked else 'disabled'}.")

    def toggle_theme(self):
        """Toggle app theme."""
        if hasattr(self.main_window, "toggle_theme"):
            self.main_window.toggle_theme()

    def add_baked_result(self, baking_result: BakingResult):
        """Add a baked result to the baked results list and update the image list."""
        try:
            self.layer.setVisible(False)  # Hide the current layer
            filename = Path(baking_result.filename)
            filepath = self.config.bake_dir / filename.name
            baking_result.image.save(str(filepath))
            Annotation.save_as_json(
                baking_result.annotations, self._cache_path_for_file(filepath)
            )
            self.sync_labels_from_annotations(
                [annotation.copy() for annotation in baking_result.annotations]
            )

            baked_result_entry = ImageEntry(is_baked_result=True, data=filepath)
            self.image_entries.append(baked_result_entry)

            logger.info("A baked result has arrived, adding it to the image list.")
            page_index = (len(self.image_entries) - 1) // self.config.deque_maxlen
            self.image_list_panel.image_entries = self.image_entries
            self.image_list_panel.current_page = page_index
            self.image_list_panel.update_image_list(self.image_entries)
            self.image_list_panel.imageSelected.emit(baked_result_entry)

            self.messageSignal.emit("Baked result added")
            self.gotToTab.emit(0)
        except Exception as e:
            logger.exception(f"Failed to add baked result: {e}")
            self.messageSignal.emit(f"Failed to add baked result: {e}")

    def keyPressEvent(self, event):
        """Handle key press events for setting labels and deleting annotations."""
        key = event.key()

        # Debugging: Log the key press
        logger.info(f"Key pressed in LayerifyTab: {key}")
        if event.modifiers() & Qt.ControlModifier:
            if key == Qt.Key_Z:
                if event.modifiers() & Qt.ShiftModifier:
                    self.layer.redo()
                else:
                    self.layer.undo()
                self.annotation_list.update_list()
                event.accept()
                return
            if key == Qt.Key_Y:
                self.layer.redo()
                self.annotation_list.update_list()
                event.accept()
                return
            if key == Qt.Key_A:
                self.layer.select_all_annotations()
                self.annotation_list.update_list()
                event.accept()
                return
            if key == Qt.Key_C:
                self.layer.copy_annotation()
                event.accept()
                return
            if key == Qt.Key_V:
                self.layer.paste_annotation()
                self.annotation_list.update_list()
                event.accept()
                return

        # only if no modifier keys are pressed
        if event.modifiers() == Qt.NoModifier:
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
                if self.layer:
                    self.layer.delete_selected_annotations()
                    self.annotation_list.update_list()
                    logger.info("Selected annotation deleted.")

            # if clicked q, set the mode to point
            elif key == Qt.Key_Q:
                self.set_annotation_mode(MouseMode.POINT)
                logger.info("Mouse mode set to POINT.")
            # if clicked w, set the mode to polygon
            elif key == Qt.Key_W:
                self.set_annotation_mode(MouseMode.POLYGON)
                logger.info("Mouse mode set to POLYGON.")
            # if clicked e, set the mode to rectangle
            elif key == Qt.Key_E:
                self.set_annotation_mode(MouseMode.RECTANGLE)
                logger.info("Mouse mode set to RECTANGLE.")
            # if clicked b, set the mode to brush
            elif key == Qt.Key_B:
                self.set_annotation_mode(MouseMode.DRAW)
                logger.info("Mouse mode set to BRUSH DRAW.")
            # if clicked v or Esc, set the mode to idle/select
            elif key in (Qt.Key_V, Qt.Key_Escape):
                if self.layer and self.layer.current_annotation is not None:
                    self.layer.current_annotation = None
                    self.layer.update()
                self.set_annotation_mode(MouseMode.IDLE)
                logger.info("Mouse mode set to IDLE.")
                # if pressed h key, then toggle visibility of annotations
            elif event.key() == Qt.Key_H:
                self.layer.toggle_annotation_visibility()

            # if selected l, then run layerify the selected annotations
            elif event.key() == Qt.Key_L:
                if self.layer and self.layer.annotations:
                    selected_annotations = [
                        ann for ann in self.layer.annotations if ann.selected
                    ]
                    if selected_annotations:
                        logger.info(
                            f"Layerifying {len(selected_annotations)} selected annotations."
                        )
                        self.layer.layerify_annotation(selected_annotations)
                    else:
                        # layerify all annotations in the current layer
                        self.layer.layerify_annotation(self.layer.annotations)
                    logger.info("Layerified all annotations in the current layer.")
                else:
                    logger.warning("No annotations to layerify.")
            elif event.key() == Qt.Key_C:
                # if an annotation is selected, open a dialog box
                # in that dialog box, ask for a caption
                self.layer.selected_annotation = self.layer._get_selected_annotation()
                if self.layer.selected_annotation:
                    current_caption = getattr(
                        self.layer.selected_annotation, "caption", ""
                    )
                    text, ok = QInputDialog.getMultiLineText(
                        self, "Edit Caption", "Enter caption:", current_caption
                    )
                    if ok:
                        self.layer._push_undo_state()
                        self.layer.selected_annotation.caption = text
                        self.on_annotation_updated(self.layer.selected_annotation)
                        self.layer.update()

            # Pass the event to the annotation list if it needs to handle it
            if self.annotation_list.hasFocus():
                self.annotation_list.keyPressEvent(event)

        # Pass unhandled events to the base class
        super().keyPressEvent(event)
