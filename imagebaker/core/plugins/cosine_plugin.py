from imagebaker.core.plugins.base_plugin import BasePlugin
from imagebaker.core.defs import LayerState

import numpy as np
from PySide6.QtCore import QPointF


class CosinePlugin(BasePlugin):
    """
    Cosine Plugin implementation.
    """

    def __init__(self, layer_state: LayerState, amplitude=50, frequency=0.1):
        """
        Initialize the CosinePlugin.

        :param layer_state: The LayerState to modify.
        :param amplitude: The amplitude of the cosine wave (how far it moves).
        :param frequency: The frequency of the cosine wave (how fast it oscillates).
        """
        super().__init__(layer_state)
        self.amplitude = amplitude
        self.frequency = frequency

    def compute_step(self, step):
        """
        Update the x and y positions of the LayerState based on a cosine curve.

        :param step: The step to compute the cosine value for.
        """
        # Compute the new x position based on the cosine curve
        layer_state = LayerState()
        layer_state.position = QPointF(
            self.initial_layer_state.position.x()
            + self.amplitude * np.cos(self.frequency * step),
            self.initial_layer_state.position.y(),
        )

        return layer_state
