from abc import ABC, abstractmethod
from PIL import Image
from typing import Union
import numpy as np


class BasePainter(ABC):
    def __init__(self):

        pass

    @abstractmethod
    def paint(self, image=Union[np.ndarray, Image.Image]) -> Image.Image:
        pass

    @property
    def name(self):
        return f"{self.__class__.__name__}()"
