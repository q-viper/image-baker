from abc import ABC, abstractmethod
from imagebaker.core.defs import LayerState
from imagebaker import logger


class BasePlugin(ABC):

    def __init__(self, layer_state: LayerState, final_step: int = -1):
        self.initial_layer_state = layer_state
        self.final_step = final_step
        self.current_step = 0

    def __str__(self):
        return self.__class__.__name

    @abstractmethod
    def compute_step(self, step: int):
        """
        Compute the step based on the given step.

        :param step: The step to compute the step by.
        """
        pass

    def update(self, step: int = 1):
        """
        Returns the updated state after passed step.

        :param step: The step to update the state by.
        """
        if (
            self.final_step != -1
            and step > self.final_step
            or self.current_step >= self.final_step
        ):
            logger.info(f"Final step reached for {self}. Returning last step.")
            step = self.final_step
        self.compute_step(step)
        self.current_step += step
