from __future__ import annotations

import io
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QSizeF
from PySide6.QtGui import (
    QColor,
    QImage,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig
from imagebaker.core.defs import (
    Annotation,
    DrawingState,
    LayerState,
)
from imagebaker.plugins.base_plugin import BasePlugin
from imagebaker.plugins.runtime import apply_pixel_plugins
from imagebaker.utils.image import qpixmap_to_numpy


def ensure_headless_qapp():
    """Ensure a QApplication exists (using offscreen platform if needed)."""
    app = QApplication.instance()
    if app is None:
        if sys.platform != 'win32' and not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
            os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        app = QApplication(sys.argv[:1])
    return app


def qcolor_to_hex(color: QColor) -> str:
    return f'#{color.red():02x}{color.green():02x}{color.blue():02x}'


def hex_to_qcolor(hex_or_rgb: str | list | tuple, alpha: int = 255) -> QColor:
    if isinstance(hex_or_rgb, (list, tuple)) and len(hex_or_rgb) >= 3:
        r, g, b = int(hex_or_rgb[0]), int(hex_or_rgb[1]), int(hex_or_rgb[2])
        a = int(hex_or_rgb[3]) if len(hex_or_rgb) >= 4 else alpha
        return QColor(r, g, b, a)
    s = str(hex_or_rgb or '#ffffff').strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(ch * 2 for ch in s)
    if len(s) >= 6:
        try:
            r = int(s[0:2], 16)
            g = int(s[2:4], 16)
            b = int(s[4:6], 16)
            return QColor(r, g, b, alpha)
        except ValueError:
            pass
    return QColor(255, 255, 255, alpha)


def qimage_to_png_bytes(image: QImage | QPixmap) -> bytes:
    arr = qpixmap_to_numpy(image)
    pil_img = Image.fromarray(arr, mode='RGBA')
    buf = io.BytesIO()
    pil_img.save(buf, format='PNG')
    return buf.getvalue()


@dataclass
class WebImageEntry:
    is_baked_result: bool
    file_path: Path
    width: int = 0
    height: int = 0

    @property
    def name(self) -> str:
        return self.file_path.name


class WebLayerItem:
    """
    Headless representation of a Baker layer, compatible with BasePlugin,
    apply_pixel_plugins, calculate_intermediate_states, and BakerWorker logic.
    """

    _next_id = 1

    def __init__(self, config: CanvasConfig):
        self.id = WebLayerItem._next_id
        WebLayerItem._next_id += 1
        self.config = config
        self.layer_state = LayerState(layer_id=self.id)
        self.previous_state: LayerState | None = None
        self.file_path: Path = Path("Runtime")
        self._image = QPixmap()
        self._original_image = QPixmap()
        self.original_size = QSizeF(0, 0)
        self.annotations: list[Annotation] = []
        self.layers: list[WebLayerItem] = []
        self.plugins: list[BasePlugin] = []
        self.revision: int = 1
        self._plugin_render_cache: dict[tuple, bytes] = {}

    def bump_revision(self):
        self.revision += 1
        self._plugin_render_cache.clear()

    def set_image(self, image_source: Path | QPixmap | QImage):
        if isinstance(image_source, Path):
            self.file_path = image_source
            if image_source.exists():
                self._image = QPixmap(str(image_source))
        elif isinstance(image_source, QPixmap):
            self._image = image_source.copy()
        elif isinstance(image_source, QImage):
            self._image = QPixmap.fromImage(image_source)

        self._original_image = self._image.copy()
        self.original_size = QSizeF(self._image.size())
        self.bump_revision()

    @property
    def image(self) -> QPixmap:
        return self._image

    @image.setter
    def image(self, value: QPixmap):
        self._image = value
        self.bump_revision()

    def _apply_edge_opacity(self):
        """Fast vectorized edge opacity feathering matching BaseLayer._apply_edge_opacity."""
        if self._original_image.isNull():
            return

        edge_width = int(self.edge_width)
        edge_opacity = int(self.edge_opacity)
        if edge_width <= 0 or edge_opacity >= 255:
            self._image = self._original_image.copy()
            self.bump_revision()
            return

        annotation = self.annotations[0] if self.annotations else None
        if annotation is None:
            self._image = self._original_image.copy()
            self.bump_revision()
            return

        arr = qpixmap_to_numpy(self._original_image).copy()
        height, width = arr.shape[:2]
        if height <= 0 or width <= 0:
            return

        alpha = arr[:, :, 3].astype(np.float32)
        non_zero = alpha > 0
        if not np.any(non_zero):
            return

        if annotation.rectangle is not None:
            xs = np.minimum(np.arange(width), width - 1 - np.arange(width))[None, :]
            ys = np.minimum(np.arange(height), height - 1 - np.arange(height))[:, None]
            dist = np.minimum(xs, ys).astype(np.float32)
            in_edge = non_zero & (dist < edge_width)
            factor = np.clip((edge_width - dist) / float(edge_width), 0.0, 1.0)
            scale = (1.0 - factor) + (factor * (edge_opacity / 255.0))
            new_alpha = np.where(in_edge, alpha * scale, alpha)
            arr[:, :, 3] = np.clip(new_alpha, 0, 255).astype(np.uint8)
        elif annotation.polygon is not None or annotation.mask is not None:
            binary = np.where(non_zero, 255, 0).astype(np.uint8)
            dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
            # Subtract 1 so boundary pixels have distance 0 like pointPolygonTest
            dist = np.maximum(0.0, dist - 1.0)
            in_edge = non_zero & (dist < edge_width)
            factor = np.clip((edge_width - dist) / float(edge_width), 0.0, 1.0)
            scale = (1.0 - factor) + (factor * (edge_opacity / 255.0))
            new_alpha = np.where(in_edge, alpha * scale, alpha)
            arr[:, :, 3] = np.clip(new_alpha, 0, 255).astype(np.uint8)

        arr = np.ascontiguousarray(arr)
        qimg = QImage(arr.data, width, height, width * 4, QImage.Format_RGBA8888)
        self._image = QPixmap.fromImage(qimg.copy())
        self.bump_revision()

    def copy(self) -> WebLayerItem:
        cloned = WebLayerItem(self.config)
        cloned.id = self.id
        cloned.layer_state = self.layer_state.copy()
        cloned.previous_state = self.previous_state.copy() if self.previous_state else None
        cloned._image = self._image.copy()
        cloned._original_image = self._original_image.copy()
        cloned.original_size = QSizeF(self.original_size)
        cloned.file_path = Path(self.file_path)
        cloned.annotations = [ann.copy() for ann in self.annotations]
        cloned.layers = [child.copy() for child in self.layers]
        cloned.plugins = [
            p.copy() if hasattr(p, "copy") else p for p in self.plugins
        ]
        cloned.revision = self.revision
        return cloned

    def clone_as_new(self) -> WebLayerItem:
        cloned = self.copy()
        cloned.id = WebLayerItem._next_id
        WebLayerItem._next_id += 1
        cloned.layer_id = cloned.id
        return cloned

    # Property delegators matching BaseLayer
    @property
    def layer_id(self) -> int:
        return self.layer_state.layer_id

    @layer_id.setter
    def layer_id(self, value: int):
        self.layer_state.layer_id = value

    @property
    def layer_name(self) -> str:
        return self.layer_state.layer_name

    @layer_name.setter
    def layer_name(self, value: str):
        self.layer_state.layer_name = value

    @property
    def position(self) -> QPointF:
        return self.layer_state.position

    @position.setter
    def position(self, value: QPointF):
        self.layer_state.position = value

    @property
    def rotation(self) -> float:
        return self.layer_state.rotation

    @rotation.setter
    def rotation(self, value: float):
        self.layer_state.rotation = value

    @property
    def scale(self) -> float:
        return self.layer_state.scale

    @scale.setter
    def scale(self, value: float):
        self.layer_state.scale = value

    @property
    def scale_x(self) -> float:
        return self.layer_state.scale_x

    @scale_x.setter
    def scale_x(self, value: float):
        self.layer_state.scale_x = value

    @property
    def scale_y(self) -> float:
        return self.layer_state.scale_y

    @scale_y.setter
    def scale_y(self, value: float):
        self.layer_state.scale_y = value

    @property
    def order(self) -> int:
        return self.layer_state.order

    @order.setter
    def order(self, value: int):
        self.layer_state.order = value

    @property
    def visible(self) -> bool:
        return self.layer_state.visible

    @visible.setter
    def visible(self, value: bool):
        self.layer_state.visible = value

    @property
    def allow_annotation_export(self) -> bool:
        return self.layer_state.allow_annotation_export

    @allow_annotation_export.setter
    def allow_annotation_export(self, value: bool):
        self.layer_state.allow_annotation_export = value

    @property
    def selected(self) -> bool:
        return self.layer_state.selected

    @selected.setter
    def selected(self, value: bool):
        self.layer_state.selected = value

    @property
    def opacity(self) -> float:
        return self.layer_state.opacity

    @opacity.setter
    def opacity(self, value: float):
        self.layer_state.opacity = value

    @property
    def drawing_states(self) -> list[DrawingState]:
        return self.layer_state.drawing_states

    @drawing_states.setter
    def drawing_states(self, value: list[DrawingState]):
        self.layer_state.drawing_states = value

    @property
    def edge_opacity(self) -> int:
        return self.layer_state.edge_opacity

    @edge_opacity.setter
    def edge_opacity(self, value: int):
        self.layer_state.edge_opacity = int(value)

    @property
    def edge_width(self) -> int:
        return self.layer_state.edge_width

    @edge_width.setter
    def edge_width(self, value: int):
        self.layer_state.edge_width = int(value)

    @property
    def caption(self) -> str:
        return self.layer_state.caption

    @caption.setter
    def caption(self, value: str):
        self.layer_state.caption = value


class WebCanvasItem:
    """Headless representation of a Baker CanvasLayer."""

    _next_id = 1

    def __init__(self, name: str, config: CanvasConfig):
        self.canvas_id = WebCanvasItem._next_id
        WebCanvasItem._next_id += 1
        self.layer_name = name
        self.config = config
        self.layers: list[WebLayerItem] = []
        self.states: dict[int, list[LayerState]] = {}
        self.current_step: int = 0
        self._current_step_index: int = 0
        self.copied_layer: WebLayerItem | None = None
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._max_history = 100
        self.viewport_width = 960
        self.viewport_height = 640

    def get_layer(self, layer_id: int | str) -> WebLayerItem | None:
        try:
            target_id = int(layer_id)
        except (ValueError, TypeError):
            target_id = None
        for layer in self.layers:
            if (target_id is not None and layer.layer_id == target_id) or str(layer.layer_id) == str(layer_id):
                return layer
        return None

    def _snapshot_layers(self) -> dict:
        snapshot_layers = []
        selected_indices = []
        for idx, layer in enumerate(self.layers):
            layer_copy = layer.copy()
            layer_copy.selected = layer.selected
            if layer.selected:
                selected_indices.append(idx)
            snapshot_layers.append(layer_copy)
        return {
            "layers": snapshot_layers,
            "selected_indices": selected_indices,
        }

    def _restore_layers(self, snapshot: dict):
        restored_layers = [layer.copy() for layer in snapshot.get("layers", [])]
        selected_indices = set(snapshot.get("selected_indices", []))
        for idx, layer in enumerate(restored_layers):
            layer.selected = idx in selected_indices
            layer.bump_revision()
        self.layers = restored_layers

    def push_undo_state(self):
        self._undo_stack.append(self._snapshot_layers())
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> tuple[bool, str]:
        if not self._undo_stack:
            return False, "Nothing to undo."
        self._redo_stack.append(self._snapshot_layers())
        snapshot = self._undo_stack.pop()
        self._restore_layers(snapshot)
        return True, "Undo applied."

    def redo(self) -> tuple[bool, str]:
        if not self._redo_stack:
            return False, "Nothing to redo."
        self._undo_stack.append(self._snapshot_layers())
        snapshot = self._redo_stack.pop()
        self._restore_layers(snapshot)
        return True, "Redo applied."

    def ordered_state_steps(self) -> list[int]:
        return sorted(self.states.keys())

    def state_step_index(self, step_key: int) -> int:
        steps = self.ordered_state_steps()
        try:
            return steps.index(step_key)
        except ValueError:
            return 0

    def step_key_for_index(self, step_index: int) -> int | None:
        steps = self.ordered_state_steps()
        if not steps:
            return None
        idx = max(0, min(len(steps) - 1, int(step_index)))
        return steps[idx]

    def apply_plugins_to_state(
        self,
        layer: WebLayerItem,
        state: LayerState,
        step: int,
        total_steps: int,
    ) -> LayerState:
        for plugin in getattr(layer, "plugins", []):
            if not getattr(plugin, "enabled", True):
                continue
            try:
                updated = plugin.update(
                    state=state,
                    step=step,
                    total_steps=total_steps,
                    layer=layer,
                    canvas=self,
                )
                if updated is not None:
                    state = updated
            except Exception as err:
                logger.error(f"Plugin '{getattr(plugin, 'name', type(plugin).__name__)}' failed: {err}")
        return state

    def build_states_for_step(self, step: int, total_steps: int) -> list[LayerState]:
        built_states = []
        for order, layer in enumerate(self.layers):
            state = layer.layer_state.copy()
            state.order = order
            state.selected = False
            state.caption = layer.caption
            state.drawing_states = [
                DrawingState(position=QPointF(d.position), color=QColor(d.color), size=d.size)
                for d in layer.layer_state.drawing_states
            ]
            state = self.apply_plugins_to_state(layer, state, step, total_steps)
            built_states.append(state)
        return built_states

    def get_layer_render_pixmap(self, layer: WebLayerItem, step: int, total_steps: int) -> QPixmap:
        if not getattr(layer, "plugins", []):
            return layer.image
        return apply_pixel_plugins(
            layer=layer,
            step=step,
            total_steps=total_steps,
            canvas=self,
        )


@dataclass
class ImageUndoHistory:
    undo_stack: list[list[Annotation]] = field(default_factory=list)
    redo_stack: list[list[Annotation]] = field(default_factory=list)
    max_history: int = 100

    @staticmethod
    def _ann_sig(ann: Annotation) -> tuple:
        pts = tuple((round(p.x(), 3), round(p.y(), 3)) for p in (ann.points or []))
        rect = (
            (
                round(ann.rectangle.x(), 3),
                round(ann.rectangle.y(), 3),
                round(ann.rectangle.width(), 3),
                round(ann.rectangle.height(), 3),
            )
            if ann.rectangle is not None
            else None
        )
        poly = (
            tuple((round(p.x(), 3), round(p.y(), 3)) for p in ann.polygon)
            if ann.polygon is not None
            else None
        )
        mask_sig = (
            (ann.mask.shape, int(ann.mask.sum()))
            if ann.mask is not None
            else None
        )
        col = (
            (ann.color.red(), ann.color.green(), ann.color.blue())
            if ann.color is not None
            else (255, 255, 255)
        )
        return (
            ann.label,
            col,
            pts,
            rect,
            poly,
            mask_sig,
            bool(ann.visible),
            ann.caption or "",
        )

    @classmethod
    def annotations_equal(
        cls, before: list[Annotation], after: list[Annotation]
    ) -> bool:
        if len(before) != len(after):
            return False
        return all(
            cls._ann_sig(a) == cls._ann_sig(b) for a, b in zip(before, after, strict=False)
        )

    def push(self, annotations: list[Annotation]):
        snapshot = [ann.copy() for ann in annotations]
        if self.undo_stack and self.annotations_equal(self.undo_stack[-1], snapshot):
            self.redo_stack.clear()
            return
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()


