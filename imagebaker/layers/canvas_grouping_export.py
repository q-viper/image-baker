"""Layer grouping, stack manipulation, and Baker export workflows for CanvasLayer."""

import math
from datetime import datetime

import cv2
from PySide6.QtCore import QPointF, QRectF, Qt, QThread
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from imagebaker import logger
from imagebaker.core.defs import Annotation, BakingResult
from imagebaker.layers.base_layer import BaseLayer
from imagebaker.utils.image import draw_annotations, qpixmap_to_numpy
from imagebaker.workers import BakerWorker


class CanvasGroupingExportMixin:
    """Mixin managing layer stack ops, grouping/ungrouping, and Baker exports."""

    def _get_selected_layer(self):
        for layer in self.layers:
            if layer.selected:
                return layer
        return None

    def _get_selected_layers(self) -> list[BaseLayer]:
        return [layer for layer in self.layers if layer.selected]

    @staticmethod
    def _compose_layer_transform(layer: BaseLayer) -> QTransform:
        transform = QTransform()
        transform.translate(layer.position.x(), layer.position.y())
        transform.rotate(layer.rotation)
        transform.scale(layer.scale_x, layer.scale_y)
        return transform

    @staticmethod
    def _decompose_transform(transform: QTransform) -> tuple[QPointF, float, float, float]:
        m11 = transform.m11()
        m12 = transform.m12()
        m21 = transform.m21()
        m22 = transform.m22()

        scale_x = max(0.001, math.hypot(m11, m12))
        scale_y = max(0.001, math.hypot(m21, m22))
        rotation = math.degrees(math.atan2(m12, m11))
        position = QPointF(transform.dx(), transform.dy())
        return position, rotation, scale_x, scale_y

    @staticmethod
    def _is_group_layer(layer: BaseLayer) -> bool:
        return len(layer.layers) >= 2

    @staticmethod
    def _map_annotation_to_group(
        annotation: Annotation, layer_transform: QTransform
    ) -> Annotation:
        mapped = annotation.copy()
        if mapped.rectangle:
            mapped.rectangle = layer_transform.mapRect(mapped.rectangle)
        if mapped.polygon:
            mapped.polygon = layer_transform.map(mapped.polygon)
        if mapped.points:
            mapped.points = [layer_transform.map(point) for point in mapped.points]
        return mapped

    def group_selected_layers(self) -> bool:
        """Group 2 selected layers or ungroup 1 selected grouped layer."""
        selected_layers = self._get_selected_layers()
        if len(selected_layers) == 1 and self._is_group_layer(selected_layers[0]):
            return self._ungroup_layer(selected_layers[0])

        if len(selected_layers) != 2:
            self.messageSignal.emit("Select exactly 2 layers to group.")
            return False

        indices = sorted(self.layers.index(layer) for layer in selected_layers)
        ordered_layers = [self.layers[idx] for idx in indices]

        union_rect = None
        for layer in ordered_layers:
            if layer.image.isNull():
                self.messageSignal.emit("Cannot group layers with empty images.")
                return False

            transformed_rect = self._compose_layer_transform(layer).mapRect(
                QRectF(QPointF(0, 0), layer.original_size)
            )
            union_rect = (
                transformed_rect
                if union_rect is None
                else union_rect.united(transformed_rect)
            )

        if union_rect is None or union_rect.width() <= 0 or union_rect.height() <= 0:
            self.messageSignal.emit("Unable to group selected layers.")
            return False

        self.push_undo_state()
        group_width = max(1, int(math.ceil(union_rect.width())))
        group_height = max(1, int(math.ceil(union_rect.height())))

        composed = QPixmap(group_width, group_height)
        composed.fill(Qt.transparent)

        composed_painter = QPainter(composed)
        composed_painter.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        try:
            for layer in ordered_layers:
                layer_local_transform = QTransform()
                layer_local_transform.translate(
                    layer.position.x() - union_rect.left(),
                    layer.position.y() - union_rect.top(),
                )
                layer_local_transform.rotate(layer.rotation)
                layer_local_transform.scale(layer.scale_x, layer.scale_y)

                composed_painter.save()
                composed_painter.setTransform(layer_local_transform, combine=False)
                composed_painter.setOpacity(max(0.0, min(1.0, layer.opacity / 255.0)))
                composed_painter.drawPixmap(0, 0, layer.image)

                for state in layer.layer_state.drawing_states:
                    composed_painter.setPen(
                        QPen(
                            state.color,
                            state.size,
                            Qt.SolidLine,
                            Qt.RoundCap,
                            Qt.RoundJoin,
                        )
                    )
                    composed_painter.drawPoint(state.position)
                composed_painter.restore()
        finally:
            composed_painter.end()

        grouped_layer = ordered_layers[-1].copy()
        grouped_layer.set_image(composed)
        grouped_layer.position = QPointF(union_rect.left(), union_rect.top())
        grouped_layer.rotation = 0.0
        grouped_layer.scale_x = 1.0
        grouped_layer.scale_y = 1.0
        grouped_layer.opacity = 255
        grouped_layer.visible = True
        grouped_layer.selected = True
        grouped_layer.allow_annotation_export = any(
            layer.allow_annotation_export for layer in ordered_layers
        )
        grouped_layer.layer_name = (
            f"Group({ordered_layers[0].layer_name}, {ordered_layers[1].layer_name})"
        )
        grouped_layer.caption = (
            f"Grouped: {ordered_layers[0].layer_name}, {ordered_layers[1].layer_name}"
        )
        grouped_layer.layers = []
        grouped_layer.plugins = []

        merged_annotations: list[Annotation] = []
        for layer in ordered_layers:
            child_copy = layer.copy()
            child_copy.selected = False
            child_copy.position = child_copy.position - QPointF(
                union_rect.left(), union_rect.top()
            )
            grouped_layer.layers.append(child_copy)
            grouped_layer.plugins.extend(
                [
                    plugin.copy() if hasattr(plugin, "copy") else plugin
                    for plugin in getattr(layer, "plugins", [])
                ]
            )

            annotation_transform = QTransform()
            annotation_transform.translate(
                layer.position.x() - union_rect.left(),
                layer.position.y() - union_rect.top(),
            )
            annotation_transform.rotate(layer.rotation)
            annotation_transform.scale(layer.scale_x, layer.scale_y)
            for annotation in layer.annotations:
                mapped = self._map_annotation_to_group(annotation, annotation_transform)
                mapped.selected = False
                mapped.file_path = grouped_layer.file_path
                merged_annotations.append(mapped)

        if not merged_annotations:
            merged_annotations = [
                Annotation(annotation_id=0, label="Grouped", color=QColor(255, 255, 255))
            ]

        for idx, annotation in enumerate(merged_annotations):
            annotation.annotation_id = idx
        grouped_layer.annotations = merged_annotations

        for layer in self.layers:
            layer.selected = False
        insert_index = indices[-1]
        for idx in reversed(indices):
            del self.layers[idx]
            if idx < insert_index:
                insert_index -= 1
        self.layers.insert(insert_index, grouped_layer)

        for order, layer in enumerate(self.layers):
            layer.order = order

        self.selected_layer = grouped_layer
        self._update_back_buffer()
        self.layersChanged.emit()
        self.layerSelected.emit(grouped_layer)
        self.update()
        self.messageSignal.emit(
            f"Grouped layers: {ordered_layers[0].layer_name} + {ordered_layers[1].layer_name}"
        )
        return True

    def _ungroup_layer(self, grouped_layer: BaseLayer) -> bool:
        """Ungroup a previously grouped layer back into child layers."""
        if not self._is_group_layer(grouped_layer):
            self.messageSignal.emit("Select a grouped layer to ungroup.")
            return False

        if grouped_layer not in self.layers:
            self.messageSignal.emit("Grouped layer not found in canvas.")
            return False
        self.push_undo_state()

        group_index = self.layers.index(grouped_layer)
        group_transform = self._compose_layer_transform(grouped_layer)
        restored_layers: list[BaseLayer] = []
        for child_relative in grouped_layer.layers:
            child = child_relative.copy()
            child_local_transform = self._compose_layer_transform(child)
            child_world_transform = group_transform * child_local_transform

            position, rotation, scale_x, scale_y = self._decompose_transform(
                child_world_transform
            )
            child.position = position
            child.rotation = rotation
            child.scale_x = scale_x
            child.scale_y = scale_y
            child.opacity = int(round((child.opacity * grouped_layer.opacity) / 255.0))
            child.visible = grouped_layer.visible and child.visible
            child.selected = False
            restored_layers.append(child)

        del self.layers[group_index]
        for offset, child in enumerate(restored_layers):
            self.layers.insert(group_index + offset, child)

        for layer in self.layers:
            layer.selected = False
        if restored_layers:
            restored_layers[0].selected = True
            self.selected_layer = restored_layers[0]
        else:
            self.selected_layer = None

        for order, layer in enumerate(self.layers):
            layer.order = order

        self._update_back_buffer()
        self.layersChanged.emit()
        if self.selected_layer is not None:
            self.layerSelected.emit(self.selected_layer)
        self.update()
        self.messageSignal.emit(f"Ungrouped layer: {grouped_layer.layer_name}")
        return True

    def _center_layer_in_view(self, layer: BaseLayer):
        """Center a layer in the current canvas viewport."""
        if layer.image.isNull():
            return

        view_center = QPointF(self.width() / 2.0, self.height() / 2.0)
        world_center = (
            (view_center - self.pan_offset) / self.scale
            if self.scale != 0
            else view_center
        )
        half_width = (layer.image.width() * layer.scale_x) / 2.0
        half_height = (layer.image.height() * layer.scale_y) / 2.0
        layer.position = QPointF(
            world_center.x() - half_width, world_center.y() - half_height
        )

    def add_layer(
        self, layer: BaseLayer, index=-1, center=False, on_top=False, track_undo=True
    ):
        """Add a new child layer to the canvas layer."""
        if track_undo:
            self.push_undo_state()
        if center:
            self._center_layer_in_view(layer)

        layer.layer_name = f"{len(self.layers) + 1}_" + layer.layer_name
        if on_top or index >= 0:
            self.layers.append(layer)
        else:
            self.layers.insert(0, layer)

        self._update_back_buffer()
        self.update()
        self.messageSignal.emit(f"Added layer {layer.layer_name}")

    def clear_layers(self):
        """Clear all layers from the canvas layer."""
        if self.layers:
            self.push_undo_state()
        self.layers.clear()
        self._update_back_buffer()
        self.update()
        self.messageSignal.emit("Cleared all layers")

    def _copy_layer(self):
        self.selected_layer = self._get_selected_layer()
        if self.selected_layer:
            self.copied_layer = self.selected_layer.copy()
            self.messageSignal.emit(f"Copied layer {self.selected_layer.layer_name}.")
        else:
            self.messageSignal.emit("No layer selected to copy.")

    def _paste_layer(self):
        if self.copied_layer:
            new_layer = self.copied_layer.copy()
            new_layer.position += QPointF(10, 10)
            self.add_layer(new_layer, on_top=True)
            self.update()
            self.layerSelected.emit(new_layer)
            self.messageSignal.emit(f"Pasted layer {new_layer.layer_name}.")
        else:
            self.messageSignal.emit("No layer copied to paste.")

    def _delete_layer(self):
        self.selected_layer = self._get_selected_layer()
        if self.selected_layer:
            self.push_undo_state()
            self.layers = [
                layer for layer in self.layers if layer is not self.selected_layer
            ]
            self.messageSignal.emit(f"Deleted {self.selected_layer.layer_name} layer.")
            self.selected_layer = None
            self._update_back_buffer()
            self.layersChanged.emit()
            self.update()

    def _move_selected_layer_up(self):
        selected_layer = self._get_selected_layer()
        if not selected_layer:
            return
        self.push_undo_state()

        index = self.layers.index(selected_layer)
        if index > 0:
            self.layers.insert(index - 1, selected_layer)
            del self.layers[index + 1]
        else:
            self.layers.append(selected_layer)
            del self.layers[0]

        self.layersChanged.emit()
        self.update()
        self.messageSignal.emit(f"Moved layer {selected_layer.layer_name} up in order.")

    def _move_selected_layer_down(self):
        selected_layer = self._get_selected_layer()
        if not selected_layer:
            return
        self.push_undo_state()

        index = self.layers.index(selected_layer)
        if index < len(self.layers) - 1:
            self.layers.insert(index + 2, selected_layer)
            del self.layers[index]
        else:
            self.layers.insert(0, selected_layer)
            del self.layers[-1]

        self.layersChanged.emit()
        self.update()
        self.messageSignal.emit(
            f"Moved layer {selected_layer.layer_name} down in order."
        )

    def _launch_baker_worker(
        self,
        export_states: dict,
        timeline_total_steps: int,
        export_render_cache: dict,
        filename,
        progress_title: str,
        export_to_annotation_tab: bool,
        annotation_format: str,
    ):
        self.loading_dialog = QProgressDialog(
            progress_title, "Cancel", 0, 0, self.parentWidget()
        )
        self.loading_dialog.setWindowTitle("Please Wait")
        self.loading_dialog.setWindowModality(Qt.WindowModal)
        self.loading_dialog.setCancelButton(None)
        self.loading_dialog.show()
        QApplication.processEvents()

        self.worker_thread = QThread()
        self.worker = BakerWorker(
            layers=self.layers,
            states=export_states,
            filename=filename,
            render_cache=export_render_cache,
            timeline_total_steps=timeline_total_steps,
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(
            lambda results, export_to_annotation_tab=export_to_annotation_tab, fmt=annotation_format: self.handle_baker_results(
                results,
                export_to_annotation_tab=export_to_annotation_tab,
                annotation_format=fmt,
            )
        )
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.handle_baker_error)

        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.loading_dialog.close)
        self.worker_thread.start()

    def export_current_state(
        self, export_to_annotation_tab=False, annotation_format: str = "default"
    ):
        """Export the current state of the canvas layer."""
        if not self.layers:
            QMessageBox.warning(
                self,
                "Operation Not Possible",
                "No layers are available to export. Please add layers before exporting.",
                QMessageBox.Ok,
            )
            return
        filename = self.config.filename_format.format(
            project_name=self.config.project_name,
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        filename = self.config.export_folder / f"{filename}.png"
        logger.info(f"Exporting current baked image to {filename}")

        if self.states:
            step_key = (
                int(self.current_step)
                if int(self.current_step) in self.states
                else self._step_key_for_index(self._current_step_index)
            )
            if step_key is None:
                step_key = min(self.states.keys())
            export_states = {int(step_key): self.states[int(step_key)]}
            timeline_total_steps = max(1, len(self.states))
            cache_source_states = {
                int(k): self.states[int(k)]
                for k in sorted(self.states.keys())
                if int(k) <= int(step_key)
            }
            if not cache_source_states:
                cache_source_states = export_states
            self.messageSignal.emit(f"Exporting current timeline step {step_key}.")
        else:
            export_states = {0: self._build_states_for_step(step=0, total_steps=1)}
            timeline_total_steps = 1
            cache_source_states = export_states
            self.messageSignal.emit("No saved states found. Exporting current live state.")

        export_render_cache = self._build_export_render_cache(
            cache_source_states,
            timeline_total_steps=timeline_total_steps,
        )
        self._launch_baker_worker(
            export_states=export_states,
            timeline_total_steps=timeline_total_steps,
            export_render_cache=export_render_cache,
            filename=filename,
            progress_title="Baking Please wait...",
            export_to_annotation_tab=export_to_annotation_tab,
            annotation_format=annotation_format,
        )

    def handle_baker_error(self, error_msg):
        """Handle any errors that occur during the baking process."""
        self.loading_dialog.close()
        QMessageBox.critical(
            self.parentWidget(), "Error", f"Processing failed: {error_msg}"
        )

    def predict_state(self):
        """Send the current state to the prediction tab."""
        self.export_current_state(export_to_annotation_tab=True)

    def export_baked_states(
        self, export_to_annotation_tab=False, annotation_format: str = "default"
    ):
        """Export all the states stored in self.states."""
        export_states = self.states
        if len(self.states) == 0:
            msg = "No states to export. Creating a single image."
            logger.warning(msg)
            self.messageSignal.emit(msg)
            export_states = {0: self._build_states_for_step(step=0, total_steps=1)}

        filename = self.config.filename_format.format(
            project_name=self.config.project_name,
            timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        filename = self.config.export_folder / f"{filename}.png"
        timeline_total_steps = max(1, len(self.states)) if self.states else 1
        export_render_cache = self._build_export_render_cache(
            export_states,
            timeline_total_steps=timeline_total_steps,
        )
        self._launch_baker_worker(
            export_states=export_states,
            timeline_total_steps=timeline_total_steps,
            export_render_cache=export_render_cache,
            filename=filename,
            progress_title="Exporting states, please wait...",
            export_to_annotation_tab=export_to_annotation_tab,
            annotation_format=annotation_format,
        )

    def handle_baker_results(
        self,
        baking_results: list[BakingResult],
        export_to_annotation_tab=False,
        annotation_format: str = "default",
    ):
        from imagebaker.utils.annotation_formats import save_annotations_to_path

        logger.info("Baking completed.")
        fmt_norm = (annotation_format or "default").strip().lower()
        for baking_result in baking_results:
            filename, image = baking_result.filename, baking_result.image
            masks = baking_result.masks
            mask_names = baking_result.mask_names
            annotations = baking_result.annotations

            if not export_to_annotation_tab:
                image.save(str(filename))
                logger.info(f"Saved annotated image to annotated_{filename}")

                if self.config.is_debug:
                    if self.config.write_masks:
                        for i, mask in enumerate(masks):
                            mask_name = mask_names[i]
                            write_to = filename.parent / f"{mask_name}_{filename.name}"
                            cv2.imwrite(write_to, mask)
                    if self.config.write_annotations:
                        image_np = qpixmap_to_numpy(image.copy())
                        image_np = cv2.cvtColor(image_np, cv2.COLOR_RGBA2BGRA)
                        drawn = draw_annotations(image_np, annotations)
                        write_to = filename.parent / f"annotated_{filename.name}"
                        cv2.imwrite(str(write_to), drawn)

                if fmt_norm == "coco":
                    out_ann = filename.parent / f"{filename.stem}_coco.json"
                    save_annotations_to_path(
                        annotations,
                        out_ann,
                        fmt="coco",
                        image_name=filename.name,
                        image_width=image.width(),
                        image_height=image.height(),
                    )
                elif fmt_norm == "yolo":
                    out_ann = filename.parent / f"{filename.stem}.txt"
                    save_annotations_to_path(
                        annotations,
                        out_ann,
                        fmt="yolo",
                        image_name=filename.name,
                        image_width=image.width(),
                        image_height=image.height(),
                    )
                else:
                    Annotation.save_as_json(
                        annotations, f"{filename.parent / filename.stem}.json"
                    )
            else:
                self.bakingResult.emit(baking_result)

    def export_states_to_predict(self):
        self.export_baked_states(export_to_annotation_tab=True)
