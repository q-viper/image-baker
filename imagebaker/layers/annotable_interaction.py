"""Keyboard, wheel, mouse interaction, and hit-testing for AnnotableLayer."""

import cv2
import numpy as np
from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPolygonF, QWheelEvent

from imagebaker import logger
from imagebaker.core.configs import CursorDef
from imagebaker.core.defs import Annotation, MouseMode


class AnnotableInteractionMixin:
    """Mixin handling user input and spatial hit-testing on AnnotableLayer."""

    def handle_key_press(self, event: QKeyEvent):
        if event.key() == Qt.Key_Control:
            self.mouse_mode = MouseMode.PAN
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self._copy_annotation()
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self._paste_annotation()
            event.accept()
            return

        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_A:
            self.select_all_annotations()
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

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_Delete:
            self.delete_selected_annotations()
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and Qt.Key_0 <= event.key() <= Qt.Key_9:
            label_index = event.key() - Qt.Key_0
            if label_index < len(self.config.predefined_labels):
                label_info = self.config.predefined_labels[label_index]
                self.current_label = label_info.name
                self.current_color = label_info.color

                selected_annotations = [ann for ann in self.annotations if ann.selected]
                if not selected_annotations and self.selected_annotation is not None:
                    selected_annotations = [self.selected_annotation]

                if selected_annotations:
                    self._push_undo_state()
                for annotation in selected_annotations:
                    annotation.label = label_info.name
                    annotation.color = label_info.color
                    self.annotationUpdated.emit(annotation)

                self.messageSignal.emit(f"Label changed to: {label_info.name}")
                self.update()
                event.accept()
                return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_Q:
            self.set_mode(MouseMode.POINT)
            self.messageSignal.emit("Mouse mode set to POINT.")
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_W:
            self.set_mode(MouseMode.POLYGON)
            self.messageSignal.emit("Mouse mode set to POLYGON.")
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_E:
            self.set_mode(MouseMode.RECTANGLE)
            self.messageSignal.emit("Mouse mode set to RECTANGLE.")
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_H:
            self.toggle_annotation_visibility()
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_L:
            selected_annotations = [ann for ann in self.annotations if ann.selected]
            if selected_annotations:
                self.layerify_annotation(selected_annotations)
            else:
                self.layerify_annotation(self.annotations)
            event.accept()
            return

        if event.modifiers() == Qt.NoModifier and event.key() == Qt.Key_C:
            self.edit_selected_annotation_caption()
            event.accept()
            return

    def handle_key_release(self, event):
        if event.key() == Qt.Key_Control:
            if self.mouse_mode == MouseMode.PAN:
                self.mouse_mode = MouseMode.IDLE

    def handle_wheel(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            old_pos = self.widget_to_image_pos(event.position())
            zoom_factor = (
                self.config.zoom_in_factor
                if event.angleDelta().y() > 0
                else self.config.zoom_out_factor
            )
            new_scale = max(0.1, min(self.scale * zoom_factor, 10.0))
            self.offset += old_pos * self.scale - old_pos * new_scale
            self.scale = new_scale

            if event.angleDelta().y() > 0:
                self.mouse_mode = MouseMode.ZOOM_IN
            else:
                self.mouse_mode = MouseMode.ZOOM_OUT

            self.zoomChanged.emit(self.scale)
        elif self.mouse_mode in (MouseMode.DRAW, MouseMode.ERASE):
            step = 2 if event.angleDelta().y() > 0 else -2
            self.brush_size = max(2, min(120, int(getattr(self, "brush_size", 12)) + step))
            self.update_cursor()
            self.brushSizeChanged.emit(self.brush_size)
            self.messageSignal.emit(f"Brush size: {self.brush_size}px")
            self.update()

    def handle_mouse_release(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.mouse_mode in (MouseMode.DRAW, MouseMode.ERASE) and self._brush_mask is not None:
                mask = (self._brush_mask > 0).astype(np.uint8)
                target_ann = getattr(self, "_target_brush_annotation", None)
                if target_ann is not None and target_ann in self.annotations:
                    self._push_undo_state()
                    if np.any(mask):
                        target_ann.mask = mask
                        self.annotationUpdated.emit(target_ann)
                    else:
                        self.annotations.remove(target_ann)
                        if getattr(self, "selected_annotation", None) is target_ann:
                            self.selected_annotation = None
                        self.annotationRemoved.emit()
                elif (
                    np.any(mask)
                    and self.mouse_mode != MouseMode.ERASE
                    and not (event.modifiers() & Qt.AltModifier)
                ):
                    self._push_undo_state()
                    label = self.current_label or self.config.default_label.name
                    color = self.current_color or self.config.get_label_color(label)
                    next_id = max((a.annotation_id for a in self.annotations), default=-1) + 1
                    for prev_ann in self.annotations:
                        if prev_ann.selected:
                            prev_ann.selected = False
                            self.annotationUpdated.emit(prev_ann)

                    ann = Annotation(
                        file_path=self.file_path,
                        annotation_id=next_id,
                        label=label,
                        color=color,
                        mask=mask,
                        rectangle=None,
                        polygon=None,
                        selected=True,
                        is_complete=True,
                    )
                    self.annotations.append(ann)
                    self.selected_annotation = ann
                    self.annotationAdded.emit(ann)
                self._brush_mask = None
                self._brush_last_pos = None
                self._target_brush_annotation = None
                self.update()
                return
            if self.mouse_mode == MouseMode.RECTANGLE and self.current_annotation:
                rect = self.current_annotation.rectangle
                if rect and (
                    rect.width() >= self.config.drag_threshold
                    and rect.height() >= self.config.drag_threshold
                ):
                    self.finalize_annotation()
                else:
                    self.current_annotation = None
            elif self.mouse_mode == MouseMode.POLYGON and self.current_annotation:
                pass
            elif self.mouse_mode in [
                MouseMode.PAN,
                MouseMode.ZOOM_IN,
                MouseMode.ZOOM_OUT,
            ]:
                if self.current_annotation:
                    if (
                        self.current_annotation.polygon
                        and not self.current_annotation.is_complete
                    ):
                        self.mouse_mode = MouseMode.POLYGON
                else:
                    self.mouse_mode = MouseMode.IDLE

        if hasattr(self, "selected_annotation"):
            self.selected_annotation = None
        self.active_handle = None
        if hasattr(self, "active_point_index"):
            del self.active_point_index
        if hasattr(self, "initial_rect"):
            del self.initial_rect
        if hasattr(self, "initial_polygon"):
            del self.initial_polygon

        self.pan_start = None
        self.drag_start = None
        if self._drag_start_snapshot is not None:
            before = self._drag_start_snapshot
            after = self._snapshot_annotations()
            if not self._annotations_equal(before, after):
                self._undo_stack.append(before)
                if len(self._undo_stack) > self._max_history:
                    self._undo_stack.pop(0)
                self._redo_stack.clear()
            self._drag_start_snapshot = None

    def handle_mouse_move(self, event: QMouseEvent):
        img_pos = self.widget_to_image_pos(event.position())
        clamped_pos = QPointF(
            max(0, min(self.image.width(), img_pos.x())),
            max(0, min(self.image.height(), img_pos.y())),
        )
        self.mouseMoved.emit(img_pos)
        self.messageSignal.emit(f"X: {img_pos.x()}, Y: {img_pos.y()}")

        if not event.buttons():
            annotation, handle = self.find_annotation_and_handle_at(img_pos)
            prev_hovered = getattr(self, "hovered_annotation", None)
            self.hovered_annotation = annotation
            if prev_hovered is not annotation:
                self.update()
            if annotation and handle and self.mouse_mode == MouseMode.IDLE:
                if "point_" in handle or handle in [
                    "top_left",
                    "top_right",
                    "bottom_left",
                    "bottom_right",
                ]:
                    self.mouse_mode = MouseMode.RESIZE
                elif "center" in handle:
                    if "top" in handle or "bottom" in handle:
                        self.mouse_mode = MouseMode.RESIZE_HEIGHT
                    else:
                        self.mouse_mode = MouseMode.RESIZE_WIDTH
                elif handle == "move":
                    self.mouse_mode = MouseMode.GRAB

            elif not handle and self.mouse_mode in [
                MouseMode.RESIZE,
                MouseMode.RESIZE_HEIGHT,
                MouseMode.RESIZE_WIDTH,
                MouseMode.GRAB,
            ]:
                self.mouse_mode = MouseMode.IDLE
            self.update_cursor()
        else:
            if (
                event.buttons() & Qt.LeftButton
                and self.mouse_mode not in (MouseMode.DRAW, MouseMode.ERASE)
                and self.selected_annotation
                and getattr(self, "active_handle", None)
            ):
                if self.active_handle == "move":
                    self.setCursor(CursorDef.GRABBING_CURSOR)
                    new_pos = img_pos - self.drag_offset
                    delta = new_pos - self.get_annotation_position(
                        self.selected_annotation
                    )
                    targets = (
                        [ann for ann in self.annotations if ann.selected]
                        if self.selected_annotation.selected
                        else [self.selected_annotation]
                    )
                    for target_ann in targets:
                        target_pos = self.get_annotation_position(target_ann) + delta
                        self.move_annotation(target_ann, target_pos)
                        self.annotationUpdated.emit(target_ann)
                elif self.selected_annotation.rectangle:
                    rect = QRectF(self.initial_rect)
                    if "top" in self.active_handle:
                        rect.setTop(img_pos.y())
                    if "bottom" in self.active_handle:
                        rect.setBottom(img_pos.y())
                    if "left" in self.active_handle:
                        rect.setLeft(img_pos.x())
                    if "right" in self.active_handle:
                        rect.setRight(img_pos.x())
                    self.selected_annotation.rectangle = rect.normalized()
                elif self.selected_annotation.polygon and hasattr(
                    self, "active_point_index"
                ):
                    self.selected_annotation.polygon[self.active_point_index] = (
                        clamped_pos
                    )
                elif self.selected_annotation.points:
                    self.selected_annotation.points[0] = clamped_pos
                self.annotationMoved.emit()
                self.annotationUpdated.emit(self.selected_annotation)
                self.update()
                return

            if (
                self.mouse_mode in (MouseMode.DRAW, MouseMode.ERASE)
                and event.buttons() & Qt.LeftButton
            ):
                if self._brush_mask is not None and self._brush_last_pos is not None:
                    x0, y0 = self._brush_last_pos
                    x1, y1 = int(round(clamped_pos.x())), int(round(clamped_pos.y()))
                    brush_size = max(1, int(getattr(self, "brush_size", 12)))
                    effective_erase = (
                        self.mouse_mode == MouseMode.ERASE
                        or bool(event.modifiers() & Qt.AltModifier)
                    )
                    color_val = 0 if effective_erase else 1
                    cv2.line(
                        self._brush_mask,
                        (x0, y0),
                        (x1, y1),
                        color=color_val,
                        thickness=brush_size,
                    )
                    self._brush_last_pos = (x1, y1)
                    self.update()
                return

            if self.mouse_mode == MouseMode.PAN and event.buttons() & Qt.LeftButton:
                if self.pan_start:
                    delta = event.position() - self.pan_start
                    self.offset += delta
                    self.pan_start = event.position()
                    self.update()
            elif self.mouse_mode == MouseMode.RECTANGLE and self.drag_start:
                self.current_annotation.rectangle = QRectF(
                    self.drag_start, clamped_pos
                ).normalized()
                self.update()
            elif self.mouse_mode == MouseMode.POLYGON and self.current_annotation:
                if self.current_annotation.polygon:
                    temp_points = QPolygonF(self.current_annotation.polygon)
                    if temp_points:
                        temp_points[-1] = clamped_pos
                        self.current_annotation.polygon = temp_points
                        self.update()

    def move_annotation(self, annotation, new_pos: QPointF):
        delta = new_pos - self.get_annotation_position(annotation)

        if annotation.rectangle:
            annotation.rectangle.translate(delta)
        if annotation.polygon:
            annotation.polygon.translate(delta)
        if annotation.points:
            annotation.points = [p + delta for p in annotation.points]

        if annotation.mask is not None:
            dx = int(round(delta.x()))
            dy = int(round(delta.y()))
            if dx != 0 or dy != 0:
                h, w = annotation.mask.shape[:2]
                shifted = np.zeros_like(annotation.mask)
                sx1 = max(0, -dx)
                sy1 = max(0, -dy)
                sx2 = min(w, w - dx)
                sy2 = min(h, h - dy)
                dx1 = max(0, dx)
                dy1 = max(0, dy)
                dx2 = min(w, dx + (sx2 - sx1))
                dy2 = min(h, dy + (sy2 - sy1))
                if sx2 > sx1 and sy2 > sy1 and dx2 > dx1 and dy2 > dy1:
                    shifted[dy1:dy2, dx1:dx2] = annotation.mask[sy1:sy2, sx1:sx2]
                annotation.mask = shifted

    def handle_mouse_press(self, event: QMouseEvent):
        img_pos = self.widget_to_image_pos(event.position())
        clamped_pos = QPointF(
            max(0, min(self.image.width(), img_pos.x())),
            max(0, min(self.image.height(), img_pos.y())),
        )

        if event.button() == Qt.RightButton:
            if self.current_annotation and self.mouse_mode == MouseMode.POLYGON:
                if len(self.current_annotation.polygon) > 0:
                    self.current_annotation.polygon = QPolygonF(
                        list(self.current_annotation.polygon)[:-1]
                    )
                if len(self.current_annotation.polygon) == 0:
                    self.current_annotation = None
                    self.mouse_mode = MouseMode.IDLE

            if not self.current_annotation:
                self.mouse_mode = MouseMode.IDLE
                ann_at_pos, _ = self.find_annotation_and_handle_at(img_pos)
                if ann_at_pos is None:
                    for ann in self.annotations:
                        ann.selected = False
                        self.annotationUpdated.emit(ann)
            self.update()

        if event.button() == Qt.LeftButton:
            self._drag_start_snapshot = None
            if self.mouse_mode in (MouseMode.DRAW, MouseMode.ERASE):
                effective_erase = (
                    self.mouse_mode == MouseMode.ERASE
                    or bool(event.modifiers() & Qt.AltModifier)
                )
                img_h, img_w = max(1, self.image.height()), max(1, self.image.width())
                selected_brush = next(
                    (
                        a
                        for a in self.annotations
                        if a.selected
                        and a.visible
                        and a.mask is not None
                        and not a.polygon
                        and not a.rectangle
                    ),
                    None,
                )
                if selected_brush is None and effective_erase:
                    hit_ann = self.find_annotation_at(img_pos)
                    if (
                        hit_ann is not None
                        and hit_ann.mask is not None
                        and not hit_ann.polygon
                        and not hit_ann.rectangle
                    ):
                        selected_brush = hit_ann
                        for a in self.annotations:
                            a.selected = a is hit_ann
                            self.annotationUpdated.emit(a)

                if selected_brush is not None:
                    raw_m = np.asarray(selected_brush.mask)
                    if raw_m.ndim == 3:
                        raw_m = raw_m[:, :, -1] if raw_m.shape[2] == 4 else raw_m[:, :, 0]
                    work_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                    ch = min(img_h, raw_m.shape[0])
                    cw = min(img_w, raw_m.shape[1])
                    work_mask[:ch, :cw] = (raw_m[:ch, :cw] > 0).astype(np.uint8)
                    self._brush_mask = work_mask
                    self._target_brush_annotation = selected_brush
                elif effective_erase:
                    self._brush_mask = None
                    self._target_brush_annotation = None
                    self.messageSignal.emit("Select or click a brush mask to erase.")
                    return
                else:
                    self._target_brush_annotation = None
                    self._brush_mask = np.zeros((img_h, img_w), dtype=np.uint8)

                pt = (int(round(clamped_pos.x())), int(round(clamped_pos.y())))
                self._brush_last_pos = pt
                brush_size = max(1, int(getattr(self, "brush_size", 12)))
                color_val = 0 if effective_erase else 1
                cv2.circle(self._brush_mask, pt, max(1, brush_size // 2), color_val, -1)
                self.current_label = self.current_label or (
                    selected_brush.label
                    if selected_brush
                    else self.config.default_label.name
                )
                self.current_color = self.current_color or (
                    selected_brush.color
                    if selected_brush
                    else self.config.get_label_color(self.current_label)
                )
                self.update()
                return

            is_drawing_polygon = (
                self.mouse_mode == MouseMode.POLYGON
                and self.current_annotation is not None
                and self.current_annotation.polygon is not None
                and len(self.current_annotation.polygon) > 0
            )

            if not is_drawing_polygon:
                widget_pos = event.position()
                for lrect, ann in reversed(self.label_rects):
                    if lrect.contains(widget_pos):
                        self.selected_annotation = ann
                        self.active_handle = "move"
                        break

                if not self.selected_annotation:
                    self.selected_annotation, self.active_handle = (
                        self.find_annotation_and_handle_at(img_pos)
                    )
            else:
                self.selected_annotation = None
                self.active_handle = None

            if self.selected_annotation:
                self._drag_start_snapshot = self._snapshot_annotations()
                is_multi_select = bool(event.modifiers() & Qt.ControlModifier)
                self.drag_offset = img_pos - self.get_annotation_position(
                    self.selected_annotation
                )
                if is_multi_select:
                    self.selected_annotation.selected = (
                        not self.selected_annotation.selected
                    )
                    self.annotationUpdated.emit(self.selected_annotation)
                else:
                    if not (
                        self.selected_annotation.selected
                        and self.active_handle == "move"
                    ):
                        self.selected_annotation.selected = True
                        for ann in self.annotations:
                            if ann != self.selected_annotation:
                                ann.selected = False
                            self.annotationUpdated.emit(ann)

                if self.selected_annotation.rectangle:
                    self.initial_rect = QRectF(self.selected_annotation.rectangle)
                elif self.selected_annotation.polygon:
                    self.initial_polygon = QPolygonF(self.selected_annotation.polygon)
                    if self.active_handle and "point_" in self.active_handle:
                        self.active_point_index = int(self.active_handle.split("_")[1])
                elif self.selected_annotation.points:
                    self.active_point_index = 0

                self.update()
                return

            if self.mouse_mode == MouseMode.PAN:
                self.pan_start = event.position()
                return

            if self.mouse_mode == MouseMode.POINT:
                self.current_annotation = Annotation(
                    label=self.current_label,
                    annotation_id=len(self.annotations),
                    points=[clamped_pos],
                )
                self.finalize_annotation()
            elif self.mouse_mode == MouseMode.RECTANGLE:
                self.current_annotation = Annotation(
                    file_path=self.file_path,
                    annotation_id=len(self.annotations),
                    label="Incomplete",
                    color=self.current_color,
                    rectangle=QRectF(clamped_pos, clamped_pos),
                )
                self.drag_start = clamped_pos
            elif self.mouse_mode == MouseMode.POLYGON:
                eff_margin = 10.0 / max(0.1, float(self.scale))
                if not self.current_annotation:
                    if len(self.annotations) > 0:
                        last_polygon = self.annotations[-1].polygon
                        if last_polygon:
                            last_point = last_polygon[-1]
                            if (last_point - clamped_pos).manhattanLength() < 1.0:
                                logger.info(
                                    "Ignoring point, same as last polygon point"
                                )
                                return

                    self.current_annotation = Annotation(
                        file_path=self.file_path,
                        annotation_id=len(self.annotations),
                        label="Incomplete",
                        color=self.current_color,
                        polygon=QPolygonF([clamped_pos]),
                    )
                else:
                    poly = self.current_annotation.polygon
                    if (
                        len(poly) >= 3
                        and (poly[0] - clamped_pos).manhattanLength() < eff_margin
                    ):
                        self.current_annotation.is_complete = True
                        self.finalize_annotation()
                        self.current_annotation = None
                    elif (
                        len(poly) == 0
                        or (poly[-1] - clamped_pos).manhattanLength() > 1.0
                    ):
                        logger.info(f"Adding point to polygon: {clamped_pos}")
                        self.current_annotation.polygon.append(clamped_pos)

            self.update()

    def get_annotation_position(self, annotation: Annotation):
        if annotation.rectangle:
            return annotation.rectangle.center()
        elif annotation.polygon:
            return annotation.polygon.boundingRect().center()
        elif annotation.points:
            return annotation.points[0]
        elif annotation.mask is not None and np.any(annotation.mask):
            ys, xs = np.nonzero(annotation.mask)
            if len(xs) > 0 and len(ys) > 0:
                return QPointF(
                    (float(xs.min()) + float(xs.max())) / 2.0,
                    (float(ys.min()) + float(ys.max())) / 2.0,
                )
        return QPointF()

    @staticmethod
    def _find_polygon_edge_at(
        polygon: QPolygonF, pos: QPointF
    ) -> tuple[int | None, QPointF | None, float]:
        if not polygon or len(polygon) < 2:
            return None, None, float("inf")
        best_idx = None
        best_proj = None
        best_dist = float("inf")
        n = len(polygon)
        for i in range(n):
            start_point = polygon[i]
            end_point = polygon[(i + 1) % n]
            line_vector = end_point - start_point
            point_vector = pos - start_point
            line_length_squared = (
                line_vector.x() ** 2 + line_vector.y() ** 2
            )
            if line_length_squared == 0:
                continue
            projection = (
                point_vector.x() * line_vector.x()
                + point_vector.y() * line_vector.y()
            ) / line_length_squared
            projection = max(0.0, min(1.0, projection))
            projection_point = QPointF(
                start_point.x() + projection * line_vector.x(),
                start_point.y() + projection * line_vector.y(),
            )
            perpendicular_distance = (pos - projection_point).manhattanLength()
            if perpendicular_distance < best_dist:
                best_dist = perpendicular_distance
                best_idx = i
                best_proj = projection_point
        return best_idx, best_proj, best_dist

    def find_annotation_and_handle_at(self, pos: QPointF, margin=10.0):
        """Find annotation and specific handle at given position."""
        eff_margin = (
            margin / max(0.1, float(self.scale))
            if getattr(self, "scale", None)
            else margin
        )
        for annotation in reversed(self.annotations):
            if not annotation.visible or not annotation.is_complete:
                continue

            if (
                annotation.mask is not None
                and np.any(annotation.mask)
                and not annotation.polygon
                and not annotation.rectangle
            ):
                ix, iy = int(round(pos.x())), int(round(pos.y()))
                mh, mw = annotation.mask.shape[:2]
                if 0 <= ix < mw and 0 <= iy < mh and annotation.mask[iy, ix] > 0:
                    return annotation, "move"

            if not annotation.polygon and annotation.rectangle:
                rect = annotation.rectangle
                handles = {
                    "top_left": rect.topLeft(),
                    "top_right": rect.topRight(),
                    "bottom_left": rect.bottomLeft(),
                    "bottom_right": rect.bottomRight(),
                    "top_center": QPointF(rect.center().x(), rect.top()),
                    "bottom_center": QPointF(rect.center().x(), rect.bottom()),
                    "left_center": QPointF(rect.left(), rect.center().y()),
                    "right_center": QPointF(rect.right(), rect.center().y()),
                }

                for handle_name, handle_pos in handles.items():
                    if (handle_pos - pos).manhattanLength() < eff_margin:
                        return annotation, handle_name

                if rect.contains(pos):
                    return annotation, "move"

            elif annotation.polygon:
                for i, point in enumerate(annotation.polygon):
                    if (point - pos).manhattanLength() < eff_margin:
                        return annotation, f"point_{i}"

                edge_idx, _, edge_dist = self._find_polygon_edge_at(
                    annotation.polygon, pos
                )
                if edge_idx is not None and edge_dist < eff_margin:
                    return annotation, f"edge_{edge_idx}"

                if annotation.polygon.containsPoint(pos, Qt.OddEvenFill):
                    return annotation, "move"

            elif annotation.points:
                if (annotation.points[0] - pos).manhattanLength() < eff_margin:
                    return annotation, "point_0"

            elif annotation.mask is not None:
                ix, iy = int(round(pos.x())), int(round(pos.y()))
                mh, mw = annotation.mask.shape[:2]
                if 0 <= ix < mw and 0 <= iy < mh and annotation.mask[iy, ix] > 0:
                    return annotation, "move"

        return None, None

    def handle_mouse_double_click(self, event: QMouseEvent, pos: QPoint | None = None):
        pos = event.position()
        for rect, annotation in self.label_rects:
            if rect.contains(pos):
                self.edit_annotation_label(annotation)
                break
        if event.button() == Qt.LeftButton:
            img_pos = self.widget_to_image_pos(event.position())
            eff_margin = (
                10.0 / max(0.1, float(self.scale))
                if getattr(self, "scale", None)
                else 10.0
            )

            if (
                self.current_annotation
                and self.mouse_mode == MouseMode.POLYGON
                and len(self.current_annotation.polygon) >= 3
            ):
                pts = list(self.current_annotation.polygon)
                while len(pts) > 3 and (pts[-1] - pts[-2]).manhattanLength() < 2.0:
                    pts.pop()
                self.current_annotation.polygon = QPolygonF(pts)
                self.current_annotation.is_complete = True
                self.finalize_annotation()
                self.current_annotation = None
                return

            self.selected_annotation, self.active_handle = (
                self.find_annotation_and_handle_at(img_pos)
            )

            if self.selected_annotation:
                if self.selected_annotation.polygon and self.active_handle:
                    if "point_" in self.active_handle:
                        index = int(self.active_handle.split("_")[1])
                        polygon = self.selected_annotation.polygon
                        if len(polygon) > 3:
                            self._push_undo_state()
                            polygon = QPolygonF(
                                [p for i, p in enumerate(polygon) if i != index]
                            )
                            self.selected_annotation.polygon = polygon
                            self.current_annotation = None
                            self.annotationUpdated.emit(self.selected_annotation)
                            self.update()
                            logger.info(f"Removed point at index {index}")
                        return

                polygon = self.selected_annotation.polygon
                if polygon:
                    edge_idx, projection_point, perpendicular_distance = (
                        self._find_polygon_edge_at(polygon, img_pos)
                    )
                    if edge_idx is not None and perpendicular_distance < eff_margin:
                        self._push_undo_state()
                        pts = list(polygon)
                        pts.insert(edge_idx + 1, projection_point)
                        self.selected_annotation.polygon = QPolygonF(pts)
                        self.current_annotation = None
                        self.annotationUpdated.emit(self.selected_annotation)
                        self.update()
                        logger.info(
                            f"Inserted point at index {edge_idx + 1}: {projection_point}"
                        )
                        return

            for ann in self.annotations:
                self.annotationUpdated.emit(ann)
            self.update()

    def find_annotation_at(self, pos: QPointF):
        for ann in reversed(self.annotations):
            if not ann.visible:
                continue
            if (
                ann.mask is not None
                and np.any(ann.mask)
                and not ann.polygon
                and not ann.rectangle
            ):
                ix, iy = int(round(pos.x())), int(round(pos.y()))
                mh, mw = ann.mask.shape[:2]
                if 0 <= ix < mw and 0 <= iy < mh and ann.mask[iy, ix] > 0:
                    return ann
            elif ann.rectangle and ann.rectangle.contains(pos):
                return ann
            elif ann.polygon and ann.polygon.containsPoint(pos, Qt.OddEvenFill):
                return ann
            elif ann.points:
                for p in ann.points:
                    if QLineF(pos, p).length() < 5:
                        return ann
            elif ann.mask is not None and np.any(ann.mask):
                ix, iy = int(round(pos.x())), int(round(pos.y()))
                mh, mw = ann.mask.shape[:2]
                if 0 <= ix < mw and 0 <= iy < mh and ann.mask[iy, ix] > 0:
                    return ann
        return None
