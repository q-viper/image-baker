from __future__ import annotations

import copy

import numpy as np

from imagebaker.core.defs import LayerState


class BasePlugin:
    """Base class for Baker plugins that can modify a layer state per step."""

    plugin_name = "BasePlugin"

    def __init__(self, name: str | None = None, enabled: bool = True):
        self.name = name or self.plugin_name
        self.enabled = enabled

    def update(
        self,
        state: LayerState,
        step: int,
        total_steps: int,
        layer=None,
        canvas=None,
    ) -> LayerState:
        """
        Update a layer state for a given step.
        Subclasses should override this.
        """
        return state

    def update_pixels(
        self,
        image: np.ndarray,
        mask: np.ndarray | None,
        step: int,
        total_steps: int,
        layer=None,
        canvas=None,
    ) -> np.ndarray:
        """
        Optionally update layer pixel data for a given step.
        `image` is RGBA uint8 array. `mask` is uint8 binary mask (0 or 255).
        """
        return image

    def copy(self) -> BasePlugin:
        """Return a deep copy of this plugin instance."""
        return copy.deepcopy(self)

    def describe(self) -> str:
        return self.name
