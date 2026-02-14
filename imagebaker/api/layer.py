"""
Layer API

Provides simplified layer manipulation functionality.
"""

from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np
from PySide6.QtGui import QImage, QPixmap

from imagebaker import logger


class Layer:
    """
    Simplified Layer class for API usage.
    
    Example:
        >>> layer = Layer.from_file("image.png")
        >>> layer.set_position(100, 100)
        >>> layer.set_opacity(0.5)
        >>> layer.rotate(45)
    """
    
    def __init__(self, image: QPixmap, name: Optional[str] = None):
        """
        Initialize a Layer.
        
        Args:
            image: QPixmap image data
            name: Optional layer name
        """
        self.image = image
        self.name = name or "Layer"
        self.visible = True
        self.opacity = 1.0
        self.position = (0.0, 0.0)
        self.rotation = 0.0
        self.scale = (1.0, 1.0)
    
    @classmethod
    def from_file(cls, image_path: Union[str, Path], name: Optional[str] = None) -> "Layer":
        """
        Create a Layer from an image file.
        
        Args:
            image_path: Path to the image file
            name: Optional layer name
            
        Returns:
            Layer instance
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            raise ValueError(f"Failed to load image: {image_path}")
        
        layer_name = name or image_path.stem
        logger.info(f"Created layer '{layer_name}' from {image_path}")
        return cls(pixmap, layer_name)
    
    @classmethod
    def from_array(cls, image: np.ndarray, name: Optional[str] = None) -> "Layer":
        """
        Create a Layer from a numpy array.
        
        Args:
            image: Image as numpy array (H, W, C)
            name: Optional layer name
            
        Returns:
            Layer instance
        """
        if image.shape[2] == 4:
            format = QImage.Format_RGBA8888
        elif image.shape[2] == 3:
            format = QImage.Format_RGB888
        else:
            raise ValueError("Image must have 3 or 4 channels")
        
        height, width = image.shape[:2]
        bytes_per_line = image.strides[0]
        
        qimage = QImage(image.data, width, height, bytes_per_line, format)
        pixmap = QPixmap.fromImage(qimage.copy())
        
        layer_name = name or "Layer"
        logger.info(f"Created layer '{layer_name}' from numpy array")
        return cls(pixmap, layer_name)
    
    def set_position(self, x: float, y: float):
        """Set the position of the layer."""
        self.position = (x, y)
        logger.debug(f"Set layer '{self.name}' position to ({x}, {y})")
    
    def set_rotation(self, rotation: float):
        """Set the rotation of the layer in degrees."""
        self.rotation = rotation
        logger.debug(f"Set layer '{self.name}' rotation to {rotation}°")
    
    def set_scale(self, scale_x: float, scale_y: Optional[float] = None):
        """Set the scale of the layer."""
        if scale_y is None:
            scale_y = scale_x
        self.scale = (scale_x, scale_y)
        logger.debug(f"Set layer '{self.name}' scale to ({scale_x}, {scale_y})")
    
    def set_opacity(self, opacity: float):
        """Set the opacity of the layer (0.0 to 1.0)."""
        self.opacity = max(0.0, min(1.0, opacity))
        logger.debug(f"Set layer '{self.name}' opacity to {self.opacity}")
    
    def set_visibility(self, visible: bool):
        """Set the visibility of the layer."""
        self.visible = visible
        logger.debug(f"Set layer '{self.name}' visibility to {visible}")
    
    def get_size(self) -> Tuple[int, int]:
        """Get the size of the layer."""
        return (self.image.width(), self.image.height())
    
    def __repr__(self):
        return f"Layer(name='{self.name}', size={self.get_size()}, visible={self.visible})"
