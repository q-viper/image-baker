import numpy as np
import cv2


def generate_color_map(num_colors: int = 20):
    """Generate a color map for the segmentation masks"""
    np.random.seed(42)  # For reproducible colors

    colors = {}
    for i in range(num_colors):
        # Generate distinct colors with good visibility
        # Using HSV color space for better distribution
        hue = i / num_colors
        saturation = 0.8 + np.random.random() * 0.2
        value = 0.8 + np.random.random() * 0.2

        # Convert HSV to BGR (OpenCV uses BGR)
        hsv_color = np.array(
            [[[hue * 180, saturation * 255, value * 255]]], dtype=np.uint8
        )
        bgr_color = cv2.cvtColor(hsv_color, cv2.COLOR_HSV2BGR)[0][0]

        # Store as (B, G, R) tuple
        colors[i] = (int(bgr_color[0]), int(bgr_color[1]), int(bgr_color[2]))

    return colors
