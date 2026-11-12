"""
Web Application Engine for ImageBaker.

Provides a cross-platform, headless-compatible state and rendering engine that mirrors
all features of the desktop Layerify, Baker, and Help tabs while reusing ImageBaker's
core data structures, plugins, models, and cache/export formats.
"""

from __future__ import annotations

import os
import sys
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

# Ensure Qt can initialize headlessly on Linux/macOS/CI servers without an X display
if sys.platform != "win32" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QPixmap

from imagebaker import __version__, logger
from imagebaker.core.configs import CanvasConfig, LayerConfig
from imagebaker.core.defs import Annotation
from imagebaker.plugins.base_plugin import BasePlugin
from imagebaker.web.engine_ai_and_extract import WebEngineAiExtractMixin
from imagebaker.web.engine_baking import WebEngineBakingMixin
from imagebaker.web.engine_cache import WebEngineCacheMixin
from imagebaker.web.engine_canvas import WebEngineCanvasMixin
from imagebaker.web.engine_layerify import WebEngineLayerifyMixin
from imagebaker.web.models import (
    ImageUndoHistory,
    WebCanvasItem,
    WebImageEntry,
    ensure_headless_qapp,
    qcolor_to_hex,
    qimage_to_png_bytes,
)
from imagebaker.window.app import find_and_import_subclass, load_models


class WebAppEngine(
    WebEngineCacheMixin,
    WebEngineLayerifyMixin,
    WebEngineAiExtractMixin,
    WebEngineCanvasMixin,
    WebEngineBakingMixin,
):
    """
    Core stateful engine for the ImageBaker standalone web app.
    """

    def __init__(
        self,
        models_file: str | None = "loaded_models.py",
        project_dir: str = ".",
        configs_file: str | None = "imagebaker/core/configs.py",
        is_debug: bool = False,
    ):
        ensure_headless_qapp()
        self.lock = threading.RLock()
        self.project_dir = Path(project_dir).resolve()
        self.is_debug = is_debug
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

        if self.is_debug:
            self.layer_config.is_debug = True
            self.canvas_config.is_debug = True

        # Layerify state
        self.layer_config.load_labels_from_cache()
        model_keys = [str(k) for k in self.loaded_models.keys()]
        self.current_model_name = model_keys[0] if model_keys else "None"
        self.current_predict_prompt: str = ""
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
        self.load_baker_cache()

        # Load default images
        self._load_images_from_folder(self.layer_config.assets_folder)
        if self.image_entries:
            self._select_image_by_index(0, save_previous=False)
            self.last_message = f"Showing image 1/{len(self.image_entries)}"
        else:
            self.last_message = "No images found in the assets folder."

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
                            "grouped_layers": [
                                {
                                    "layer_id": child.layer_id,
                                    "layer_name": child.layer_name,
                                    "label": child.annotations[0].label if child.annotations else child.layer_name,
                                    "caption": child.caption or "",
                                    "visible": bool(child.visible),
                                    "opacity": float(child.opacity),
                                    "annotations": [
                                        self.serialize_annotation(a) for a in child.annotations
                                    ],
                                }
                                for child in layer.layers
                            ] if len(layer.layers) >= 2 else [],
                            "annotations": [
                                self.serialize_annotation(a) for a in layer.annotations
                            ],
                            "plugins": plugin_names,
                            "annotation_type": (
                                "brush"
                                if (ann and ann.mask is not None and np.any(ann.mask) and not ann.polygon)
                                else (
                                    "polygon"
                                    if (ann and ann.polygon is not None)
                                    else ("rectangle" if (ann and ann.rectangle is not None) else "other")
                                )
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
                            "thumb_url": img_url,
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
                "is_debug": bool(getattr(self, "is_debug", False) or self.canvas_config.is_debug),
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
                    "current_predict_prompt": self.current_predict_prompt,
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
