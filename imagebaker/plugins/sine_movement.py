import math

from imagebaker.core.defs import LayerState
from imagebaker.plugins.base_plugin import BasePlugin


class SineMovement(BasePlugin):
    """Move a layer along a sine trajectory between two positions."""

    plugin_name = "SineMovement"

    def __init__(
        self,
        amplitude_x: float = 25.0,
        amplitude_y: float = 0.0,
        frequency: float = 0.5,
        phase: float = 0.0,
        enabled: bool = True,
    ):
        super().__init__(name=self.plugin_name, enabled=enabled)
        self.amplitude_x = float(amplitude_x)
        self.amplitude_y = float(amplitude_y)
        self.frequency = float(frequency)
        self.phase = float(phase)

    def update(
        self,
        state: LayerState,
        step: int,
        total_steps: int,
        layer=None,
        canvas=None,
    ) -> LayerState:
        steps = max(1, int(total_steps))
        if steps <= 1:
            progress = 0.0
        else:
            progress = float(step) / float(steps - 1)

        # Default to the interpolated position when no trajectory endpoints are available.
        base_x = state.position.x()
        base_y = state.position.y()
        direction_x = 1.0
        direction_y = 0.0

        # Use previous->current layer positions as the trajectory endpoints.
        if (
            layer is not None
            and getattr(layer, "previous_state", None) is not None
            and getattr(layer, "layer_state", None) is not None
        ):
            start_pos = layer.previous_state.position
            end_pos = layer.layer_state.position
            base_x = start_pos.x() + ((end_pos.x() - start_pos.x()) * progress)
            base_y = start_pos.y() + ((end_pos.y() - start_pos.y()) * progress)
            direction_x = end_pos.x() - start_pos.x()
            direction_y = end_pos.y() - start_pos.y()

        direction_len = math.hypot(direction_x, direction_y)
        if direction_len <= 1e-6:
            tangent_x, tangent_y = 1.0, 0.0
            normal_x, normal_y = 0.0, 1.0
        else:
            tangent_x = direction_x / direction_len
            tangent_y = direction_y / direction_len
            normal_x = -tangent_y
            normal_y = tangent_x

        angle = (2.0 * math.pi * self.frequency * progress) + self.phase
        wave = math.sin(angle)

        # amplitude_x = lateral arc amplitude (normal to the path)
        # amplitude_y = optional along-path oscillation
        lateral_offset = self.amplitude_x * wave
        forward_offset = self.amplitude_y * wave

        state.position.setX(
            base_x + (normal_x * lateral_offset) + (tangent_x * forward_offset)
        )
        state.position.setY(
            base_y + (normal_y * lateral_offset) + (tangent_y * forward_offset)
        )
        return state

    def describe(self) -> str:
        return (
            f"{self.name}(ax={self.amplitude_x:.1f}, ay={self.amplitude_y:.1f}, "
            f"f={self.frequency:.2f})"
        )
