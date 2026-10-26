"""
Web Application Engine for ImageBaker.

Provides a cross-platform, headless-compatible state and rendering engine that mirrors
all features of the desktop Layerify, Baker, and Help tabs while reusing ImageBaker's
core data structures, plugins, models, and cache/export formats.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import os
import random
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure Qt can initialize headlessly on Linux/macOS/CI servers without an X display
if sys.platform != "win32" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QApplication

from imagebaker import __version__, logger
from imagebaker.core.configs import CanvasConfig, LayerConfig
from imagebaker.core.defs import (
    Annotation,
    BakingResult,
    DrawingState,
    Label,
    LayerState,
    PredictionResult,
)
from imagebaker.plugins.base_plugin import BasePlugin
from imagebaker.plugins.discovery import discover_plugin_classes
from imagebaker.plugins.runtime import apply_pixel_plugins
from imagebaker.utils.image import draw_annotations, qpixmap_to_numpy
from imagebaker.utils.state_utils import calculate_intermediate_states
from imagebaker.utils.transform_mask import mask_to_polygons, mask_to_rectangles
from imagebaker.window.app import find_and_import_subclass, load_models


def ensure_headless_qapp():
    """Ensure a QApplication exists (using offscreen platform if needed)."""
    app = QApplication.instance()
    if app is None:
        if sys.platform != "win32" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(sys.argv[:1])
    return app


def qcolor_to_hex(color: QColor) -> str:
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def hex_to_qcolor(hex_or_rgb: str | list | tuple, alpha: int = 255) -> QColor:
    if isinstance(hex_or_rgb, (list, tuple)) and len(hex_or_rgb) >= 3:
        r, g, b = int(hex_or_rgb[0]), int(hex_or_rgb[1]), int(hex_or_rgb[2])
        a = int(hex_or_rgb[3]) if len(hex_or_rgb) >= 4 else alpha
        return QColor(r, g, b, a)
    s = str(hex_or_rgb or "#ffffff").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
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
    pil_img = Image.fromarray(arr, mode="RGBA")
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
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

    def get_layer(self, layer_id: int) -> WebLayerItem | None:
        for layer in self.layers:
            if layer.layer_id == layer_id:
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

    def push(self, annotations: list[Annotation]):
        self.undo_stack.append([ann.copy() for ann in annotations])
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()


class WebAppEngine:
    """
    Core stateful engine for the ImageBaker standalone web app.
    """

    def __init__(
        self,
        models_file: str | None = "loaded_models.py",
        project_dir: str = ".",
        configs_file: str | None = "imagebaker/core/configs.py",
    ):
        ensure_headless_qapp()
        self.lock = threading.RLock()
        self.project_dir = Path(project_dir).resolve()
        self.theme_mode = "light"
        self.active_tab = "Layerify"
        self.last_message = "Ready"

        # Load Models
        models_file_path = Path(models_file) if models_file else None
        if models_file_path and not models_file_path.is_absolute():
            candidate = self.project_dir / models_file_path
            if candidate.is_file():
                models_file_path = candidate

        if models_file_path and models_file_path.is_file():
            loaded = load_models(str(models_file_path))
            self.loaded_models = loaded if loaded else {"None": None}
        else:
            if models_file_path:
                logger.warning(f"Models file not found: {models_file_path}")
            self.loaded_models = {"None": None}

        # Load Configs
        configs_file_path = Path(configs_file) if configs_file else None
        if configs_file_path and not configs_file_path.is_absolute():
            candidate = self.project_dir / configs_file_path
            if candidate.is_file():
                configs_file_path = candidate

        layer_config_cls = None
        canvas_config_cls = None
        if configs_file_path and configs_file_path.is_file():
            layer_config_cls = find_and_import_subclass(str(configs_file_path), "LayerConfig")
            canvas_config_cls = find_and_import_subclass(str(configs_file_path), "CanvasConfig")

        if layer_config_cls:
            self.layer_config: LayerConfig = layer_config_cls()
            if self.layer_config.project_dir == Path("."):
                self.layer_config.project_dir = self.project_dir
        else:
            self.layer_config = LayerConfig(project_dir=self.project_dir)

        if canvas_config_cls:
            self.canvas_config: CanvasConfig = canvas_config_cls()
            if self.canvas_config.project_dir == Path("."):
                self.canvas_config.project_dir = self.project_dir
        else:
            self.canvas_config = CanvasConfig(project_dir=self.project_dir)

        # Layerify state
        model_keys = [str(k) for k in self.loaded_models.keys()]
        self.current_model_name = model_keys[0] if model_keys else "None"
        self.current_label = self.layer_config.default_label.name
        self.image_entries: list[WebImageEntry] = []
        self.curr_image_idx: int = 0
        self.current_annotations: list[Annotation] = []
        self.annotation_clipboard: list[Annotation] = []
        self.image_histories: dict[str, ImageUndoHistory] = defaultdict(ImageUndoHistory)

        # Baker state
        self.canvases: list[WebCanvasItem] = []
        first_canvas = WebCanvasItem("Canvas 1", self.canvas_config)
        self.canvases.append(first_canvas)
        self.current_canvas: WebCanvasItem = first_canvas
        self.plugin_registry: dict[str, type[BasePlugin]] = {}
        self.reload_plugins()

        # Load default images
        self._load_images_from_folder(self.layer_config.assets_folder)
        if self.image_entries:
            self._select_image_by_index(0, save_previous=False)
            self.last_message = f"Showing image 1/{len(self.image_entries)}"
        else:
            self.last_message = "No images found in the assets folder."

    # -------------------------------------------------------------------------
    # Cache & Annotation Serialization Helpers
    # -------------------------------------------------------------------------
    def _cache_path_for_file(self, file_path: Path, base_dir: Path | None = None) -> Path:
        if base_dir is None:
            base_dir = self.layer_config.cache_dir
        normalized = str(Path(file_path))
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        safe_name = Path(file_path).name
        return base_dir / f"{safe_name}.{digest}.json"

    def _label_color(self, label_name: str) -> QColor:
        color = self.layer_config.get_label_color(label_name)
        return QColor(color.red(), color.green(), color.blue())

    def ensure_label_available(self, label_name: str, color: QColor | None = None) -> bool:
        if not label_name:
            return False
        existing_names = [lbl.name for lbl in self.layer_config.predefined_labels]
        if label_name in existing_names:
            return False
        self.layer_config.predefined_labels.append(
            Label(name=label_name, color=color or QColor(255, 255, 255))
        )
        return True

    def get_default_label(self) -> Label:
        if self.layer_config.predefined_labels:
            return self.layer_config.predefined_labels[0]
        return self.layer_config.default_label

    def normalize_annotation_colors(
        self, annotations: list[Annotation], add_missing_labels: bool = True
    ) -> bool:
        changed = False
        for ann in annotations:
            if not ann.label:
                ann.label = self.get_default_label().name
                changed = True
            if add_missing_labels:
                self.ensure_label_available(ann.label, ann.color)
            target = self._label_color(ann.label)
            if (ann.color.red(), ann.color.green(), ann.color.blue()) != (
                target.red(),
                target.green(),
                target.blue(),
            ):
                ann.color = target
                changed = True
        return changed

    def save_current_image_annotations(self, delete_if_empty: bool = True):
        if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
            return
        entry = self.image_entries[self.curr_image_idx]
        file_path = entry.file_path
        if not file_path or file_path == Path("Runtime"):
            return
        cache_path = self._cache_path_for_file(file_path)
        for idx, ann in enumerate(self.current_annotations):
            ann.annotation_id = idx
            ann.file_path = Path(file_path)

        # Save copy with selected=False to disk cache just like desktop LayerifyTab
        disk_copies = []
        for idx, ann in enumerate(self.current_annotations):
            c = ann.copy()
            c.annotation_id = idx
            c.selected = False
            c.file_path = Path(file_path)
            disk_copies.append(c)

        if disk_copies:
            Annotation.save_as_json(disk_copies, str(cache_path))
        elif delete_if_empty and cache_path.exists():
            try:
                cache_path.unlink()
            except OSError:
                pass

    def load_image_annotations(self, file_path: Path) -> list[Annotation]:
        if not file_path or file_path == Path("Runtime"):
            return []
        cache_path = self._cache_path_for_file(file_path)
        if cache_path.exists():
            annotations = Annotation.load_from_json(str(cache_path))
            for ann in annotations:
                self.ensure_label_available(ann.label, ann.color)
            if self.normalize_annotation_colors(annotations):
                Annotation.save_as_json(annotations, str(cache_path))
            return annotations
        return []

    @staticmethod
    def serialize_annotation(ann: Annotation) -> dict[str, Any]:
        rect = None
        if ann.rectangle is not None:
            rect = [
                float(ann.rectangle.x()),
                float(ann.rectangle.y()),
                float(ann.rectangle.x() + ann.rectangle.width()),
                float(ann.rectangle.y() + ann.rectangle.height()),
            ]
        poly = None
        if ann.polygon is not None and len(ann.polygon) > 0:
            poly = [[float(p.x()), float(p.y())] for p in ann.polygon]
        pts = None
        if ann.points:
            pts = [[float(p.x()), float(p.y())] for p in ann.points]

        has_mask = ann.mask is not None and np.any(ann.mask)
        mask_b64 = None
        if has_mask:
            mask_arr = np.asarray(ann.mask, dtype=np.uint8)
            if mask_arr.max() <= 1:
                mask_arr = mask_arr * 255
            pil_m = Image.fromarray(mask_arr, mode="L")
            buf = io.BytesIO()
            pil_m.save(buf, format="PNG")
            mask_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        ann_type = "point"
        if rect is not None:
            ann_type = "rectangle"
        elif poly is not None:
            ann_type = "polygon"
        elif has_mask:
            ann_type = "mask"

        rgb = [ann.color.red(), ann.color.green(), ann.color.blue()]
        return {
            "annotation_id": int(ann.annotation_id),
            "name": ann.name,
            "type": ann_type,
            "label": ann.label,
            "color": rgb,
            "color_hex": qcolor_to_hex(ann.color),
            "rgb": rgb,
            "points": pts or [],
            "rectangle": rect,
            "polygon": poly or [],
            "has_mask": bool(has_mask),
            "mask_png_b64": mask_b64,
            "is_complete": bool(ann.is_complete),
            "selected": bool(ann.selected),
            "score": float(ann.score) if ann.score is not None else None,
            "annotator": ann.annotator or "User",
            "annotation_time": ann.annotation_time or "",
            "visible": bool(ann.visible),
            "file_path": str(ann.file_path),
            "file_stem": Path(ann.file_path).stem[:15],
            "is_model_generated": bool(ann.is_model_generated),
            "model_name": ann.model_name,
            "caption": ann.caption or "",
        }

    def deserialize_annotation(self, d: dict[str, Any], index: int, default_file_path: Path) -> Annotation:
        label = d.get("label") or self.current_label or self.get_default_label().name
        self.ensure_label_available(label)
        color = self._label_color(label)
        ann = Annotation(
            annotation_id=index,
            label=label,
            color=color,
            is_complete=bool(d.get("is_complete", True)),
            selected=bool(d.get("selected", False)),
            score=d.get("score"),
            annotator=d.get("annotator") or "User",
            annotation_time=d.get("annotation_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            visible=bool(d.get("visible", True)),
            file_path=Path(d.get("file_path") or default_file_path),
            is_model_generated=bool(d.get("is_model_generated", False)),
            model_name=d.get("model_name"),
            caption=d.get("caption") or "",
        )
        if d.get("points"):
            ann.points = [QPointF(float(p[0]), float(p[1])) for p in d["points"]]
        if d.get("rectangle"):
            r = d["rectangle"]
            if len(r) == 4:
                x1, y1, x2, y2 = float(r[0]), float(r[1]), float(r[2]), float(r[3])
                ann.rectangle = QRectF(
                    min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
                )
        if d.get("polygon"):
            ann.polygon = QPolygonF([QPointF(float(p[0]), float(p[1])) for p in d["polygon"]])
        if d.get("mask_png_b64"):
            raw = base64.b64decode(d["mask_png_b64"])
            pil_m = Image.open(io.BytesIO(raw)).convert("L")
            ann.mask = (np.array(pil_m, dtype=np.uint8) > 0).astype(np.uint8)
        elif d.get("mask") is not None:
            ann.mask = np.array(d["mask"], dtype=np.uint8)
        if ann.mask is not None and (ann.polygon is None or len(ann.polygon) == 0):
            polys = mask_to_polygons((ann.mask > 0).astype(np.uint8) * 255, merge_polygons=True)
            if polys and len(polys[0]) >= 3:
                ann.polygon = QPolygonF([QPointF(float(p[0]), float(p[1])) for p in polys[0]])
        return ann

    # -------------------------------------------------------------------------
    # Image Loading & Selection
    # -------------------------------------------------------------------------
    def _probe_image_size(self, img_path: Path) -> tuple[int, int]:
        try:
            with Image.open(img_path) as im:
                return im.size
        except Exception:
            pix = QPixmap(str(img_path))
            return pix.width(), pix.height()

    def _load_images_from_folder(self, folder_path: Path):
        self.image_entries = []
        valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
        if folder_path.exists() and folder_path.is_dir():
            if self.layer_config.full_search:
                paths = sorted(folder_path.rglob("*.*"))
            else:
                paths = sorted(folder_path.glob("*.*"))
            for p in paths:
                if p.is_file() and p.suffix.lower() in valid_exts:
                    w, h = self._probe_image_size(p)
                    if w > 0 and h > 0:
                        self.image_entries.append(
                            WebImageEntry(is_baked_result=False, file_path=p.resolve(), width=w, height=h)
                        )

        bake_folder = self.layer_config.bake_dir
        if bake_folder.exists() and bake_folder.is_dir():
            for p in sorted(bake_folder.glob("*.*")):
                if p.is_file() and p.suffix.lower() in valid_exts:
                    w, h = self._probe_image_size(p)
                    if w > 0 and h > 0:
                        self.image_entries.append(
                            WebImageEntry(is_baked_result=True, file_path=p.resolve(), width=w, height=h)
                        )

    def _select_image_by_index(self, idx: int, save_previous: bool = True):
        if not self.image_entries:
            self.curr_image_idx = 0
            self.current_annotations = []
            return
        if save_previous:
            self.save_current_image_annotations(delete_if_empty=False)
        idx = max(0, min(len(self.image_entries) - 1, int(idx)))
        self.curr_image_idx = idx
        entry = self.image_entries[idx]
        self.current_annotations = self.load_image_annotations(entry.file_path)
        self.last_message = f"Showing image {self.curr_image_idx + 1}/{len(self.image_entries)}"

    def select_folder(self, folder_path_str: str) -> tuple[bool, str]:
        with self.lock:
            self.save_current_image_annotations(delete_if_empty=False)
            folder_path = Path(folder_path_str).expanduser().resolve()
            if not folder_path.exists() or not folder_path.is_dir():
                return False, f"Folder not found: {folder_path}"
            self._load_images_from_folder(folder_path)
            if not self.image_entries:
                self.current_annotations = []
                self.curr_image_idx = 0
                return False, f"No valid image files found in {folder_path}"
            self._select_image_by_index(0, save_previous=False)
            msg = f"Loaded {len(self.image_entries)} images from {folder_path}"
            self.last_message = msg
            return True, msg

    def browse_directory(self, path_str: str | None = None) -> dict[str, Any]:
        target = Path(path_str).expanduser().resolve() if path_str else self.project_dir
        if not target.exists() or not target.is_dir():
            target = self.project_dir
        valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
        subdirs = []
        images = []
        image_count = 0
        try:
            for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    subdirs.append({"name": item.name, "path": str(item.resolve())})
                elif item.is_file() and item.suffix.lower() in valid_exts:
                    image_count += 1
                    if len(images) < 100:
                        images.append({"name": item.name, "path": str(item.resolve())})
        except PermissionError:
            pass
        parent_str = str(target.parent) if target.parent != target else str(target)

        quick_paths = [
            {"label": "Project", "path": str(self.project_dir)},
            {"label": "Assets", "path": str(self.layer_config.assets_folder.resolve())},
        ]
        home_dir = Path.home()
        if home_dir.exists():
            quick_paths.append({"label": "Home", "path": str(home_dir.resolve())})
            for sub_name in ("Desktop", "Pictures", "Downloads"):
                candidate = home_dir / sub_name
                if candidate.exists() and candidate.is_dir():
                    quick_paths.append({"label": sub_name, "path": str(candidate.resolve())})

        return {
            "current": str(target),
            "current_path": str(target),
            "parent": parent_str,
            "parent_path": parent_str,
            "directories": subdirs,
            "images": images,
            "image_count": image_count,
            "quick_paths": quick_paths,
        }

    def upload_images(
        self, files: list[dict[str, str]], folder_name: str | None = None
    ) -> tuple[bool, str]:
        with self.lock:
            self.save_current_image_annotations(delete_if_empty=False)
            dest_dir = self.layer_config.assets_folder
            if folder_name:
                safe_folder = Path(folder_name).name.strip()
                if safe_folder and safe_folder not in {".", ".."}:
                    dest_dir = self.layer_config.assets_folder / safe_folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            saved_count = 0
            last_saved_path = None
            for f in files:
                name = Path(f.get("name", "uploaded.png")).name
                b64_data = f.get("data_b64", "")
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                if not b64_data:
                    continue
                raw = base64.b64decode(b64_data)
                out_path = dest_dir / name
                out_path.write_bytes(raw)
                last_saved_path = out_path.resolve()
                saved_count += 1

            if saved_count == 0:
                return False, "No valid images uploaded."

            self._load_images_from_folder(dest_dir)
            target_idx = 0
            if last_saved_path is not None and not folder_name:
                for i, entry in enumerate(self.image_entries):
                    if entry.file_path == last_saved_path:
                        target_idx = i
                        break
            self._select_image_by_index(target_idx, save_previous=False)
            msg = (
                f"Loaded {saved_count} image(s) from folder '{dest_dir.name}'"
                if folder_name
                else f"Uploaded {saved_count} image(s) to {dest_dir.name}"
            )
            self.last_message = msg
            return True, msg

    # -------------------------------------------------------------------------
    # Layerify Annotation Operations
    # -------------------------------------------------------------------------
    def _current_history(self) -> ImageUndoHistory:
        if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
            return self.image_histories["__runtime__"]
        return self.image_histories[str(self.image_entries[self.curr_image_idx].file_path)]

    def update_annotations(
        self,
        annotations_payload: list[dict[str, Any]],
        push_undo: bool = True,
        message: str | None = None,
    ):
        with self.lock:
            if push_undo:
                self._current_history().push(self.current_annotations)
            default_fp = (
                self.image_entries[self.curr_image_idx].file_path
                if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                else Path("Runtime")
            )
            new_anns = [
                self.deserialize_annotation(item, idx, default_fp)
                for idx, item in enumerate(annotations_payload)
            ]
            self.normalize_annotation_colors(new_anns)
            self.current_annotations = new_anns
            self.save_current_image_annotations()
            if message:
                self.last_message = message

    def undo_annotation(self) -> tuple[bool, str]:
        with self.lock:
            hist = self._current_history()
            if not hist.undo_stack:
                self.last_message = "Nothing to undo."
                return False, self.last_message
            hist.redo_stack.append([ann.copy() for ann in self.current_annotations])
            snapshot = hist.undo_stack.pop()
            self.current_annotations = [ann.copy() for ann in snapshot]
            for idx, ann in enumerate(self.current_annotations):
                ann.annotation_id = idx
                ann.selected = False
            self.save_current_image_annotations()
            self.last_message = "Undo applied."
            return True, self.last_message

    def redo_annotation(self) -> tuple[bool, str]:
        with self.lock:
            hist = self._current_history()
            if not hist.redo_stack:
                self.last_message = "Nothing to redo."
                return False, self.last_message
            hist.undo_stack.append([ann.copy() for ann in self.current_annotations])
            snapshot = hist.redo_stack.pop()
            self.current_annotations = [ann.copy() for ann in snapshot]
            for idx, ann in enumerate(self.current_annotations):
                ann.annotation_id = idx
                ann.selected = False
            self.save_current_image_annotations()
            self.last_message = "Redo applied."
            return True, self.last_message

    def copy_annotations(self) -> tuple[bool, str]:
        with self.lock:
            selected = [ann for ann in self.current_annotations if ann.selected]
            if not selected:
                self.last_message = "No annotation selected to copy."
                return False, self.last_message
            copied = [ann.copy() for ann in selected]
            for ann in copied:
                ann.selected = False
            self.annotation_clipboard = copied
            self.last_message = f"Copied {len(copied)} annotation(s)"
            return True, self.last_message

    def paste_annotations(self) -> tuple[bool, str]:
        with self.lock:
            if not self.annotation_clipboard:
                self.last_message = "No annotation copied to paste."
                return False, self.last_message
            self._current_history().push(self.current_annotations)
            fp = (
                self.image_entries[self.curr_image_idx].file_path
                if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                else Path("Runtime")
            )
            for copied in self.annotation_clipboard:
                new_ann = copied.copy()
                new_ann.annotation_id = len(self.current_annotations)
                new_ann.selected = False
                new_ann.file_path = fp
                new_ann.color = self._label_color(new_ann.label)
                self.current_annotations.append(new_ann)
            self.save_current_image_annotations()
            self.last_message = f"Pasted {len(self.annotation_clipboard)} annotation(s)"
            return True, self.last_message

    def clear_all_annotations_and_layers(self) -> tuple[bool, str]:
        with self.lock:
            self._current_history().push(self.current_annotations)
            self.current_annotations.clear()
            if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries):
                cache_path = self._cache_path_for_file(
                    self.image_entries[self.curr_image_idx].file_path
                )
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                    except OSError:
                        pass
            if self.current_canvas is not None:
                if self.current_canvas.layers:
                    self.current_canvas.push_undo_state()
                self.current_canvas.layers.clear()
            self.last_message = "All annotations cleared"
            return True, self.last_message

    def get_all_annotations(self) -> list[Annotation]:
        self.save_current_image_annotations()
        merged: list[Annotation] = []
        seen: set[Path] = set()
        for entry in self.image_entries:
            fp = entry.file_path
            if fp in seen:
                continue
            seen.add(fp)
            cache_path = self._cache_path_for_file(fp)
            if cache_path.exists():
                merged.extend(Annotation.load_from_json(str(cache_path)))
        return merged

    def export_annotations_json(self, all_layers: bool, file_path: str | None = None) -> dict[str, Any]:
        with self.lock:
            anns = self.get_all_annotations() if all_layers else self.current_annotations
            if not anns:
                return {"ok": False, "message": "No annotations to save!"}
            target_path = (
                Path(file_path).expanduser().resolve()
                if file_path
                else (
                    self.layer_config.cache_dir / "all_annotations.json"
                    if all_layers
                    else self.layer_config.cache_dir / "layer_annotations.json"
                )
            )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            Annotation.save_as_json(anns, str(target_path))
            content = target_path.read_text(encoding="utf-8")
            self.last_message = f"Saved annotations to {target_path.name}"
            return {
                "ok": True,
                "message": "Merged annotations saved successfully!"
                if all_layers
                else "Annotations saved successfully!",
                "path": str(target_path),
                "filename": target_path.name,
                "json_content": content,
            }

    def import_annotations_json(
        self,
        all_layers: bool,
        file_path: str | None = None,
        json_content: str | None = None,
    ) -> tuple[bool, str]:
        with self.lock:
            temp_path: Path | None = None
            try:
                if json_content:
                    temp_path = self.layer_config.cache_dir / "_uploaded_annotations.json"
                    temp_path.write_text(json_content, encoding="utf-8")
                    load_path = temp_path
                elif file_path:
                    load_path = Path(file_path).expanduser().resolve()
                else:
                    load_path = self.layer_config.cache_dir / "all_annotations.json"

                if not load_path.exists():
                    return False, f"Annotation file not found: {load_path}"

                loaded = Annotation.load_from_json(str(load_path))
                if all_layers:
                    by_file = defaultdict(list)
                    by_name = defaultdict(list)
                    for ann in loaded:
                        by_file[Path(ann.file_path).resolve()].append(ann)
                        by_name[Path(ann.file_path).name].append(ann)

                    for entry in self.image_entries:
                        fp = entry.file_path.resolve()
                        matched = by_file.get(fp) or by_name.get(fp.name, [])
                        copied = [a.copy() for a in matched]
                        self.normalize_annotation_colors(copied)
                        for idx, a in enumerate(copied):
                            a.annotation_id = idx
                            a.selected = False
                            a.file_path = fp
                        cache_p = self._cache_path_for_file(fp)
                        if copied:
                            Annotation.save_as_json(copied, str(cache_p))
                        elif cache_p.exists():
                            cache_p.unlink()

                    if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries):
                        self.current_annotations = self.load_image_annotations(
                            self.image_entries[self.curr_image_idx].file_path
                        )
                    self.last_message = "Merged annotations loaded successfully!"
                    return True, self.last_message
                else:
                    self._current_history().push(self.current_annotations)
                    fp = (
                        self.image_entries[self.curr_image_idx].file_path
                        if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                        else Path("Runtime")
                    )
                    for idx, a in enumerate(loaded):
                        a.annotation_id = idx
                        a.file_path = fp
                        self.ensure_label_available(a.label, a.color)
                    self.normalize_annotation_colors(loaded, add_missing_labels=False)
                    self.current_annotations = loaded
                    self.save_current_image_annotations()
                    self.last_message = "Annotations loaded successfully!"
                    return True, self.last_message
            except Exception as err:
                logger.exception(err)
                return False, f"Failed to load annotations: {err}"
            finally:
                if temp_path and temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

    # -------------------------------------------------------------------------
    # Label Management
    # -------------------------------------------------------------------------
    def manage_labels(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            action = payload.get("action")
            if action == "select":
                label_name = payload.get("label")
                if not label_name:
                    return False, "No label specified."
                self.current_label = label_name
                color = self._label_color(label_name)
                updated_selected = False
                for ann in self.current_annotations:
                    if ann.selected:
                        ann.label = label_name
                        ann.color = color
                        updated_selected = True
                if updated_selected:
                    self.save_current_image_annotations()
                self.last_message = f"Label changed to {label_name}"
                return True, self.last_message

            elif action == "add":
                name = (payload.get("name") or payload.get("label") or "").strip()
                color_hex = payload.get("color") or "#ffffff"
                if not name:
                    return False, "Label name cannot be empty."
                existing = [lbl.name for lbl in self.layer_config.predefined_labels]
                if name in existing:
                    return False, "Label name already exists!"
                qcol = hex_to_qcolor(color_hex)
                self.ensure_label_available(name, qcol)
                self.current_label = name
                self.last_message = f"Added label: {name}"
                return True, self.last_message

            elif action == "color":
                label_name = payload.get("label") or self.current_label
                color_hex = payload.get("color") or "#ffffff"
                qcol = hex_to_qcolor(color_hex)
                for lbl in self.layer_config.predefined_labels:
                    if lbl.name == label_name:
                        lbl.color = qcol
                        break
                self._propagate_label_color(label_name, qcol)
                self.last_message = f"Updated color for label {label_name}"
                return True, self.last_message

            elif action == "rename":
                old_name = (payload.get("old_name") or payload.get("old_label") or "").strip()
                new_name = (payload.get("new_name") or payload.get("new_label") or "").strip()
                if not old_name or not new_name or old_name == new_name:
                    return False, "Invalid label rename."
                existing = [
                    lbl.name
                    for lbl in self.layer_config.predefined_labels
                    if lbl.name != old_name
                ]
                if new_name in existing:
                    return False, "Label name already exists!"
                found = False
                for lbl in self.layer_config.predefined_labels:
                    if lbl.name == old_name:
                        lbl.name = new_name
                        found = True
                        break
                if not found:
                    return False, f"Label '{old_name}' not found."
                self._propagate_label_rename(old_name, new_name)
                if self.current_label == old_name:
                    self.current_label = new_name
                self.last_message = f"Renamed label {old_name} to {new_name}"
                return True, self.last_message

            elif action == "delete":
                raw_labels = payload.get("labels")
                if not raw_labels and payload.get("label"):
                    raw_labels = [payload.get("label")]
                names = [n for n in (raw_labels or []) if n]
                if not names:
                    return False, "Select one or more labels to delete."
                default_lbl = self.get_default_label()
                if default_lbl.name in names:
                    return False, "The default label cannot be removed."
                self.layer_config.predefined_labels = [
                    lbl for lbl in self.layer_config.predefined_labels if lbl.name not in set(names)
                ]
                for name in names:
                    self._propagate_label_delete(name, default_lbl)
                self.current_label = default_lbl.name
                self.last_message = f"Deleted {len(names)} label(s)"
                return True, self.last_message

            elif action == "cleanup_defaults":
                placeholders = {"Label 1", "Label 2", "Label 3", "Custom"}
                custom_labels = {
                    lbl.name
                    for lbl in self.layer_config.predefined_labels
                    if lbl.name not in (placeholders | {"Unlabeled"})
                }
                if not custom_labels:
                    return (
                        False,
                        "Create your own labels first, then the default placeholders can be removed.",
                    )
                targets = [
                    lbl.name
                    for lbl in self.layer_config.predefined_labels
                    if lbl.name in placeholders
                ]
                if not targets:
                    return False, "No default placeholder labels remain."
                return self.manage_labels({"action": "delete", "labels": targets})

            return False, f"Unknown label action: {action}"

    def _propagate_label_rename(self, old_label: str, new_label: str):
        for ann in self.current_annotations:
            if ann.label == old_label:
                ann.label = new_label
        self.save_current_image_annotations()

        for entry in self.image_entries:
            cp = self._cache_path_for_file(entry.file_path)
            if cp.exists():
                anns = Annotation.load_from_json(str(cp))
                changed = False
                for a in anns:
                    if a.label == old_label:
                        a.label = new_label
                        changed = True
                if changed:
                    Annotation.save_as_json(anns, str(cp))

    def _propagate_label_color(self, label_name: str, color: QColor):
        for ann in self.current_annotations:
            if ann.label == label_name:
                ann.color = QColor(color.red(), color.green(), color.blue())
        self.save_current_image_annotations()

        for entry in self.image_entries:
            cp = self._cache_path_for_file(entry.file_path)
            if cp.exists():
                anns = Annotation.load_from_json(str(cp))
                changed = False
                for a in anns:
                    if a.label == label_name:
                        a.color = QColor(color.red(), color.green(), color.blue())
                        changed = True
                if changed:
                    Annotation.save_as_json(anns, str(cp))

    def _propagate_label_delete(self, deleted_label: str, replacement: Label):
        for ann in self.current_annotations:
            if ann.label == deleted_label:
                ann.label = replacement.name
                ann.color = QColor(replacement.color)
        self.save_current_image_annotations()

        for entry in self.image_entries:
            cp = self._cache_path_for_file(entry.file_path)
            if cp.exists():
                anns = Annotation.load_from_json(str(cp))
                changed = False
                for a in anns:
                    if a.label == deleted_label:
                        a.label = replacement.name
                        a.color = QColor(replacement.color)
                        changed = True
                if changed:
                    Annotation.save_as_json(anns, str(cp))

    # -------------------------------------------------------------------------
    # Model Prediction & Layerify
    # -------------------------------------------------------------------------
    def run_prediction(self) -> tuple[bool, str]:
        with self.lock:
            model = self.loaded_models.get(self.current_model_name)
            if model is None:
                # Check if user stored None key
                model = self.loaded_models.get(None)
            if model is None:
                self.last_message = "No model selected/or loaded to predict"
                return False, self.last_message

            if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
                return False, "No image loaded to predict."

            entry = self.image_entries[self.curr_image_idx]
            pixmap = QPixmap(str(entry.file_path))
            if pixmap.isNull():
                return False, "Failed to read image for prediction."

            image_np = qpixmap_to_numpy(pixmap)
            prompt_anns = [
                ann
                for ann in self.current_annotations
                if not ann.is_model_generated and ann.visible
            ]

            points = []
            polygons = []
            rectangles = []
            label_hints = []
            for ann in prompt_anns:
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

            points_arg = points if points else None
            polygons_arg = polygons if polygons else None
            rectangles_arg = [rectangles] if rectangles else None
            label_hints_arg = label_hints if label_hints else None

            self._current_history().push(self.current_annotations)
            try:
                predictions: list[PredictionResult] = model.predict(
                    image_np,
                    points_arg,
                    rectangles_arg,
                    polygons_arg,
                    label_hints_arg,
                )
            except Exception as err:
                logger.exception(err)
                return False, f"Model error: {err}"

            model_name = getattr(model, "name", self.current_model_name)
            img_w = max(1, pixmap.width())
            img_h = max(1, pixmap.height())
            for pred in predictions or []:
                cls_name = pred.class_name or pred.prompt or "predicted"
                self.ensure_label_available(cls_name)
                pred_color = self._label_color(cls_name)
                if pred.rectangle:
                    r = pred.rectangle
                    # Handle xywh from PredictionResult and clamp into image bounds if out-of-range
                    if len(r) == 4:
                        rx, ry, rw, rh = float(r[0]), float(r[1]), float(r[2]), float(r[3])
                        rect = QRectF(rx, ry, rw, rh).normalized()
                        intersected = rect.intersected(QRectF(0, 0, img_w, img_h))
                        if intersected.width() >= 2 and intersected.height() >= 2:
                            rect = intersected
                        else:
                            # Fallback for dummy models generating coordinates larger than small images
                            rect = QRectF(
                                img_w * 0.15,
                                img_h * 0.15,
                                max(4.0, img_w * 0.7),
                                max(4.0, img_h * 0.7),
                            )
                    else:
                        rect = QRectF(0, 0, min(50, img_w), min(50, img_h))
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            rectangle=rect,
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )
                elif pred.polygon is not None and len(pred.polygon) >= 3:
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            polygon=QPolygonF(
                                [QPointF(float(p[0]), float(p[1])) for p in pred.polygon]
                            ),
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )
                elif pred.mask is not None:
                    mask_arr = np.asarray(pred.mask)
                    poly_q: QPolygonF | None = None
                    bin_mask: np.ndarray | None = None
                    if (
                        mask_arr.ndim == 2
                        and mask_arr.shape[1] == 2
                        and 3 <= mask_arr.shape[0] <= 256
                    ):
                        # Vertex list in pred.mask (e.g. get_dummy_prediction_result)
                        pts = []
                        for p in mask_arr:
                            px = min(float(img_w), max(0.0, float(p[0])))
                            py = min(float(img_h), max(0.0, float(p[1])))
                            pts.append(QPointF(px, py))
                        poly_q = QPolygonF(pts)
                    elif mask_arr.ndim == 2 and mask_arr.shape[0] > 2 and mask_arr.shape[1] > 2:
                        # 2D binary mask
                        bin_mask = (mask_arr > 0).astype(np.uint8)
                        polys = mask_to_polygons(bin_mask * 255, merge_polygons=True)
                        if polys and len(polys[0]) >= 3:
                            poly_q = QPolygonF(
                                [QPointF(float(p[0]), float(p[1])) for p in polys[0]]
                            )
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            polygon=poly_q,
                            mask=bin_mask,
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )
                else:
                    cx, cy = entry.width // 2, entry.height // 2
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            points=[QPointF(cx, cy)],
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )

            self.normalize_annotation_colors(self.current_annotations, add_missing_labels=False)
            self.save_current_image_annotations()
            self.last_message = f"Prediction complete ({len(predictions or [])} result(s))"
            return True, self.last_message

    def layerify_annotations(self, annotation_ids: list[int] | None = None) -> tuple[bool, str]:
        with self.lock:
            if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
                return False, "No image loaded to layerify."
            entry = self.image_entries[self.curr_image_idx]
            source_pixmap = QPixmap(str(entry.file_path))
            if source_pixmap.isNull():
                return False, "Failed to load source image for layerifying."

            if annotation_ids is not None and len(annotation_ids) > 0:
                target_ids = {int(i) for i in annotation_ids}
                targets = [
                    ann
                    for ann in self.current_annotations
                    if ann.annotation_id in target_ids and ann.visible
                ]
            else:
                selected = [ann for ann in self.current_annotations if ann.selected and ann.visible]
                targets = selected if selected else [ann for ann in self.current_annotations if ann.visible]

            if not targets:
                return False, "No visible annotations to layerify"

            if self.current_canvas is None:
                return False, "No active Baker canvas."

            self.current_canvas.push_undo_state()
            created_names = []

            for ann in targets:
                local_ann = ann.copy()
                if ann.rectangle:
                    rect = ann.rectangle.toRect().intersected(source_pixmap.rect())
                    if rect.width() <= 0 or rect.height() <= 0:
                        continue
                    cropped_pixmap = source_pixmap.copy(rect)
                    local_ann.rectangle = QRectF(0, 0, rect.width(), rect.height())
                elif ann.polygon and len(ann.polygon) >= 3:
                    bounding_rect = ann.polygon.boundingRect().toRect().intersected(source_pixmap.rect())
                    if bounding_rect.width() <= 0 or bounding_rect.height() <= 0:
                        continue
                    cropped_raw = source_pixmap.copy(bounding_rect).toImage().convertToFormat(
                        QImage.Format_ARGB32
                    )
                    mask_img = QImage(cropped_raw.size(), QImage.Format_ARGB32)
                    mask_img.fill(Qt.transparent)
                    translated_poly = ann.polygon.translated(-bounding_rect.topLeft())

                    painter = QPainter(mask_img)
                    painter.setRenderHint(QPainter.Antialiasing, False)
                    painter.setBrush(QColor(255, 255, 255, 255))
                    painter.setPen(Qt.NoPen)
                    painter.drawPolygon(translated_poly)
                    painter.end()

                    raw_arr = qpixmap_to_numpy(cropped_raw).copy()
                    mask_arr = qpixmap_to_numpy(mask_img)
                    raw_arr[:, :, 3] = np.where(mask_arr[:, :, 3] > 0, 255, 0).astype(np.uint8)
                    raw_arr = np.ascontiguousarray(raw_arr)
                    qimg = QImage(
                        raw_arr.data,
                        raw_arr.shape[1],
                        raw_arr.shape[0],
                        raw_arr.shape[1] * 4,
                        QImage.Format_RGBA8888,
                    )
                    cropped_pixmap = QPixmap.fromImage(qimg.copy())
                    local_ann.polygon = translated_poly
                elif ann.mask is not None and np.any(ann.mask):
                    mask_u8 = (np.asarray(ann.mask) > 0).astype(np.uint8) * 255
                    ys, xs = np.nonzero(mask_u8)
                    x0, x1 = int(xs.min()), int(xs.max()) + 1
                    y0, y1 = int(ys.min()), int(ys.max()) + 1
                    raw_arr = qpixmap_to_numpy(source_pixmap)[y0:y1, x0:x1].copy()
                    raw_arr[:, :, 3] = mask_u8[y0:y1, x0:x1]
                    raw_arr = np.ascontiguousarray(raw_arr)
                    qimg = QImage(
                        raw_arr.data,
                        raw_arr.shape[1],
                        raw_arr.shape[0],
                        raw_arr.shape[1] * 4,
                        QImage.Format_RGBA8888,
                    )
                    cropped_pixmap = QPixmap.fromImage(qimg.copy())
                    local_ann.mask = (mask_u8[y0:y1, x0:x1] > 0).astype(np.uint8)
                else:
                    cropped_pixmap = source_pixmap.copy()

                new_layer = WebLayerItem(self.canvas_config)
                new_layer.set_image(cropped_pixmap)
                new_layer.file_path = entry.file_path
                new_layer.annotations = [local_ann]
                base_name = f"{ann.label} {ann.annotation_id} {ann.annotator}"
                new_layer.layer_name = f"{len(self.current_canvas.layers) + 1}_{base_name}"
                new_layer.caption = ann.caption
                new_layer._apply_edge_opacity()

                # Center in viewport
                vw = self.current_canvas.viewport_width
                vh = self.current_canvas.viewport_height
                cx = max(0.0, (vw - cropped_pixmap.width()) / 2.0)
                cy = max(0.0, (vh - cropped_pixmap.height()) / 2.0)
                new_layer.position = QPointF(cx, cy)
                new_layer.order = len(self.current_canvas.layers)

                self.current_canvas.layers.append(new_layer)
                created_names.append(new_layer.layer_name)

            if not created_names:
                return False, "Could not layerify selected annotation(s)."

            self.last_message = f"Layerified: {created_names[-1]}"
            return True, f"Layerified {len(created_names)} layer(s): {', '.join(created_names)}"

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
                self.last_message = f"New canvas added: {name}"
                return True, self.last_message

            elif action == "select":
                cid = int(payload.get("canvas_id", -1))
                for c in self.canvases:
                    if c.canvas_id == cid:
                        self.current_canvas = c
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
                id_map = {layer.layer_id: layer for layer in layers}
                new_layers = [id_map[int(lid)] for lid in payload["order"] if int(lid) in id_map]
                for layer in layers:
                    if layer not in new_layers:
                        new_layers.append(layer)
                for idx, layer in enumerate(new_layers):
                    layer.order = idx
                self.current_canvas.layers = new_layers
                self.last_message = "Reordered layers."
                return True, self.last_message

            direction = payload.get("direction", "up")
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
            return True, self.last_message

    def baker_layer_action(self, payload: dict[str, Any]) -> tuple[bool, str]:
        with self.lock:
            if self.current_canvas is None:
                return False, "No active canvas."
            action = payload.get("action")
            canvas = self.current_canvas

            if action == "undo":
                ok, msg = canvas.undo()
                self.last_message = msg
                return ok, msg

            elif action == "redo":
                ok, msg = canvas.redo()
                self.last_message = msg
                return ok, msg

            elif action == "copy":
                selected = next((lyr for lyr in canvas.layers if lyr.selected), None)
                if selected is None:
                    self.last_message = "No layer selected to copy."
                    return False, self.last_message
                canvas.copied_layer = selected.copy()
                self.last_message = f"Copied layer {selected.layer_name}."
                return True, self.last_message

            elif action == "paste":
                if canvas.copied_layer is None:
                    self.last_message = "No layer copied to paste."
                    return False, self.last_message
                canvas.push_undo_state()
                new_layer = canvas.copied_layer.clone_as_new()
                new_layer.position = QPointF(
                    new_layer.position.x() + 10.0, new_layer.position.y() + 10.0
                )
                new_layer.layer_name = f"{len(canvas.layers) + 1}_{new_layer.layer_name}"
                for lyr in canvas.layers:
                    lyr.selected = False
                new_layer.selected = True
                new_layer.order = len(canvas.layers)
                canvas.layers.append(new_layer)
                self.last_message = f"Pasted layer {new_layer.layer_name}."
                return True, self.last_message

            elif action == "delete":
                lid = payload.get("layer_id")
                if lid is not None:
                    targets = [lyr for lyr in canvas.layers if lyr.layer_id == int(lid)]
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
                self.last_message = f"Deleted {targets[0].layer_name} layer."
                return True, self.last_message

            elif action == "group":
                return self._group_or_ungroup_selected_layers()

            elif action == "convert_ann_type":
                return self._convert_selected_annotation_type()

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
        if len(selected_layers) == 1 and len(selected_layers[0].layers) >= 2:
            return self._ungroup_layer(selected_layers[0])

        if len(selected_layers) != 2:
            self.last_message = "Select exactly 2 layers to group."
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

    def _ungroup_layer(self, grouped_layer: WebLayerItem) -> tuple[bool, str]:
        canvas = self.current_canvas
        if grouped_layer not in canvas.layers:
            return False, "Grouped layer not found in canvas."
        canvas.push_undo_state()
        group_idx = canvas.layers.index(grouped_layer)
        group_tf = self._compose_layer_transform(grouped_layer)

        restored: list[WebLayerItem] = []
        for child_rel in grouped_layer.layers:
            child = child_rel.clone_as_new()
            child_local_tf = self._compose_layer_transform(child)
            world_tf = group_tf * child_local_tf
            pos, rot, sx, sy = self._decompose_transform(world_tf)
            child.position = pos
            child.rotation = rot
            child.scale_x = sx
            child.scale_y = sy
            child.opacity = int(round((child.opacity * grouped_layer.opacity) / 255.0))
            child.visible = grouped_layer.visible and child.visible
            child.selected = False
            restored.append(child)

        del canvas.layers[group_idx]
        for offset, child in enumerate(restored):
            canvas.layers.insert(group_idx + offset, child)

        for lyr in canvas.layers:
            lyr.selected = False
        if restored:
            restored[0].selected = True
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
            layer = canvas.get_layer(st.layer_id)
            if layer is not None:
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

    # -------------------------------------------------------------------------
    # Baking & Exporting (Exact BakerWorker + CanvasLayer.handle_baker_results)
    # -------------------------------------------------------------------------
    def bake_and_export(self, mode: str) -> dict[str, Any]:
        """
        Modes:
        - "current_local": Export Current State locally to assets/exports
        - "states_local": Export all saved states locally to assets/exports
        - "predict_state": Bake current state and add to Layerify tab
        - "annotate_states": Bake all saved states and add to Layerify tab
        """
        with self.lock:
            canvas = self.current_canvas
            if canvas is None or not canvas.layers:
                return {
                    "ok": False,
                    "message": "No layers are available to export. Please add layers before exporting.",
                }

            is_current_only = mode in {"current_local", "predict_state"}
            export_to_annotation_tab = mode in {"predict_state", "annotate_states"}

            if canvas.states:
                if is_current_only:
                    step_key = (
                        int(canvas.current_step)
                        if int(canvas.current_step) in canvas.states
                        else canvas.step_key_for_index(canvas._current_step_index)
                    )
                    if step_key is None:
                        step_key = min(canvas.states.keys())
                    export_states = {int(step_key): canvas.states[int(step_key)]}
                else:
                    export_states = dict(canvas.states)
                timeline_total_steps = max(1, len(canvas.states))
            else:
                export_states = {0: canvas.build_states_for_step(step=0, total_steps=1)}
                timeline_total_steps = 1

            base_filename = self.canvas_config.filename_format.format(
                project_name=self.canvas_config.project_name,
                timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
            )
            base_filepath = self.canvas_config.export_folder / f"{base_filename}.png"

            # Snapshot current layer states before baking
            state_snapshots = {lyr.layer_id: lyr.layer_state.copy() for lyr in canvas.layers}
            image_snapshots = {lyr.layer_id: lyr.image.copy() for lyr in canvas.layers}

            results: list[BakingResult] = []
            try:
                for step_key, step_states in sorted(export_states.items()):
                    timeline_step = int(step_key)
                    top_left = QPointF(sys.maxsize, sys.maxsize)
                    bottom_right = QPointF(-sys.maxsize, -sys.maxsize)
                    rendered_images: dict[int, QImage] = {}

                    for st in step_states:
                        layer = canvas.get_layer(st.layer_id)
                        if layer and st.visible and not layer.image.isNull():
                            update_edge = (
                                layer.edge_width != st.edge_width
                                or layer.edge_opacity != st.edge_opacity
                            )
                            layer.layer_state = st
                            if update_edge:
                                layer._apply_edge_opacity()

                            pix = canvas.get_layer_render_pixmap(
                                layer, timeline_step, timeline_total_steps
                            )
                            qimg = pix.toImage().convertToFormat(QImage.Format_RGBA8888)
                            rendered_images[st.layer_id] = qimg

                            tf = QTransform()
                            tf.translate(layer.position.x(), layer.position.y())
                            tf.rotate(layer.rotation)
                            tf.scale(layer.scale_x, layer.scale_y)
                            t_rect = tf.mapRect(QRectF(QPointF(0, 0), qimg.size()))

                            top_left.setX(min(top_left.x(), t_rect.left()))
                            top_left.setY(min(top_left.y(), t_rect.top()))
                            bottom_right.setX(max(bottom_right.x(), t_rect.right()))
                            bottom_right.setY(max(bottom_right.y(), t_rect.bottom()))

                    width = int(bottom_right.x() - top_left.x())
                    height = int(bottom_right.y() - top_left.y())
                    if width <= 0 or height <= 0:
                        continue

                    out_image = QImage(width, height, QImage.Format_ARGB32)
                    out_image.fill(Qt.transparent)
                    masks = []
                    mask_names = []
                    new_annotations = []

                    painter = QPainter(out_image)
                    painter.setRenderHints(
                        QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                    )
                    try:
                        for st in step_states:
                            layer = canvas.get_layer(st.layer_id)
                            render_image = rendered_images.get(st.layer_id)
                            if not layer or not st.visible or render_image is None:
                                continue

                            painter.save()
                            painter.translate(layer.position - top_left)
                            painter.rotate(layer.rotation)
                            painter.scale(layer.scale_x, layer.scale_y)
                            painter.setOpacity(layer.opacity / 255.0)
                            painter.drawImage(QPoint(0, 0), render_image)
                            painter.restore()

                            if st.drawing_states:
                                painter.save()
                                painter.translate(layer.position - top_left)
                                painter.rotate(layer.rotation)
                                painter.scale(layer.scale_x, layer.scale_y)
                                for ds in st.drawing_states:
                                    painter.setPen(
                                        QPen(
                                            ds.color,
                                            ds.size,
                                            Qt.SolidLine,
                                            Qt.RoundCap,
                                            Qt.RoundJoin,
                                        )
                                    )
                                    painter.drawPoint(ds.position)
                                painter.restore()

                            # Layer mask
                            layer_mask = QImage(width, height, QImage.Format_ARGB32)
                            layer_mask.fill(Qt.transparent)
                            mp = QPainter(layer_mask)
                            mp.setRenderHints(
                                QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                            )
                            mp.translate(layer.position - top_left)
                            mp.rotate(layer.rotation)
                            mp.scale(layer.scale_x, layer.scale_y)
                            mp.drawImage(QPoint(0, 0), render_image)
                            if st.drawing_states:
                                for ds in st.drawing_states:
                                    mp.setPen(
                                        QPen(
                                            Qt.black,
                                            ds.size,
                                            Qt.SolidLine,
                                            Qt.RoundCap,
                                            Qt.RoundJoin,
                                        )
                                    )
                                    mp.drawPoint(ds.position)
                            mp.end()

                            mask_arr = qpixmap_to_numpy(layer_mask)
                            alpha_ch = mask_arr[:, :, 3].copy()
                            alpha_ch[alpha_ch > 0] = 255
                            masks.append(alpha_ch)
                            mask_names.append(layer.layer_name)

                            if layer.allow_annotation_export:
                                base_ann = layer.annotations[0] if layer.annotations else None
                                if base_ann is not None:
                                    gen_ann = self._generate_annotation_from_mask(base_ann, alpha_ch)
                                    gen_ann.caption = layer.caption
                                    new_annotations.append(gen_ann)

                                brush_mask = self._render_brush_mask(
                                    width, height, layer, st, top_left
                                )
                                brush_ann = self._generate_brush_annotation(
                                    base_ann, brush_mask, layer.layer_name, layer.caption
                                )
                                if brush_ann is not None:
                                    new_annotations.append(brush_ann)
                    finally:
                        painter.end()

                    step_filename = base_filepath.parent / f"{base_filepath.stem}_{step_key}.png"
                    results.append(
                        BakingResult(
                            filename=step_filename,
                            step=step_key,
                            image=out_image,
                            masks=masks,
                            mask_names=mask_names,
                            annotations=new_annotations,
                        )
                    )
            finally:
                for layer in canvas.layers:
                    if layer.layer_id in state_snapshots:
                        layer.layer_state = state_snapshots[layer.layer_id]
                    if layer.layer_id in image_snapshots:
                        layer._image = image_snapshots[layer.layer_id]

            if not results:
                return {"ok": False, "message": "Baking produced no visible output."}

            exported_files = []
            for res in results:
                if not export_to_annotation_tab:
                    res.image.save(str(res.filename))
                    exported_files.append(str(res.filename))

                    if self.canvas_config.is_debug:
                        if self.canvas_config.write_masks:
                            for i, m in enumerate(res.masks):
                                m_name = res.mask_names[i]
                                write_to = res.filename.parent / f"{m_name}_{res.filename.name}"
                                cv2.imwrite(str(write_to), m)
                        if self.canvas_config.write_annotations:
                            img_np = qpixmap_to_numpy(res.image.copy())
                            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGRA)
                            drawn = draw_annotations(img_bgr, res.annotations)
                            write_to = res.filename.parent / f"annotated_{res.filename.name}"
                            cv2.imwrite(str(write_to), drawn)

                    json_out = res.filename.parent / f"{res.filename.stem}.json"
                    Annotation.save_as_json(res.annotations, str(json_out))
                else:
                    # Add to Layerify Tab (bake_dir + cache_dir)
                    self.save_current_image_annotations(delete_if_empty=False)
                    filepath = (self.layer_config.bake_dir / res.filename.name).resolve()
                    res.image.save(str(filepath))
                    for idx, a in enumerate(res.annotations):
                        a.annotation_id = idx
                        a.file_path = filepath
                        self.ensure_label_available(a.label, a.color)
                    Annotation.save_as_json(
                        res.annotations, str(self._cache_path_for_file(filepath))
                    )
                    w, h = res.image.width(), res.image.height()
                    entry = WebImageEntry(
                        is_baked_result=True, file_path=filepath, width=w, height=h
                    )
                    self.image_entries.append(entry)
                    self._select_image_by_index(len(self.image_entries) - 1, save_previous=False)
                    self.active_tab = "Layerify"
                    exported_files.append(str(filepath))

            if export_to_annotation_tab:
                self.last_message = f"Baked result added ({len(results)} state(s))"
            else:
                self.last_message = f"Exported {len(results)} baked state(s) to {self.canvas_config.export_folder}"

            return {
                "ok": True,
                "message": self.last_message,
                "count": len(results),
                "exported_files": exported_files,
                "switched_to_layerify": export_to_annotation_tab,
            }

    @staticmethod
    def _generate_annotation_from_mask(ann: Annotation, alpha_channel: np.ndarray) -> Annotation:
        new_ann = Annotation(
            label=ann.label,
            color=ann.color,
            annotation_id=ann.annotation_id,
            is_complete=True,
            visible=True,
            caption=ann.caption,
            is_model_generated=ann.is_model_generated,
        )
        if ann.points:
            polygons = mask_to_polygons(alpha_channel, merge_polygons=True)
            if polygons:
                new_ann.polygon = QPolygonF([QPointF(p[0], p[1]) for p in polygons[0]])
            else:
                xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
                if xywhs:
                    new_ann.rectangle = QRectF(*xywhs[0])
        elif ann.rectangle:
            xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
            if xywhs:
                new_ann.rectangle = QRectF(*xywhs[0])
        elif ann.polygon:
            polygons = mask_to_polygons(alpha_channel, merge_polygons=True)
            if polygons:
                new_ann.polygon = QPolygonF([QPointF(p[0], p[1]) for p in polygons[0]])
            else:
                xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
                if xywhs:
                    new_ann.rectangle = QRectF(*xywhs[0])
        return new_ann

    @staticmethod
    def _render_brush_mask(
        width: int, height: int, layer: WebLayerItem, state: LayerState, top_left: QPointF
    ) -> np.ndarray | None:
        if not state.drawing_states:
            return None
        brush_mask = QImage(width, height, QImage.Format_ARGB32)
        brush_mask.fill(Qt.transparent)
        bp = QPainter(brush_mask)
        bp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        bp.translate(layer.position - top_left)
        bp.rotate(layer.rotation)
        bp.scale(layer.scale_x, layer.scale_y)
        for ds in state.drawing_states:
            bp.setPen(QPen(Qt.white, ds.size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            bp.drawPoint(ds.position)
        bp.end()

        arr = qpixmap_to_numpy(brush_mask)
        alpha = arr[:, :, 3].copy()
        alpha[alpha > 0] = 255
        if not np.any(alpha):
            return None
        return alpha

    @staticmethod
    def _generate_brush_annotation(
        base_ann: Annotation | None,
        brush_mask: np.ndarray | None,
        fallback_name: str,
        caption: str = "",
    ) -> Annotation | None:
        if brush_mask is None:
            return None
        label = f"{base_ann.label}_brush" if base_ann is not None else "Brush"
        color = base_ann.color if base_ann is not None else QColor(255, 255, 255)
        ann_id = (
            base_ann.annotation_id * 1000 + 1
            if base_ann is not None
            else abs(hash((fallback_name, "brush"))) % 1_000_000
        )
        brush_ann = Annotation(
            annotation_id=ann_id,
            label=label,
            color=color,
            mask=brush_mask,
            is_complete=True,
            visible=True,
            caption=caption or (base_ann.caption if base_ann is not None else ""),
        )
        polygons = mask_to_polygons(brush_mask, merge_polygons=True)
        if polygons:
            brush_ann.polygon = QPolygonF([QPointF(p[0], p[1]) for p in polygons[0]])
        else:
            xywhs = mask_to_rectangles(brush_mask, merge_rectangles=True)
            if xywhs:
                brush_ann.rectangle = QRectF(*xywhs[0])
        return brush_ann

    # -------------------------------------------------------------------------
    # Image Serving & State Serialization
    # -------------------------------------------------------------------------
    def get_layerify_image_bytes(self, index: int) -> tuple[bytes, str] | None:
        with self.lock:
            if not (0 <= index < len(self.image_entries)):
                return None
            entry = self.image_entries[index]
            if not entry.file_path.exists():
                return None
            ext = entry.file_path.suffix.lower()
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".bmp": "image/bmp",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(ext, "application/octet-stream")
            if ext in {".tiff", ".tif"}:
                pix = QPixmap(str(entry.file_path))
                return qimage_to_png_bytes(pix), "image/png"
            return entry.file_path.read_bytes(), mime

    def get_baker_layer_png_bytes(self, canvas_id: int, layer_id: int, step: int = 0) -> bytes | None:
        with self.lock:
            canvas = next((c for c in self.canvases if c.canvas_id == canvas_id), self.current_canvas)
            if canvas is None:
                return None
            layer = canvas.get_layer(layer_id)
            if layer is None or layer.image.isNull():
                return None

            total_steps = max(1, len(canvas.states)) if canvas.states else 1
            render_step = canvas._current_step_index if canvas.states else int(step)
            cache_key = (layer.revision, render_step, total_steps)
            if cache_key in layer._plugin_render_cache:
                return layer._plugin_render_cache[cache_key]

            rendered_pix = canvas.get_layer_render_pixmap(layer, render_step, total_steps)
            png_bytes = qimage_to_png_bytes(rendered_pix)
            layer._plugin_render_cache[cache_key] = png_bytes
            return png_bytes

    def get_state(self) -> dict[str, Any]:
        return self.get_state_dict()

    def get_state_dict(self) -> dict[str, Any]:
        with self.lock:
            curr_entry = (
                self.image_entries[self.curr_image_idx]
                if self.image_entries and 0 <= self.curr_image_idx < len(self.image_entries)
                else None
            )
            hist = self._current_history()
            canvas = self.current_canvas

            serialized_layers = []
            selected_plugins_union: list[str] = []
            if canvas is not None:
                render_step = canvas._current_step_index if canvas.states else 0
                for idx, layer in enumerate(canvas.layers):
                    ann = layer.annotations[0] if layer.annotations else None
                    plugin_names = [
                        getattr(p, "plugin_name", getattr(p, "name", type(p).__name__))
                        for p in getattr(layer, "plugins", [])
                        if getattr(p, "enabled", True)
                    ]
                    if layer.selected or not any(lyr.selected for lyr in canvas.layers):
                        for pn in plugin_names:
                            if pn not in selected_plugins_union:
                                selected_plugins_union.append(pn)
                    img_url = (
                        f"/api/baker/layer-image?canvas_id={canvas.canvas_id}"
                        f"&layer_id={layer.layer_id}&step={render_step}&rev={layer.revision}"
                    )
                    serialized_layers.append(
                        {
                            "layer_id": layer.layer_id,
                            "layer_name": layer.layer_name,
                            "label": ann.label if ann else layer.layer_name,
                            "annotator": ann.annotator if ann else "User",
                            "score": float(ann.score) if (ann and ann.score is not None) else None,
                            "file_stem": Path(layer.file_path).stem[:15],
                            "visible": bool(layer.visible),
                            "selected": bool(layer.selected),
                            "allow_annotation_export": bool(layer.allow_annotation_export),
                            "order": idx,
                            "position": [float(layer.position.x()), float(layer.position.y())],
                            "rotation": float(layer.rotation),
                            "scale_x": float(layer.scale_x),
                            "scale_y": float(layer.scale_y),
                            "opacity": float(layer.opacity),
                            "edge_opacity": int(layer.edge_opacity),
                            "edge_width": int(layer.edge_width),
                            "caption": layer.caption or "",
                            "width": int(layer.original_size.width()),
                            "height": int(layer.original_size.height()),
                            "is_group": len(layer.layers) >= 2,
                            "plugins": plugin_names,
                            "annotation_type": (
                                "polygon"
                                if (ann and ann.polygon is not None)
                                else ("rectangle" if (ann and ann.rectangle is not None) else "other")
                            ),
                            "drawing_states": [
                                {
                                    "position": [float(d.position.x()), float(d.position.y())],
                                    "points": [[float(d.position.x()), float(d.position.y())]],
                                    "color": [d.color.red(), d.color.green(), d.color.blue(), d.color.alpha()],
                                    "color_hex": qcolor_to_hex(d.color),
                                    "size": int(d.size),
                                }
                                for d in layer.drawing_states
                            ],
                            "revision": layer.revision,
                            "image_revision": layer.revision,
                            "image_url": img_url,
                            "thumbnail": img_url,
                        }
                    )

            img_status = (
                f"{self.curr_image_idx + 1}/{len(self.image_entries)}"
                if self.image_entries
                else "0/0"
            )
            status_bar = (
                f"{self.last_message} | "
                f"Label: {self.current_label} | "
                f"Model: {self.current_model_name} | "
                f"Annotations: {len(self.current_annotations)} | "
                f"Layers: {len(canvas.layers) if canvas else 0} | "
                f"Image: {img_status}"
            )

            default_canvas_thumb = (
                "data:image/svg+xml;utf8,"
                "<svg xmlns='http://www.w3.org/2000/svg' width='44' height='44'>"
                "<rect width='44' height='44' fill='%23233650'/></svg>"
            )

            return {
                "version": __version__,
                "project_name": self.layer_config.project_name,
                "project_dir": str(self.project_dir),
                "theme_mode": self.theme_mode,
                "active_tab": self.active_tab,
                "show_gridlines": bool(self.layer_config.show_gridlines),
                "grid_spacing": int(self.layer_config.grid_spacing),
                "message": self.last_message,
                "status_message": self.last_message,
                "status_bar": status_bar,
                "configs": {
                    "layer_config": {
                        "thumbnail_page_size": int(self.layer_config.deque_maxlen),
                    },
                    "bake_config": {
                        "fps": int(self.canvas_config.fps),
                    },
                },
                "layerify": {
                    "images": [
                        {
                            "index": i,
                            "name": f"Baked Result {i + 1}"
                            if e.is_baked_result
                            else e.name[: self.layer_config.max_name_length],
                            "full_name": e.name,
                            "path": str(e.file_path),
                            "is_baked_result": e.is_baked_result,
                            "selected": i == self.curr_image_idx,
                            "width": e.width,
                            "height": e.height,
                            "url": f"/api/layerify/image?index={i}&t={int(e.file_path.stat().st_mtime_ns if e.file_path.exists() else 0)}",
                            "thumbnail": f"/api/layerify/image?index={i}&t={int(e.file_path.stat().st_mtime_ns if e.file_path.exists() else 0)}",
                        }
                        for i, e in enumerate(self.image_entries)
                    ],
                    "curr_image_idx": self.curr_image_idx if self.image_entries else None,
                    "current_image_index": self.curr_image_idx if self.image_entries else None,
                    "current_image_name": curr_entry.name if curr_entry else None,
                    "current_image_revision": int(
                        curr_entry.file_path.stat().st_mtime_ns
                        if (curr_entry and curr_entry.file_path.exists())
                        else 0
                    ),
                    "current_folder": str(
                        curr_entry.file_path.parent
                        if curr_entry
                        else self.layer_config.assets_folder
                    ),
                    "images_per_page": int(self.layer_config.deque_maxlen),
                    "current_image": (
                        {
                            "index": self.curr_image_idx,
                            "name": curr_entry.name,
                            "path": str(curr_entry.file_path),
                            "width": curr_entry.width,
                            "height": curr_entry.height,
                            "is_baked_result": curr_entry.is_baked_result,
                            "url": f"/api/layerify/image?index={self.curr_image_idx}&t={int(curr_entry.file_path.stat().st_mtime_ns if curr_entry.file_path.exists() else 0)}",
                        }
                        if curr_entry
                        else None
                    ),
                    "annotations": [
                        self.serialize_annotation(ann) for ann in self.current_annotations
                    ],
                    "labels": [
                        {
                            "name": lbl.name,
                            "color": [lbl.color.red(), lbl.color.green(), lbl.color.blue()],
                            "color_hex": qcolor_to_hex(lbl.color),
                            "rgb": [lbl.color.red(), lbl.color.green(), lbl.color.blue()],
                        }
                        for lbl in self.layer_config.predefined_labels
                    ],
                    "default_label": self.get_default_label().name,
                    "current_label": self.current_label,
                    "selected_label": self.current_label,
                    "models": [str(k) for k in self.loaded_models.keys()],
                    "current_model": self.current_model_name,
                    "selected_model": self.current_model_name,
                    "can_undo": len(hist.undo_stack) > 0,
                    "can_redo": len(hist.redo_stack) > 0,
                    "clipboard_count": len(self.annotation_clipboard),
                },
                "baker": {
                    "canvases": [
                        {
                            "canvas_id": c.canvas_id,
                            "name": c.layer_name,
                            "selected": (canvas is not None and c.canvas_id == canvas.canvas_id),
                            "layer_count": len(c.layers),
                            "num_layers": len(c.layers),
                            "state_count": len(c.states),
                            "num_states": len(c.states),
                            "thumb_url": (
                                f"/api/baker/layer-image?canvas_id={c.canvas_id}"
                                f"&layer_id={c.layers[0].layer_id}&step=0&rev={c.layers[0].revision}"
                                if c.layers
                                else default_canvas_thumb
                            ),
                            "thumbnail": (
                                f"/api/baker/layer-image?canvas_id={c.canvas_id}"
                                f"&layer_id={c.layers[0].layer_id}&step=0&rev={c.layers[0].revision}"
                                if c.layers
                                else default_canvas_thumb
                            ),
                        }
                        for c in self.canvases
                    ],
                    "current_canvas_id": canvas.canvas_id if canvas else -1,
                    "canvases_per_page": 10,
                    "layers": serialized_layers,
                    "available_plugins": sorted(self.plugin_registry.keys()),
                    "selected_plugins": selected_plugins_union,
                    "states": canvas.ordered_state_steps() if canvas else [],
                    "state_count": len(canvas.states) if canvas else 0,
                    "num_states": len(canvas.states) if canvas else 0,
                    "current_step": canvas.current_step if canvas else 0,
                    "current_step_index": canvas._current_step_index if canvas else 0,
                    "current_state_step": canvas._current_step_index if canvas else 0,
                    "fps": int(self.canvas_config.fps),
                    "slider_limits": {
                        "max_xpos": int(self.canvas_config.max_xpos),
                        "max_ypos": int(self.canvas_config.max_ypos),
                        "max_scale": int(self.canvas_config.max_scale),
                        "max_edge_width": int(self.canvas_config.max_edge_width),
                    },
                    "can_undo": len(canvas._undo_stack) > 0 if canvas else False,
                    "can_redo": len(canvas._redo_stack) > 0 if canvas else False,
                    "has_copied_layer": (canvas.copied_layer is not None) if canvas else False,
                },
            }
