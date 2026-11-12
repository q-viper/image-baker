"""Rendering, drawing states, keyboard, and mouse interactions for CanvasLayer."""

import math

from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QMessageBox

from imagebaker import logger
from imagebaker.core.configs import CursorDef
from imagebaker.core.defs import DrawingState, MouseMode


class CanvasInteractionMixin:
    """Mixin handling rendering, painting strokes, transforms, and input on CanvasLayer."""

    def handle_key_release(self, event: QKeyEvent):
        if event.key() == Qt.Key_Control:
            if self.mouse_mode not in [MouseMode.DRAW, MouseMode.ERASE]:
                self.mouse_mode = MouseMode.IDLE

    def _update_back_buffer(self):
        """
        Update the back buffer by rendering all visible layers with transforms and opacity.
        """
        self._back_buffer = QPixmap(self.size())
        self._back_buffer.fill(Qt.GlobalColor.transparent)

        if not hasattr(self, "layer_masks"):
            self.layer_masks = {}

        painter = QPainter(self._back_buffer)
        try:
            painter.setRenderHints(
                QPainter.RenderHint.Antialiasing
                | QPainter.RenderHint.SmoothPixmapTransform
            )

            for layer in self.layers:
                if layer.visible and not layer.image.isNull():
                    painter.save()
                    painter.translate(layer.position)
                    painter.rotate(layer.rotation)
                    painter.scale(layer.scale, layer.scale)
                    painter.setOpacity(layer.opacity)
                    painter.drawPixmap(QPoint(0, 0), layer.image)
                    painter.restore()
        finally:
            painter.end()

        self.image = self._back_buffer

    def handle_key_press(self, event: QKeyEvent):
        if event.key() in {Qt.Key_Delete, Qt.Key_Backspace}:
            self._delete_layer()
            event.accept()
            return

        if event.key() == Qt.Key_Escape:
            if self.is_playing:
                self.stop_playing()
                event.accept()
                return
            if self.mouse_mode in [MouseMode.DRAW, MouseMode.ERASE]:
                self.mouse_mode = MouseMode.IDLE
                self.messageSignal.emit("Exited brush mode.")
                self.update()
                event.accept()
                return
            if any(layer.selected for layer in self.layers):
                for layer in self.layers:
                    layer.selected = False
                self.selected_layer = None
                self.layersChanged.emit()
                self.messageSignal.emit("Deselected all layers.")
                self.update()
                event.accept()
                return

        if event.key() == Qt.Key_Control:
            if self.mouse_mode not in [MouseMode.DRAW, MouseMode.ERASE]:
                self.mouse_mode = MouseMode.PAN
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_A:
            for layer in self.layers:
                layer.selected = True
            self.selected_layer = self._get_selected_layer()
            self.layersChanged.emit()
            self.update()
            self.messageSignal.emit("Selected all layers.")
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self._copy_layer()
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self._paste_layer()
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Z:
            if event.modifiers() & Qt.ShiftModifier:
                self.redo()
            else:
                self.undo()
            event.accept()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Y:
            self.redo()
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_G:
            self.group_selected_layers()
            event.accept()
            return

        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_S:
            self.save_current_state(steps=1)
            event.accept()
            return

        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_W:
            self._move_selected_layer_down()
            event.accept()
            return

        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Up:
            self._move_selected_layer_up()
            event.accept()
            return

        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Down:
            self._move_selected_layer_down()
            event.accept()
            return

        if (
            event.modifiers() in {Qt.ControlModifier, Qt.NoModifier}
            and event.key() == Qt.Key_D
        ):
            self.mouse_mode = (
                MouseMode.DRAW if self.mouse_mode != MouseMode.DRAW else MouseMode.IDLE
            )
            self.messageSignal.emit(f"Drawing mode {self.mouse_mode.name.lower()}.")
            self.update()
            event.accept()
            return

        if (
            event.modifiers() in {Qt.ControlModifier, Qt.NoModifier}
            and event.key() == Qt.Key_E
        ):
            self.mouse_mode = (
                MouseMode.ERASE if self.mouse_mode != MouseMode.ERASE else MouseMode.IDLE
            )
            self.messageSignal.emit(f"Erasing mode {self.mouse_mode.name.lower()}.")
            self.update()
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_H:
            selected_layer = self._get_selected_layer()
            if selected_layer:
                self.push_undo_state()
                selected_layer.visible = not selected_layer.visible
                selected_layer.update()
                self.layersChanged.emit()
                self.messageSignal.emit(
                    f"Toggled visibility of layer: {selected_layer.layer_name}"
                )
                self.update()
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_W:
            self._move_selected_layer_up()
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_S:
            self._move_selected_layer_down()
            event.accept()
            return

        if event.key() == Qt.Key_R and not (event.modifiers() & Qt.ControlModifier):
            selected_layers = self._get_selected_layers()
            if selected_layers:
                self.push_undo_state()
                delta = -5.0 if (event.modifiers() & Qt.ShiftModifier) else 5.0
                for layer in selected_layers:
                    layer.rotation = (layer.rotation + delta) % 360.0
                self.layersChanged.emit()
                self.update()
                self.messageSignal.emit(f"Rotated selected layer(s) by {delta:+.0f}°.")
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_P:
            self.predict_state()
            event.accept()
            return

        if event.key() in {Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right} and not (
            event.modifiers() & Qt.ControlModifier
        ):
            selected_layers = self._get_selected_layers()
            if selected_layers:
                self.push_undo_state()
                step = 20.0 if (event.modifiers() & Qt.ShiftModifier) else 5.0
                dx = (
                    -step
                    if event.key() == Qt.Key_Left
                    else (step if event.key() == Qt.Key_Right else 0.0)
                )
                dy = (
                    -step
                    if event.key() == Qt.Key_Up
                    else (step if event.key() == Qt.Key_Down else 0.0)
                )
                for layer in selected_layers:
                    layer.position += QPointF(dx, dy)
                self.layersChanged.emit()
                self.update()
            event.accept()
            return

    def paint_layer(self, painter: QPainter):
        """Paint all visible layers, transforms, drawing strokes, and handles."""
        painter.translate(self.pan_offset)
        painter.scale(self.scale, self.scale)
        total_steps = max(1, len(self.states)) if self.states else 1
        render_step = self._current_step_index if self.states else 0
        for layer in self.layers:
            if layer.visible and not layer.image.isNull():
                render_pixmap = self._get_layer_render_pixmap(
                    layer=layer, step=render_step, total_steps=total_steps
                )
                painter.save()
                painter.translate(layer.position)
                painter.rotate(layer.rotation)
                painter.scale(layer.scale_x, layer.scale_y)

                pixmap_with_alpha = QPixmap(render_pixmap.size())
                pixmap_with_alpha.fill(Qt.transparent)

                temp_painter = QPainter(pixmap_with_alpha)
                opacity = layer.opacity / 255.0
                temp_painter.setOpacity(opacity)
                temp_painter.drawPixmap(0, 0, render_pixmap)
                temp_painter.end()

                painter.drawPixmap(0, 0, pixmap_with_alpha)

                if layer.selected:
                    painter.setPen(
                        QPen(
                            self.config.selected_draw_config.color,
                            self.config.selected_draw_config.line_width,
                        )
                    )
                    painter.setBrush(
                        QBrush(
                            QColor(
                                self.config.selected_draw_config.color.red(),
                                self.config.selected_draw_config.color.green(),
                                self.config.selected_draw_config.color.blue(),
                                self.config.selected_draw_config.brush_alpha,
                            )
                        )
                    )
                    painter.drawRect(QRectF(QPointF(0, 0), layer.original_size))
                painter.restore()

                if layer.selected:
                    self._draw_transform_handles(painter, layer)
                if layer.layer_state.drawing_states:
                    painter.save()
                    painter.translate(layer.position)
                    painter.rotate(layer.rotation)
                    painter.scale(layer.scale_x, layer.scale_y)

                    for state in layer.layer_state.drawing_states:
                        painter.setRenderHints(QPainter.Antialiasing)
                        painter.setPen(
                            QPen(
                                state.color,
                                state.size,
                                Qt.SolidLine,
                                Qt.RoundCap,
                                Qt.RoundJoin,
                            )
                        )
                        painter.drawPoint(state.position)

                    painter.restore()
        if self.layer_state.drawing_states:
            painter.save()
            painter.translate(self.position)
            painter.rotate(self.rotation)
            painter.scale(self.scale_x, self.scale_y)

            for state in self.layer_state.drawing_states:
                painter.setRenderHints(QPainter.Antialiasing)
                painter.setPen(
                    QPen(
                        state.color,
                        state.size,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.RoundJoin,
                    )
                )
                painter.drawPoint(state.position)

            painter.restore()

    def _grid_view_transform(self) -> tuple[QPointF, float]:
        """Use canvas pan + zoom so grid scales and moves with the page view."""
        anchor = (
            self.pan_offset if isinstance(self.pan_offset, QPointF) else QPointF(0, 0)
        )
        zoom = float(self.scale) if self.scale else 1.0
        return anchor, max(0.01, zoom)

    def _draw_transform_handles(self, painter, layer):
        """Draw rotation and scaling handles for the selected layer."""
        transform = QTransform()
        transform.translate(layer.position.x(), layer.position.y())
        transform.rotate(layer.rotation)
        transform.scale(layer.scale_x, layer.scale_y)

        rect = transform.mapRect(QRectF(QPointF(0, 0), layer.original_size))
        handle_size = 10 / self.scale
        rotation_pos = rect.center()

        corners = [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
        ]
        edges = [
            QPointF(rect.center().x(), rect.top()),
            QPointF(rect.center().x(), rect.bottom()),
            QPointF(rect.left(), rect.center().y()),
            QPointF(rect.right(), rect.center().y()),
        ]

        painter.setPen(
            QPen(
                self.config.selected_draw_config.handle_color,
                self.config.selected_draw_config.handle_width / self.scale,
            )
        )
        painter.setBrush(self.config.selected_draw_config.handle_color)
        painter.drawEllipse(
            rotation_pos,
            self.config.selected_draw_config.handle_point_size * 1.1 / self.scale,
            self.config.selected_draw_config.handle_point_size * 1.1 / self.scale,
        )
        painter.drawLine(rotation_pos, rotation_pos + QPointF(0, -handle_size))
        painter.drawLine(rotation_pos, rotation_pos + QPointF(0, handle_size))
        painter.drawLine(rotation_pos, rotation_pos + QPointF(-handle_size, 0))
        painter.drawLine(rotation_pos, rotation_pos + QPointF(handle_size, 0))

        handle_color = self.config.selected_draw_config.handle_color
        painter.setPen(
            QPen(
                handle_color, self.config.selected_draw_config.handle_width / self.scale
            )
        )
        painter.setBrush(self.config.selected_draw_config.handle_color)
        for corner in corners:
            painter.drawEllipse(
                corner,
                self.config.selected_draw_config.handle_point_size / self.scale,
                self.config.selected_draw_config.handle_point_size / self.scale,
            )
        for edge in edges:
            painter.drawEllipse(
                edge,
                self.config.selected_draw_config.handle_edge_size / self.scale,
                self.config.selected_draw_config.handle_edge_size / self.scale,
            )
            painter.drawLine(edge + QPointF(-handle_size, 0), edge + QPointF(handle_size, 0))
            painter.drawLine(edge + QPointF(0, -handle_size), edge + QPointF(0, handle_size))

    def _add_drawing_state(self, pos: QPointF):
        """Add or erase drawing strokes on the selected layer."""
        self.selected_layer = self._get_selected_layer()
        layer = self.selected_layer
        if not layer:
            logger.debug("No layer selected for drawing.")
            QMessageBox.information(
                self.parent(),
                "No Layer Selected",
                "Please select a layer to draw on.",
            )
            return

        relative_pos = pos - layer.position

        if self.mouse_mode == MouseMode.ERASE:
            layer.layer_state.drawing_states = [
                state
                for state in layer.layer_state.drawing_states
                if (state.position - relative_pos).manhattanLength() > self.brush_size
            ]
        elif self.mouse_mode == MouseMode.DRAW:
            drawing_state = DrawingState(
                position=relative_pos,
                color=self.drawing_color,
                size=self.brush_size,
            )
            layer.layer_state.drawing_states.append(drawing_state)
            self._last_draw_point = relative_pos
            logger.debug(
                f"Added drawing state at position: {relative_pos} to layer {layer.layer_name}"
            )
        else:
            logger.debug(
                f"Mouse mode {self.mouse_mode} does not support drawing states."
            )
            return
        self.update()

    def handle_wheel(self, event: QWheelEvent):
        if self.mouse_mode in (MouseMode.DRAW, MouseMode.ERASE):
            delta = event.angleDelta().y() / 120
            self.brush_size = max(1, self.brush_size + int(delta))
            self.messageSignal.emit(f"Brush size: {self.brush_size}")
            self.update()
            return
        if event.modifiers() & Qt.ControlModifier:
            mouse_pos = event.position()
            zoom_factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            old_scale = self.scale
            new_scale = max(0.1, min(old_scale * zoom_factor, 10.0))

            before_zoom_img_pos = (mouse_pos - self.pan_offset) / old_scale
            self.scale = new_scale
            after_zoom_widget_pos = before_zoom_img_pos * new_scale + self.pan_offset
            self.pan_offset += mouse_pos - after_zoom_widget_pos

            self.mouse_mode = (
                MouseMode.ZOOM_IN if event.angleDelta().y() > 0 else MouseMode.ZOOM_OUT
            )
            self.zoomChanged.emit(self.scale)
            self.update()

    def handle_mouse_release(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._active_handle = None
            self._dragging_layer = None
            self._multi_drag_offsets = None
            self._interaction_undo_pushed = False
            if self.mouse_mode in [MouseMode.DRAW, MouseMode.ERASE]:
                self._last_draw_point = None
                self.update()

    def handle_mouse_move(self, event: QMouseEvent):
        pos = (event.position() - self.pan_offset) / self.scale
        self._cursor_position = event.position()

        if event.buttons() & Qt.LeftButton:
            if self.mouse_mode in [MouseMode.DRAW, MouseMode.ERASE]:
                self._add_drawing_state(pos)
                return

        if self.mouse_mode == MouseMode.PAN:
            if (
                event.modifiers() & Qt.ControlModifier
                and event.buttons() & Qt.LeftButton
            ):
                if self.last_pan_point:
                    delta = event.position() - self.last_pan_point
                    self.pan_offset += delta
                    self.last_pan_point = event.position()
                    self.update()
                    return
            else:
                self.last_pan_point = None
                self.mouse_mode = MouseMode.IDLE

        if self._active_handle:
            handle_type, layer = self._active_handle
            start = self._drag_start
            if not self._interaction_undo_pushed:
                self.push_undo_state()
                self._interaction_undo_pushed = True
            if "rotate" in handle_type:
                center = start["center"]
                current_vector = pos - center
                current_angle = math.atan2(current_vector.y(), current_vector.x())
                angle_delta = math.degrees(current_angle - start["initial_angle"])

                new_transform = QTransform()
                new_transform.translate(center.x(), center.y())
                new_transform.rotate(angle_delta)
                new_transform.translate(-center.x(), -center.y())

                layer.rotation = (start["rotation"] + angle_delta) % 360
                layer.position = new_transform.map(start["position"])
                self.messageSignal.emit(
                    f"Rotating layer {layer.layer_name} to {layer.rotation:.2f} degrees"
                )
                layer.selected = True
                self.layersChanged.emit()
                return
            elif "scale" in handle_type:
                handle_index = int(handle_type.split("_")[-1])
                original_size = layer.original_size
                delta = pos - start["pos"]
                new_scale_x = layer.scale_x
                new_scale_y = layer.scale_y
                pos_offset = QPointF(0, 0)

                if handle_index == 0:
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] - delta.y() / original_size.height()
                    pos_offset = delta
                    self.setCursor(CursorDef.TRANSFORM_ALL)
                elif handle_index == 1:
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] - delta.y() / original_size.height()
                    pos_offset = QPointF(0, delta.y())
                    self.mouse_mode = MouseMode.RESIZE
                elif handle_index == 2:
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    pos_offset = QPointF(delta.x(), 0)
                    self.mouse_mode = MouseMode.RESIZE
                elif handle_index == 3:
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    self.mouse_mode = MouseMode.RESIZE
                elif handle_index == 4:
                    new_scale_y = start["scale_y"] - delta.y() / original_size.height()
                    pos_offset = QPointF(0, delta.y())
                    self.mouse_mode = MouseMode.RESIZE_HEIGHT
                elif handle_index == 5:
                    new_scale_y = start["scale_y"] + delta.y() / original_size.height()
                    self.mouse_mode = MouseMode.RESIZE_HEIGHT
                elif handle_index == 6:
                    new_scale_x = start["scale_x"] - delta.x() / original_size.width()
                    self.mouse_mode = MouseMode.RESIZE_WIDTH
                    pos_offset = QPointF(delta.x(), 0)
                elif handle_index == 7:
                    new_scale_x = start["scale_x"] + delta.x() / original_size.width()
                    self.mouse_mode = MouseMode.RESIZE_WIDTH

                layer.scale_x = max(0.1, min(new_scale_x, 5.0))
                layer.scale_y = max(0.1, min(new_scale_y, 5.0))
                if handle_index in [0, 1, 2, 4, 6]:
                    layer.position = start["position"] + pos_offset

                self.messageSignal.emit(
                    f"Scaling layer {layer.layer_name} to {layer.scale_x:.2f}, {layer.scale_y:.2f}"
                )
                self.layersChanged.emit()
            self.update()
        elif self._dragging_layer:
            if not self._interaction_undo_pushed:
                self.push_undo_state()
                self._interaction_undo_pushed = True
            multi_offsets = getattr(self, "_multi_drag_offsets", None)
            if multi_offsets and len(multi_offsets) > 1:
                for target_layer, offset in multi_offsets:
                    target_layer.position = pos - offset
                    target_layer.selected = True
                    target_layer.update()
            else:
                self._dragging_layer.position = pos - self._drag_offset
                self._dragging_layer.selected = True
                self._dragging_layer.update()
                for layer in self.layers:
                    if layer != self._dragging_layer:
                        layer.selected = False

            self.layersChanged.emit()
            self.update()

    def handle_mouse_press(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pos = (event.position() - self.pan_offset) / self.scale
            self._interaction_undo_pushed = False
            if self.mouse_mode in [MouseMode.DRAW, MouseMode.ERASE]:
                if self._get_selected_layer() is not None:
                    self.push_undo_state()
                self._last_draw_point = pos
                self._add_drawing_state(pos)
                return
            if event.modifiers() & Qt.ControlModifier:
                clicked_layer = None
                for layer in reversed(self.layers):
                    if not layer.visible:
                        continue
                    rect = self._compose_layer_transform(layer).mapRect(
                        QRectF(QPointF(0, 0), layer.original_size)
                    )
                    if rect.contains(pos):
                        clicked_layer = layer
                        break

                if clicked_layer is not None:
                    clicked_layer.selected = not clicked_layer.selected
                    self.selected_layer = (
                        clicked_layer
                        if clicked_layer.selected
                        else self._get_selected_layer()
                    )
                    self.layersChanged.emit()
                    self.update()
                else:
                    self.mouse_mode = MouseMode.PAN
                    self.last_pan_point = event.position()
                return

            for layer in reversed(self.layers):
                if layer.selected and layer.visible:
                    handle_size = 10 / self.scale
                    full_transform = self._compose_layer_transform(layer)
                    full_rect = full_transform.mapRect(
                        QRectF(QPointF(0, 0), layer.original_size)
                    )
                    full_center = full_rect.center()

                    if QLineF(pos, full_center).length() < handle_size:
                        vec = pos - full_center
                        self._active_handle = ("rotate", layer)
                        self._drag_start = {
                            "pos": pos,
                            "rotation": layer.rotation,
                            "center": full_center,
                            "initial_angle": math.atan2(vec.y(), vec.x()),
                            "position": layer.position,
                        }
                        return

                    scale_handles = [
                        full_rect.topLeft(),
                        full_rect.topRight(),
                        full_rect.bottomLeft(),
                        full_rect.bottomRight(),
                        QPointF(full_center.x(), full_rect.top()),
                        QPointF(full_center.x(), full_rect.bottom()),
                        QPointF(full_rect.left(), full_center.y()),
                        QPointF(full_rect.right(), full_center.y()),
                    ]
                    for i, handle_pos in enumerate(scale_handles):
                        if QLineF(pos, handle_pos).length() < handle_size:
                            self._active_handle = (f"scale_{i}", layer)
                            self._drag_start = {
                                "pos": pos,
                                "scale_x": layer.scale_x,
                                "scale_y": layer.scale_y,
                                "position": layer.position,
                            }
                            return

            for layer in reversed(self.layers):
                if layer.visible:
                    rect = self._compose_layer_transform(layer).mapRect(
                        QRectF(QPointF(0, 0), layer.original_size)
                    )
                    if rect.contains(pos):
                        self._dragging_layer = layer
                        self._drag_offset = pos - layer.position
                        if not layer.selected:
                            layer.selected = True
                            for other_layer in self.layers:
                                if other_layer != layer:
                                    other_layer.selected = False
                        self._multi_drag_offsets = [
                            (lyr, pos - lyr.position)
                            for lyr in self.layers
                            if lyr.selected
                        ]
                        layer.update()
                        self.layersChanged.emit()
                        break

        elif event.button() == Qt.RightButton:
            pos = (event.position() - self.pan_offset) / self.scale
            hit_any = any(
                self._compose_layer_transform(layer)
                .mapRect(QRectF(QPointF(0, 0), layer.original_size))
                .contains(pos)
                for layer in reversed(self.layers)
                if layer.visible
            )
            if not hit_any:
                for layer in self.layers:
                    layer.selected = False
                self.selected_layer = None
            self.mouse_mode = MouseMode.IDLE
            self.layersChanged.emit()
            self.update()

    def handle_mouse_double_click(self, event: QMouseEvent, pos: QPoint):
        self.update()
