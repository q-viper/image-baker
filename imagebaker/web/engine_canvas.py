from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF, QTransform

from imagebaker import logger
from imagebaker.core.defs import Annotation, DrawingState, LayerState
from imagebaker.plugins.discovery import discover_plugin_classes
from imagebaker.utils.state_utils import calculate_intermediate_states
from imagebaker.utils.transform_mask import mask_to_polygons, mask_to_rectangles
from imagebaker.web.models import WebCanvasItem, WebLayerItem, hex_to_qcolor


class WebEngineCanvasMixin:
    """Baker canvas, layer CRUD, grouping, geometry conversion, plugin, and timeline state operations."""

    # -------------------------------------------------------------------------
    # Baker Canvas & Layer Operations
    # -------------------------------------------------------------------------
    def reload_plugins(self):
        with self.lock:
            self.plugin_registry = discover_plugin_classes(self.project_dir)

    def manage_canvas(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            action = payload.get("action")
            if action == "create":
                idx = len(self.canvases) + 1
                name = (payload.get("name") or f"Canvas {idx}").strip() or f"Canvas {idx}"
                new_canvas = WebCanvasItem(name, self.canvas_config)
                self.canvases.append(new_canvas)
                self.current_canvas = new_canvas
                self.save_baker_cache()
                self.last_message = f"New canvas added: {name}"
                return True, self.last_message

            elif action == "select":
                cid = int(payload.get("canvas_id", -1))
                for c in self.canvases:
                    if c.canvas_id == cid:
                        self.current_canvas = c
                        self.save_baker_cache()
                        self.last_message = f"Selected canvas: {c.layer_name}"
                        return True, self.last_message
                return False, "Canvas not found."

            elif action == "delete":
                cid = int(payload.get("canvas_id", -1))
                target = next((c for c in self.canvases if c.canvas_id == cid), None)
                if target is None:
                    return False, "Canvas not found."
                self.canvases.remove(target)
                if not self.canvases:
                    fallback = WebCanvasItem("Canvas 1", self.canvas_config)
                    self.canvases.append(fallback)
                self.current_canvas = self.canvases[-1]
                self.save_baker_cache()
                self.last_message = f"Deleted canvas: {target.layer_name}"
                return True, self.last_message

            return False, f"Unknown canvas action: {action}"

    def add_blank_layer(
        self,
        width: int | None = None,
        height: int | None = None,
        label: str | None = None,
    ) -> tuple[bool, str]:
        with self.lock:
            if self.current_canvas is None:
                return False, "No active canvas."
            self.current_canvas.push_undo_state()
            new_layer = WebLayerItem(self.canvas_config)
            base_name = label or f"Layer {len(self.current_canvas.layers) + 1}"
            new_layer.layer_name = f"{len(self.current_canvas.layers) + 1}_{base_name}"
            new_layer.annotations = [
                Annotation(
                    annotation_id=0,
                    label=label or "New Annotation",
                    color=QColor(255, 255, 255),
                )
            ]
            w = max(32, int(width or self.current_canvas.viewport_width))
            h = max(32, int(height or self.current_canvas.viewport_height))
            blank = QPixmap(w, h)
            blank.fill(Qt.transparent)
            new_layer.set_image(blank)
            new_layer.position = QPointF(0, 0)
            new_layer.order = len(self.current_canvas.layers)
            self.current_canvas.layers.append(new_layer)
            self.save_baker_cache()
            self.last_message = f"Added new layer: {new_layer.layer_name}"
            return True, self.last_message

    def update_baker_layers(
        self,
        layers_payload: list[dict[str, Any]],
        push_undo: bool = False,
        message: str | None = None,
    ) -> tuple[bool, str]:
        with self.lock:
            if self.current_canvas is None:
                return False, "No active canvas."
            if push_undo:
                self.current_canvas.push_undo_state()

            # Synchronize layer list membership & order
            payload_lids = [
                int(item["layer_id"])
                for item in layers_payload
                if "layer_id" in item and item["layer_id"] is not None
            ]
            id_map = {layer.layer_id: layer for layer in self.current_canvas.layers}
            self.current_canvas.layers = [id_map[lid] for lid in payload_lids if lid in id_map]
            for idx, layer in enumerate(self.current_canvas.layers):
                layer.order = idx

            for item in layers_payload:
                lid = int(item.get("layer_id", -1))
                layer = self.current_canvas.get_layer(lid)
                if layer is None:
                    continue

                if "position" in item and item["position"] is not None:
                    pos = item["position"]
                    layer.position = QPointF(float(pos[0]), float(pos[1]))
                if "rotation" in item and item["rotation"] is not None:
                    layer.rotation = float(item["rotation"]) % 360.0
                if "scale_x" in item and item["scale_x"] is not None:
                    layer.scale_x = float(item["scale_x"])
                if "scale_y" in item and item["scale_y"] is not None:
                    layer.scale_y = float(item["scale_y"])
                if "opacity" in item and item["opacity"] is not None:
                    layer.opacity = float(item["opacity"])
                if "visible" in item and item["visible"] is not None:
                    layer.visible = bool(item["visible"])
                if "selected" in item and item["selected"] is not None:
                    layer.selected = bool(item["selected"])
                if "allow_annotation_export" in item and item["allow_annotation_export"] is not None:
                    layer.allow_annotation_export = bool(item["allow_annotation_export"])
                if "caption" in item and item["caption"] is not None:
                    layer.caption = str(item["caption"])

                edge_changed = False
                if "edge_opacity" in item and item["edge_opacity"] is not None:
                    new_eo = int(item["edge_opacity"])
                    if new_eo != layer.edge_opacity:
                        layer.edge_opacity = new_eo
                        edge_changed = True
                if "edge_width" in item and item["edge_width"] is not None:
                    new_ew = int(item["edge_width"])
                    if new_ew != layer.edge_width:
                        layer.edge_width = new_ew
                        edge_changed = True
                if edge_changed:
                    layer._apply_edge_opacity()

                if "drawing_states" in item and item["drawing_states"] is not None:
                    ds_list = []
                    for ds in item["drawing_states"]:
                        col = hex_to_qcolor(ds.get("color", "#ff0000"))
                        sz = int(ds.get("size", 5))
                        if "points" in ds and isinstance(ds["points"], list):
                            for pt in ds["points"]:
                                ds_list.append(
                                    DrawingState(
                                        position=QPointF(float(pt[0]), float(pt[1])),
                                        color=col,
                                        size=sz,
                                    )
                                )
                        else:
                            pos = ds.get("position", [0, 0])
                            ds_list.append(
                                DrawingState(
                                    position=QPointF(float(pos[0]), float(pos[1])),
                                    color=col,
                                    size=sz,
                                )
                            )
                    layer.drawing_states = ds_list

            if message:
                self.last_message = message
            self.save_baker_cache()
            return True, self.last_message

    def reorder_baker_layers(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            if self.current_canvas is None:
                return False, "No active canvas."
            layers = self.current_canvas.layers
            if not layers:
                return False, "No layers to reorder."

            if "order" in payload and isinstance(payload["order"], list):
                self.current_canvas.push_undo_state()
                id_map = {str(layer.layer_id): layer for layer in layers}
                new_layers = [id_map[str(lid)] for lid in payload["order"] if str(lid) in id_map]
                for layer in layers:
                    if layer not in new_layers:
                        new_layers.append(layer)
                for idx, layer in enumerate(new_layers):
                    layer.order = idx
                self.current_canvas.layers = new_layers
                self.save_baker_cache()
                self.last_message = "Reordered layers."
                return True, self.last_message

            direction = payload.get("direction", "up")
            lid = payload.get("layer_id")
            if lid is not None:
                selected = next((lyr for lyr in layers if str(lyr.layer_id) == str(lid)), None)
            else:
                selected = next((lyr for lyr in layers if lyr.selected), None)
            if selected is None:
                return False, "Select a layer to move."
            self.current_canvas.push_undo_state()
            idx = layers.index(selected)
            if direction == "up":
                if idx > 0:
                    layers.insert(idx - 1, layers.pop(idx))
                else:
                    layers.append(layers.pop(0))
                self.last_message = f"Moved layer {selected.layer_name} up in order."
            else:
                if idx < len(layers) - 1:
                    layers.insert(idx + 1, layers.pop(idx))
                else:
                    layers.insert(0, layers.pop(-1))
                self.last_message = f"Moved layer {selected.layer_name} down in order."

            for i, layer in enumerate(layers):
                layer.order = i
            self.save_baker_cache()
            return True, self.last_message

    def baker_layer_action(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            if self.current_canvas is None:
                return False, "No active canvas."
            action = payload.get("action")
            canvas = self.current_canvas

            if action == "undo":
                ok, msg = canvas.undo()
                if ok:
                    self.save_baker_cache()
                self.last_message = msg
                return ok, msg

            elif action == "redo":
                ok, msg = canvas.redo()
                if ok:
                    self.save_baker_cache()
                self.last_message = msg
                return ok, msg

            elif action == "copy":
                lids = payload.get("layer_ids")
                if lids is not None and isinstance(lids, (list, tuple)) and len(lids) > 0:
                    target_ids = {str(x) for x in lids}
                    for lyr in canvas.layers:
                        lyr.selected = str(lyr.layer_id) in target_ids
                selected = [lyr for lyr in canvas.layers if lyr.selected]
                if not selected:
                    self.last_message = "No layer selected to copy."
                    return False, self.last_message
                canvas.copied_layers = [lyr.copy() for lyr in selected]
                canvas.copied_layer = canvas.copied_layers[0]
                self.last_message = f"Copied {len(selected)} layer(s)."
                return True, self.last_message

            elif action == "paste":
                copied_list = getattr(canvas, "copied_layers", None) or ([canvas.copied_layer] if canvas.copied_layer else [])
                if not copied_list:
                    self.last_message = "No layer copied to paste."
                    return False, self.last_message
                canvas.push_undo_state()
                for lyr in canvas.layers:
                    lyr.selected = False
                pasted_names = []
                for copied in copied_list:
                    new_layer = copied.clone_as_new()
                    new_layer.position = QPointF(
                        new_layer.position.x() + 15.0, new_layer.position.y() + 15.0
                    )
                    new_layer.layer_name = f"{len(canvas.layers) + 1}_{new_layer.layer_name}"
                    new_layer.selected = True
                    new_layer.order = len(canvas.layers)
                    canvas.layers.append(new_layer)
                    pasted_names.append(new_layer.layer_name)
                self.save_baker_cache()
                self.last_message = f"Pasted {len(pasted_names)} layer(s)."
                return True, self.last_message

            elif action == "delete":
                lid = payload.get("layer_id")
                lids = payload.get("layer_ids")
                if lids is not None and isinstance(lids, (list, tuple)) and len(lids) > 0:
                    target_ids = {str(x) for x in lids}
                    targets = [lyr for lyr in canvas.layers if str(lyr.layer_id) in target_ids]
                elif lid is not None:
                    targets = [lyr for lyr in canvas.layers if str(lyr.layer_id) == str(lid)]
                else:
                    targets = [lyr for lyr in canvas.layers if lyr.selected]
                if not targets:
                    self.last_message = "No layer selected to delete."
                    return False, self.last_message
                canvas.push_undo_state()
                target_ids = {lyr.layer_id for lyr in targets}
                canvas.layers = [lyr for lyr in canvas.layers if lyr.layer_id not in target_ids]
                for i, lyr in enumerate(canvas.layers):
                    lyr.order = i
                self.save_baker_cache()
                self.last_message = f"Deleted {len(targets)} layer(s)."
                return True, self.last_message

            elif action == "group":
                lids = payload.get("layer_ids")
                if lids is not None and isinstance(lids, (list, tuple)) and len(lids) > 0:
                    target_ids = {str(x) for x in lids}
                    for lyr in canvas.layers:
                        lyr.selected = str(lyr.layer_id) in target_ids
                ok, msg = self._group_or_ungroup_selected_layers()
                if ok:
                    self.save_baker_cache()
                return ok, msg

            elif action == "ungroup":
                lid = payload.get("layer_id")
                lids = payload.get("layer_ids")
                if lids is not None and isinstance(lids, (list, tuple)) and len(lids) > 0:
                    target_ids = {str(x) for x in lids}
                    targets = [lyr for lyr in canvas.layers if str(lyr.layer_id) in target_ids and len(lyr.layers) >= 2]
                elif lid is not None:
                    targets = [lyr for lyr in canvas.layers if str(lyr.layer_id) == str(lid) and len(lyr.layers) >= 2]
                else:
                    targets = [lyr for lyr in canvas.layers if lyr.selected and len(lyr.layers) >= 2]
                if not targets:
                    self.last_message = "No grouped layer selected to ungroup."
                    return False, self.last_message
                canvas.push_undo_state()
                for lyr in list(targets):
                    self._ungroup_layer(lyr, push_undo=False)
                self.save_baker_cache()
                self.last_message = f"Ungrouped {len(targets)} group layer(s)."
                return True, self.last_message

            elif action in ("convert_ann_type", "convert_annotation_type"):
                ok, msg = self._convert_selected_annotation_type()
                if ok:
                    self.save_baker_cache()
                return ok, msg

            return False, f"Unknown layer action: {action}"

    # -------------------------------------------------------------------------
    # Grouping / Ungrouping & Convert Annotation Type
    # -------------------------------------------------------------------------
    @staticmethod
    def _compose_layer_transform(layer: WebLayerItem) -> QTransform:
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
    def _map_annotation_to_group(ann: Annotation, layer_transform: QTransform) -> Annotation:
        mapped = ann.copy()
        if mapped.rectangle:
            mapped.rectangle = layer_transform.mapRect(mapped.rectangle)
        if mapped.polygon:
            mapped.polygon = layer_transform.map(mapped.polygon)
        if mapped.points:
            mapped.points = [layer_transform.map(p) for p in mapped.points]
        return mapped

    def _group_or_ungroup_selected_layers(self) -> tuple[bool, str]:
        canvas = self.current_canvas
        selected_layers = [lyr for lyr in canvas.layers if lyr.selected]
        # If single layer selected and it's a group, or all selected layers are groups, ungroup them
        if selected_layers and all(len(lyr.layers) >= 2 for lyr in selected_layers):
            canvas.push_undo_state()
            messages = []
            for lyr in list(selected_layers):
                ok, msg = self._ungroup_layer(lyr, push_undo=False)
                if ok:
                    messages.append(msg)
            if messages:
                self.last_message = "; ".join(messages)
                return True, self.last_message

        if len(selected_layers) != 2:
            self.last_message = "Select exactly 2 layers to group (or a grouped layer to ungroup)."
            return False, self.last_message

        indices = sorted(canvas.layers.index(lyr) for lyr in selected_layers)
        ordered_layers = [canvas.layers[i] for i in indices]

        union_rect = None
        for layer in ordered_layers:
            if layer.image.isNull():
                self.last_message = "Cannot group layers with empty images."
                return False, self.last_message
            t_rect = self._compose_layer_transform(layer).mapRect(
                QRectF(QPointF(0, 0), layer.original_size)
            )
            union_rect = t_rect if union_rect is None else union_rect.united(t_rect)

        if union_rect is None or union_rect.width() <= 0 or union_rect.height() <= 0:
            self.last_message = "Unable to group selected layers."
            return False, self.last_message

        canvas.push_undo_state()
        group_w = max(1, int(math.ceil(union_rect.width())))
        group_h = max(1, int(math.ceil(union_rect.height())))

        composed = QPixmap(group_w, group_h)
        composed.fill(Qt.transparent)
        painter = QPainter(composed)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        try:
            for layer in ordered_layers:
                local_tf = QTransform()
                local_tf.translate(
                    layer.position.x() - union_rect.left(),
                    layer.position.y() - union_rect.top(),
                )
                local_tf.rotate(layer.rotation)
                local_tf.scale(layer.scale_x, layer.scale_y)

                painter.save()
                painter.setTransform(local_tf, combine=False)
                painter.setOpacity(max(0.0, min(1.0, layer.opacity / 255.0)))
                painter.drawPixmap(0, 0, layer.image)
                for st in layer.layer_state.drawing_states:
                    painter.setPen(
                        QPen(st.color, st.size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                    )
                    painter.drawPoint(st.position)
                painter.restore()
        finally:
            painter.end()

        grouped = ordered_layers[-1].clone_as_new()
        grouped.set_image(composed)
        grouped.position = QPointF(union_rect.left(), union_rect.top())
        grouped.rotation = 0.0
        grouped.scale_x = 1.0
        grouped.scale_y = 1.0
        grouped.opacity = 255
        grouped.visible = True
        grouped.selected = True
        grouped.allow_annotation_export = any(
            lyr.allow_annotation_export for lyr in ordered_layers
        )
        grouped.layer_name = f"Group({ordered_layers[0].layer_name}, {ordered_layers[1].layer_name})"
        grouped.caption = f"Grouped: {ordered_layers[0].layer_name}, {ordered_layers[1].layer_name}"
        grouped.layers = []
        grouped.plugins = []

        merged_annotations: list[Annotation] = []
        for layer in ordered_layers:
            child_copy = layer.copy()
            child_copy.selected = False
            child_copy.position = child_copy.position - QPointF(union_rect.left(), union_rect.top())
            grouped.layers.append(child_copy)
            grouped.plugins.extend(
                [p.copy() if hasattr(p, "copy") else p for p in getattr(layer, "plugins", [])]
            )
            ann_tf = QTransform()
            ann_tf.translate(
                layer.position.x() - union_rect.left(),
                layer.position.y() - union_rect.top(),
            )
            ann_tf.rotate(layer.rotation)
            ann_tf.scale(layer.scale_x, layer.scale_y)
            for ann in layer.annotations:
                mapped = self._map_annotation_to_group(ann, ann_tf)
                mapped.selected = False
                mapped.file_path = grouped.file_path
                merged_annotations.append(mapped)

        if not merged_annotations:
            merged_annotations = [
                Annotation(annotation_id=0, label="Grouped", color=QColor(255, 255, 255))
            ]
        for idx, ann in enumerate(merged_annotations):
            ann.annotation_id = idx
        grouped.annotations = merged_annotations

        for lyr in canvas.layers:
            lyr.selected = False
        insert_idx = indices[-1]
        for idx in reversed(indices):
            del canvas.layers[idx]
            if idx < insert_idx:
                insert_idx -= 1
        canvas.layers.insert(insert_idx, grouped)
        for order, lyr in enumerate(canvas.layers):
            lyr.order = order

        self.last_message = f"Grouped layers: {ordered_layers[0].layer_name} + {ordered_layers[1].layer_name}"
        return True, self.last_message

    def _ungroup_layer(self, grouped_layer: WebLayerItem, push_undo: bool = True) -> tuple[bool, str]:
        canvas = self.current_canvas
        if grouped_layer not in canvas.layers:
            return False, "Grouped layer not found in canvas."
        if len(grouped_layer.layers) < 2:
            return False, "Selected layer is not a grouped layer."
        if push_undo:
            canvas.push_undo_state()
        group_idx = canvas.layers.index(grouped_layer)
        group_tf = self._compose_layer_transform(grouped_layer)

        existing_ids = {
            lyr.layer_id for lyr in canvas.layers if lyr is not grouped_layer
        }
        restored: list[WebLayerItem] = []
        for child_rel in grouped_layer.layers:
            if child_rel.layer_id not in existing_ids:
                child = child_rel.copy()
                existing_ids.add(child.layer_id)
            else:
                child = child_rel.clone_as_new()
                existing_ids.add(child.layer_id)
            child_local_tf = self._compose_layer_transform(child)
            world_tf = group_tf * child_local_tf
            pos, rot, sx, sy = self._decompose_transform(world_tf)
            child.position = pos
            child.rotation = rot
            child.scale_x = sx
            child.scale_y = sy
            child.opacity = int(round((child.opacity * grouped_layer.opacity) / 255.0))
            child.visible = grouped_layer.visible and child.visible
            child.selected = True
            restored.append(child)

        del canvas.layers[group_idx]
        for offset, child in enumerate(restored):
            canvas.layers.insert(group_idx + offset, child)

        for lyr in canvas.layers:
            lyr.selected = False
        if restored:
            for child in restored:
                child.selected = True
        for order, lyr in enumerate(canvas.layers):
            lyr.order = order

        self.last_message = f"Ungrouped layer: {grouped_layer.layer_name}"
        return True, self.last_message

    def _convert_selected_annotation_type(self) -> tuple[bool, str]:
        canvas = self.current_canvas
        if not canvas.layers:
            self.last_message = "No layers available."
            return False, self.last_message
        targets = [lyr for lyr in canvas.layers if lyr.selected]
        if not targets:
            self.last_message = "Select one or more layers to convert annotation type."
            return False, self.last_message

        canvas.push_undo_state()
        converted = 0
        skipped = 0
        for layer in targets:
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
                    [rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]
                )
                ann.rectangle = None
                ann.points = []
                ann.mask = None
                converted += 1
            elif ann.mask is not None and np.any(ann.mask):
                polys = mask_to_polygons(ann.mask, min_polygon_area=2, merge_polygons=False)
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

        self.last_message = f"Converted {converted} annotation(s). Skipped {skipped} layer(s)."
        return True, self.last_message

    # -------------------------------------------------------------------------
    # Baker Plugins & Timeline States
    # -------------------------------------------------------------------------
    def manage_plugins(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            action = payload.get("action")
            canvas = self.current_canvas
            if action == "reload":
                self.reload_plugins()
                self.last_message = f"Discovered {len(self.plugin_registry)} plugin option(s)."
                return True, self.last_message

            elif action == "clear":
                targets = [lyr for lyr in canvas.layers if lyr.selected]
                if not targets:
                    self.last_message = "Select at least one layer to remove plugins."
                    return False, self.last_message
                canvas.push_undo_state()
                removed = 0
                for lyr in targets:
                    removed += len(lyr.plugins)
                    lyr.plugins = []
                    lyr.bump_revision()
                self.last_message = f"Removed {removed} plugin instance(s)."
                return True, self.last_message

            elif action == "set":
                plugin_names = payload.get("plugins") or []
                plugin_classes = [
                    self.plugin_registry[name]
                    for name in plugin_names
                    if name in self.plugin_registry
                ]
                selected_layers = [lyr for lyr in canvas.layers if lyr.selected]
                applied_to_all = False
                if not selected_layers:
                    if not canvas.layers:
                        return False, "No layers available."
                    selected_layers = list(canvas.layers)
                    applied_to_all = True

                canvas.push_undo_state()
                for layer in selected_layers:
                    current_map = {type(p): p for p in layer.plugins}
                    new_plugins = []
                    for cls in plugin_classes:
                        if cls in current_map:
                            existing = current_map[cls]
                            existing.enabled = True
                            new_plugins.append(existing)
                        else:
                            try:
                                new_plugins.append(cls())
                            except Exception as err:
                                logger.error(f"Failed to instantiate plugin {cls}: {err}")
                    layer.plugins = new_plugins
                    layer.bump_revision()

                if applied_to_all:
                    self.last_message = "No layer selected. Applied plugin options to all layers."
                else:
                    self.last_message = f"Updated plugins on {len(selected_layers)} selected layer(s)."
                return True, self.last_message

            return False, f"Unknown plugin action: {action}"

    def manage_states(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            action = payload.get("action")
            canvas = self.current_canvas
            if canvas is None:
                return False, "No active canvas."

            if action == "save":
                steps = max(1, int(payload.get("steps", 1)))
                start_step = (max(canvas.states.keys()) + 1) if canvas.states else 0
                curr_states: dict[int, list[LayerState]] = {}

                for layer in canvas.layers:
                    inter_states = calculate_intermediate_states(
                        layer.previous_state, layer.layer_state.copy(), steps
                    )
                    is_sel = layer.selected
                    for local_step, st in enumerate(inter_states):
                        state_step = start_step + local_step
                        st.selected = False
                        st.drawing_states = [
                            DrawingState(
                                position=QPointF(d.position),
                                color=QColor(d.color),
                                size=d.size,
                            )
                            for d in layer.layer_state.drawing_states
                        ]
                        st = canvas.apply_plugins_to_state(layer, st, local_step, steps)
                        curr_states.setdefault(state_step, []).append(st)

                    layer.previous_state = layer.layer_state.copy()
                    layer.selected = is_sel

                for state_step, st_list in sorted(curr_states.items()):
                    canvas.states[state_step] = st_list
                    canvas.current_step = state_step

                canvas._current_step_index = canvas.state_step_index(canvas.current_step)
                for lyr in canvas.layers:
                    lyr.bump_revision()

                self.save_baker_cache()
                self.last_message = (
                    f"State saved. Total states: {len(canvas.states)} | "
                    f"Steps: {steps} | Current step: {canvas.current_step}"
                )
                return True, self.last_message

            elif action == "randomize":
                if not canvas.layers:
                    self.last_message = "No layers available to randomize."
                    return False, self.last_message
                num_states = max(1, int(payload.get("steps", 1)))
                canvas.states.clear()
                cw = max(1, canvas.viewport_width)
                ch = max(1, canvas.viewport_height)

                for step in range(num_states):
                    rand_states = []
                    for order, layer in enumerate(canvas.layers):
                        st = layer.layer_state.copy()
                        st.scale_x = random.uniform(0.5, 1.5)
                        st.scale_y = random.uniform(0.5, 1.5)
                        max_x = max(0.0, cw - (layer.image.width() * st.scale_x))
                        max_y = max(0.0, ch - (layer.image.height() * st.scale_y))
                        st.position = QPointF(
                            random.uniform(0.0, max_x),
                            random.uniform(0.0, max_y),
                        )
                        st.rotation = random.uniform(0.0, 360.0)
                        st.opacity = random.randint(128, 255)
                        st.order = order
                        st.selected = False
                        st.caption = layer.caption
                        st.drawing_states = [
                            DrawingState(
                                position=QPointF(d.position),
                                color=QColor(d.color),
                                size=d.size,
                            )
                            for d in layer.layer_state.drawing_states
                        ]
                        st = canvas.apply_plugins_to_state(layer, st, step, num_states)
                        rand_states.append(st)
                    canvas.states[step] = rand_states

                self._seek_canvas_state(0)
                self.save_baker_cache()
                self.last_message = f"Created {num_states} randomized state(s)."
                return True, self.last_message

            elif action == "seek":
                step = int(payload.get("step", 0))
                ok = self._seek_canvas_state(step)
                return ok, self.last_message

            elif action == "clear":
                canvas.states.clear()
                canvas.current_step = 0
                canvas._current_step_index = 0
                for layer in canvas.layers:
                    layer.previous_state = None
                    layer.bump_revision()
                self.save_baker_cache()
                self.last_message = "All states cleared."
                return True, self.last_message

            return False, f"Unknown state action: {action}"

    def _seek_canvas_state(self, requested_step: int) -> bool:
        canvas = self.current_canvas
        if not canvas or not canvas.states:
            return False
        step_key = (
            requested_step
            if requested_step in canvas.states
            else canvas.step_key_for_index(requested_step)
        )
        if step_key is None or step_key not in canvas.states:
            return False

        canvas.current_step = step_key
        canvas._current_step_index = canvas.state_step_index(step_key)
        for st in canvas.states[step_key]:
            layer = canvas.get_layer(st.layer_id, st.layer_name)
            if layer is not None:
                st.layer_id = layer.layer_id
                update_edge = (
                    layer.edge_width != st.edge_width or layer.edge_opacity != st.edge_opacity
                )
                layer.layer_state = st.copy()
                if update_edge:
                    layer._apply_edge_opacity()
                else:
                    layer.bump_revision()

        self.last_message = f"Seeking to step {step_key}"
        return True
