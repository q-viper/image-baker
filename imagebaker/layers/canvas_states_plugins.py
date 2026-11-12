"""State timeline management, undo/redo, and plugin execution for CanvasLayer."""

import random

from PySide6.QtCore import QPointF, QThread
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from imagebaker import logger
from imagebaker.core.defs import DrawingState
from imagebaker.layers.base_layer import BaseLayer
from imagebaker.plugins.base_plugin import BasePlugin
from imagebaker.plugins.runtime import apply_pixel_plugins
from imagebaker.utils.state_utils import calculate_intermediate_states


class CanvasStatesPluginsMixin:
    """Mixin managing CanvasLayer undo/redo history, states, plugins, and playback."""

    def _snapshot_layers(self):
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

    def _restore_layers(self, snapshot):
        restored_layers = [layer.copy() for layer in snapshot.get("layers", [])]
        selected_indices = set(snapshot.get("selected_indices", []))
        for idx, layer in enumerate(restored_layers):
            layer.selected = idx in selected_indices
        self.layers = restored_layers
        self._plugin_render_cache.clear()
        self.selected_layer = self._get_selected_layer()
        self._update_back_buffer()
        self.layersChanged.emit()
        if self.selected_layer is not None:
            self.layerSelected.emit(self.selected_layer)
        self.update()

    def push_undo_state(self):
        """Capture current canvas layers for undo."""
        self._undo_stack.append(self._snapshot_layers())
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        """Undo the last canvas edit operation."""
        if not self._undo_stack:
            self.messageSignal.emit("Nothing to undo.")
            return False
        self._redo_stack.append(self._snapshot_layers())
        snapshot = self._undo_stack.pop()
        self._restore_layers(snapshot)
        self.messageSignal.emit("Undo applied.")
        return True

    def redo(self):
        """Redo the last undone canvas edit operation."""
        if not self._redo_stack:
            self.messageSignal.emit("Nothing to redo.")
            return False
        self._undo_stack.append(self._snapshot_layers())
        snapshot = self._redo_stack.pop()
        self._restore_layers(snapshot)
        self.messageSignal.emit("Redo applied.")
        return True

    def _apply_plugins_to_state(
        self,
        layer: BaseLayer,
        state,
        step: int,
        total_steps: int,
    ):
        plugins = getattr(layer, "plugins", [])
        if not plugins:
            return state

        for plugin in plugins:
            if not getattr(plugin, "enabled", True):
                continue
            try:
                updated_state = plugin.update(
                    state=state,
                    step=step,
                    total_steps=total_steps,
                    layer=layer,
                    canvas=self,
                )
                if updated_state is not None:
                    state = updated_state
            except Exception as error:
                logger.error(
                    f"Plugin '{getattr(plugin, 'name', type(plugin).__name__)}' failed: {error}"
                )
        return state

    def _build_states_for_step(self, step: int, total_steps: int):
        built_states = []
        for order, layer in enumerate(self.layers):
            state = layer.layer_state.copy()
            state.order = order
            state.selected = False
            state.caption = layer.caption
            state.drawing_states = [
                DrawingState(position=d.position, color=d.color, size=d.size)
                for d in layer.layer_state.drawing_states
            ]
            state = self._apply_plugins_to_state(layer, state, step, total_steps)
            built_states.append(state)
        return built_states

    def _plugin_cache_key(self, layer: BaseLayer, step: int, total_steps: int):
        def _plugin_desc(plugin):
            describe_fn = getattr(plugin, "describe", None)
            if callable(describe_fn):
                return describe_fn()
            return str(plugin)

        plugin_signature = tuple(
            (
                type(plugin).__name__,
                getattr(plugin, "enabled", True),
                _plugin_desc(plugin),
            )
            for plugin in getattr(layer, "plugins", [])
        )
        return (
            layer.layer_id,
            int(step),
            int(total_steps),
            int(layer.image.cacheKey()) if not layer.image.isNull() else 0,
            plugin_signature,
        )

    def _state_step_index(self, step_key: int):
        if not self.states:
            return 0
        ordered_steps = self._ordered_state_steps()
        try:
            return ordered_steps.index(step_key)
        except ValueError:
            return 0

    def _ordered_state_steps(self) -> list[int]:
        if not self.states:
            return []
        return sorted(self.states.keys())

    def _step_key_for_index(self, step_index: int) -> int | None:
        ordered_steps = self._ordered_state_steps()
        if not ordered_steps:
            return None
        idx = max(0, min(len(ordered_steps) - 1, int(step_index)))
        return ordered_steps[idx]

    def _get_layer_render_pixmap(self, layer: BaseLayer, step: int, total_steps: int):
        if not getattr(layer, "plugins", []):
            return layer.image

        key = self._plugin_cache_key(layer, step, total_steps)
        cached = self._plugin_render_cache.get(key)
        if cached is not None:
            return cached

        rendered = apply_pixel_plugins(
            layer=layer,
            step=step,
            total_steps=total_steps,
            canvas=self,
        )
        self._plugin_render_cache[key] = rendered
        if len(self._plugin_render_cache) > 256:
            self._plugin_render_cache.pop(next(iter(self._plugin_render_cache)))
        return rendered

    def _build_export_render_cache(
        self,
        states: dict[int, list],
        timeline_total_steps: int | None = None,
    ) -> dict[tuple[int, int], QImage]:
        """
        Pre-render plugin-adjusted layer images for export/predict in the UI thread.
        Returns mapping of (timeline_step, layer_id) -> QImage (RGBA8888).
        """
        render_cache: dict[tuple[int, int], QImage] = {}
        if not states or not self.layers:
            return render_cache

        state_snapshots = {
            layer.layer_id: layer.layer_state.copy() for layer in self.layers
        }
        image_snapshots = {
            layer.layer_id: layer.image.copy() for layer in self.layers
        }
        sorted_items = sorted(states.items())
        total_steps = (
            max(1, len(sorted_items))
            if timeline_total_steps is None
            else max(1, int(timeline_total_steps))
        )

        try:
            for step_key, step_states in sorted_items:
                timeline_step = int(step_key)
                for state in step_states:
                    layer = self.get_layer(state.layer_id)
                    if layer is None or layer.image.isNull():
                        continue

                    update_opacities = (
                        layer.edge_width != state.edge_width
                        or layer.edge_opacity != state.edge_opacity
                    )
                    layer.layer_state = state
                    if update_opacities:
                        layer._apply_edge_opacity()

                    render_pixmap = self._get_layer_render_pixmap(
                        layer=layer,
                        step=timeline_step,
                        total_steps=total_steps,
                    )
                    if render_pixmap.isNull():
                        continue

                    image = render_pixmap.toImage()
                    if image.format() != QImage.Format_RGBA8888:
                        image = image.convertToFormat(QImage.Format_RGBA8888)
                    render_cache[(timeline_step, state.layer_id)] = image.copy()
        finally:
            for layer in self.layers:
                snapshot_state = state_snapshots.get(layer.layer_id)
                snapshot_image = image_snapshots.get(layer.layer_id)
                if snapshot_state is not None:
                    layer.layer_state = snapshot_state
                if snapshot_image is not None:
                    layer.image = snapshot_image

        return render_cache

    def save_current_state(self, steps: int = 1):
        """Save current state and apply plugins for each generated step."""
        curr_states = {}
        mode = self.mouse_mode
        total_steps = max(1, int(steps))
        start_step = (max(self.states.keys()) + 1) if self.states else 0

        for layer in self.layers:
            intermediate_states = calculate_intermediate_states(
                layer.previous_state, layer.layer_state.copy(), total_steps
            )
            is_selected = layer.selected

            for local_step, state in enumerate(intermediate_states):
                state_step = start_step + local_step
                state.selected = False
                state.drawing_states = [
                    DrawingState(position=d.position, color=d.color, size=d.size)
                    for d in layer.layer_state.drawing_states
                ]
                state = self._apply_plugins_to_state(
                    layer, state, local_step, total_steps
                )
                if state_step not in curr_states:
                    curr_states[state_step] = []
                curr_states[state_step].append(state)

            layer.previous_state = layer.layer_state.copy()
            layer.selected = is_selected

        for state_step, states in sorted(curr_states.items()):
            self.states[state_step] = states
            self.current_step = state_step

        self._current_step_index = self._state_step_index(self.current_step)
        self._plugin_render_cache.clear()
        self.previous_state = self.layer_state.copy()
        self.layer_state.drawing_states = [
            DrawingState(position=d.position, color=d.color, size=d.size)
            for d in self.layer_state.drawing_states
        ]
        self.messageSignal.emit(
            "State saved."
            + f" Total states: {len(self.states)}"
            + f" | Steps: {total_steps}"
            + f" | Current step: {self.current_step}"
        )
        self.mouse_mode = mode
        self.update()

    def add_plugins_to_selected_layers(self, plugins: list[BasePlugin]) -> tuple[int, int]:
        """Attach plugin instances to each selected layer."""
        selected_layers = self._get_selected_layers()
        if not selected_layers:
            self.messageSignal.emit("Select at least one layer to add a plugin.")
            return 0, 0
        if not plugins:
            self.messageSignal.emit("No plugins selected.")
            return 0, 0

        self.push_undo_state()
        added = 0
        skipped = 0
        for layer in selected_layers:
            layer_plugins = getattr(layer, "plugins", [])
            for plugin in plugins:
                if any(type(existing) is type(plugin) for existing in layer_plugins):
                    skipped += 1
                    continue
                layer_plugins.append(plugin.copy())
                added += 1
            layer.plugins = layer_plugins

        self._plugin_render_cache.clear()
        self.layersChanged.emit()
        self.update()
        plugin_names = ", ".join(plugin.name for plugin in plugins)
        self.messageSignal.emit(
            f"Added plugin(s) [{plugin_names}] {added} time(s)."
            + (f" Skipped {skipped} duplicate attachment(s)." if skipped else "")
        )
        return added, skipped

    def add_plugin_to_selected_layers(self, plugin: BasePlugin) -> tuple[int, int]:
        """Backward-compatible wrapper for single-plugin add."""
        return self.add_plugins_to_selected_layers([plugin])

    def set_plugins_for_selected_layers(
        self, plugin_classes: list[type[BasePlugin]]
    ) -> tuple[int, int]:
        """Set selected layers' plugins to exactly the provided plugin classes."""
        selected_layers = self._get_selected_layers()
        if not selected_layers:
            self.messageSignal.emit("Select at least one layer to configure plugins.")
            return 0, 0
        return self.set_plugins_for_layers(selected_layers, plugin_classes)

    def set_plugins_for_layers(
        self, target_layers: list[BaseLayer], plugin_classes: list[type[BasePlugin]]
    ) -> tuple[int, int]:
        """Set provided layers' plugins to exactly the provided plugin classes."""
        if not target_layers:
            return 0, 0

        desired = tuple(plugin_classes)
        updates = []
        failed = 0

        for layer in target_layers:
            current_plugins = getattr(layer, "plugins", [])
            current_map = {type(plugin): plugin for plugin in current_plugins}
            current_types = tuple(type(plugin) for plugin in current_plugins)
            if current_types == desired:
                continue

            new_plugins = []
            for plugin_class in desired:
                existing = current_map.get(plugin_class)
                if existing is not None:
                    existing.enabled = True
                    new_plugins.append(existing)
                    continue
                try:
                    new_plugins.append(plugin_class())
                except Exception as error:
                    logger.error(
                        f"Failed to instantiate plugin '{plugin_class.__name__}': {error}"
                    )
                    failed += 1
            updates.append((layer, new_plugins))

        if not updates and failed == 0:
            return 0, 0

        self.push_undo_state()
        for layer, new_plugins in updates:
            layer.plugins = new_plugins

        changed_layers = len(updates)
        self._plugin_render_cache.clear()
        self.layersChanged.emit()
        self.update()
        self.messageSignal.emit(
            f"Updated plugins on {changed_layers} layer(s)."
            + (f" Failed {failed} plugin instantiation(s)." if failed else "")
        )
        return changed_layers, failed

    def clear_plugins_from_selected_layers(self) -> int:
        """Remove all plugins from selected layers."""
        selected_layers = self._get_selected_layers()
        if not selected_layers:
            self.messageSignal.emit("Select at least one layer to remove plugins.")
            return 0

        removed = sum(len(getattr(layer, "plugins", [])) for layer in selected_layers)
        if removed == 0:
            self.messageSignal.emit("Selected layers do not have plugins.")
            return 0

        self.push_undo_state()
        for layer in selected_layers:
            layer.plugins = []

        self._plugin_render_cache.clear()
        self.layersChanged.emit()
        self.update()
        self.messageSignal.emit(f"Removed {removed} plugin instance(s).")
        return removed

    def seek_state(self, step):
        """Seek to a specific state key or timeline index."""
        if not self.states:
            return

        requested = int(step)
        step_key = (
            requested if requested in self.states else self._step_key_for_index(requested)
        )
        if step_key is None:
            return

        self.messageSignal.emit(f"Seeking to step {step_key}")
        logger.info(f"Seeking to step {step_key}")
        self.current_step = step_key
        self._current_step_index = self._state_step_index(step_key)

        if step_key in self.states:
            states = self.states[step_key]
            for state in states:
                layer = self.get_layer(state.layer_id)
                if layer:
                    update_opacities = (
                        layer.edge_width != state.edge_width
                        or layer.edge_opacity != state.edge_opacity
                    )
                    layer.layer_state = state
                    if update_opacities:
                        layer._apply_edge_opacity()
                    layer.update()

    def stop_playing(self):
        """Stop playing saved states."""
        if self.is_playing:
            self.is_playing = False
            self.messageSignal.emit("Playback paused.")

    def play_states(self):
        """Play all the states stored in self.states."""
        if len(self.states) == 0:
            logger.warning("No states to play")
            self.messageSignal.emit("No states to play")
            self.is_playing = False
            return

        if self.is_playing:
            self.stop_playing()
            return

        self.is_playing = True
        fps = max(1, int(self.config.fps or 2))
        frame_delay_ms = max(250, int(1000 / fps))

        try:
            for step, states in sorted(self.states.items()):
                if not self.is_playing:
                    break
                self.messageSignal.emit(f"Playing step {step}")
                logger.info(f"Playing step {step}")
                self.current_step = step
                self._current_step_index = self._state_step_index(step)

                parent = self.parentWidget()
                if parent is not None and hasattr(parent, "timeline_slider"):
                    parent.timeline_slider.blockSignals(True)
                    parent.timeline_slider.setValue(self._current_step_index)
                    parent.timeline_slider.blockSignals(False)

                for state in states:
                    layer = self.get_layer(state.layer_id)
                    if layer:
                        update_opacities = (
                            layer.edge_width != state.edge_width
                            or layer.edge_opacity != state.edge_opacity
                        )
                        layer.layer_state = state
                        if update_opacities:
                            layer._apply_edge_opacity()
                        layer.update()

                self.update()

                elapsed = 0
                slice_ms = 25
                while elapsed < frame_delay_ms and self.is_playing:
                    QApplication.processEvents()
                    if not self.is_playing:
                        break
                    QThread.msleep(slice_ms)
                    elapsed += slice_ms
        finally:
            was_stopped = not self.is_playing
            self.is_playing = False
            if not was_stopped:
                logger.info("Finished playing states")
                self.messageSignal.emit("Finished playing states")

    def randomize_states(self, num_states: int):
        """Create randomized states for all layers."""
        if not self.layers:
            self.messageSignal.emit("No layers available to randomize.")
            return

        num_states = max(1, int(num_states))
        self.states.clear()

        canvas_width = max(1, self.width())
        canvas_height = max(1, self.height())

        for step in range(num_states):
            randomized_states = []
            for order, layer in enumerate(self.layers):
                state = layer.layer_state.copy()

                state.scale_x = random.uniform(0.5, 1.5)
                state.scale_y = random.uniform(0.5, 1.5)
                max_x = max(0.0, canvas_width - (layer.image.width() * state.scale_x))
                max_y = max(0.0, canvas_height - (layer.image.height() * state.scale_y))
                state.position = QPointF(
                    random.uniform(0.0, max_x),
                    random.uniform(0.0, max_y),
                )
                state.rotation = random.uniform(0.0, 360.0)
                state.opacity = random.randint(128, 255)
                state.order = order
                state.selected = False
                state.caption = layer.caption
                state.drawing_states = [
                    DrawingState(position=d.position, color=d.color, size=d.size)
                    for d in layer.layer_state.drawing_states
                ]
                state = self._apply_plugins_to_state(layer, state, step, num_states)
                randomized_states.append(state)

            self.states[step] = randomized_states

        self.current_step = num_states - 1
        self.seek_state(0)
        self.update()
        self.messageSignal.emit(f"Randomized {num_states} state(s).")
