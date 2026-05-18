from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPixmap

from imagebaker import logger
from imagebaker.utils.image import qpixmap_to_numpy

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def _annotation_mask_from_shape(layer, height: int, width: int):
    if not getattr(layer, "annotations", None):
        return None
    ann = layer.annotations[0]

    if ann.mask is not None:
        mask = np.asarray(ann.mask)
        if mask.ndim == 3:
            mask = mask[:, :, 0]
        if mask.shape != (height, width):
            if cv2 is None:
                return None
            mask = cv2.resize(
                mask.astype(np.uint8),
                (width, height),
                interpolation=cv2.INTER_NEAREST,
            )
        return (mask > 0).astype(np.uint8) * 255

    mask = np.zeros((height, width), dtype=np.uint8)
    if ann.rectangle is not None:
        rect: QRectF = ann.rectangle
        x0 = max(0, min(width, int(round(rect.left()))))
        y0 = max(0, min(height, int(round(rect.top()))))
        x1 = max(0, min(width, int(round(rect.right()))))
        y1 = max(0, min(height, int(round(rect.bottom()))))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 255
        return mask

    if ann.polygon is not None and len(ann.polygon) >= 3 and cv2 is not None:
        pts = np.array([[p.x(), p.y()] for p in ann.polygon], dtype=np.float32)
        pts = np.round(pts).astype(np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(mask, [pts], 255)
        return mask

    return None


def resolve_layer_mask(layer, image_rgba: np.ndarray):
    """Resolve the effective plugin mask for a layer."""
    h, w = image_rgba.shape[:2]
    ann_mask = _annotation_mask_from_shape(layer, h, w)
    alpha_mask = (image_rgba[:, :, 3] > 0).astype(np.uint8) * 255
    if ann_mask is None:
        return alpha_mask

    # If annotation geometry is out-of-layer bounds (common when coordinates are
    # still in source-image space), fallback to alpha mask so plugins remain visible.
    ann_pixels = int(np.count_nonzero(ann_mask))
    if ann_pixels == 0:
        return alpha_mask

    effective = np.where((ann_mask > 0) & (alpha_mask > 0), 255, 0).astype(np.uint8)
    effective_pixels = int(np.count_nonzero(effective))
    alpha_pixels = int(np.count_nonzero(alpha_mask))
    if alpha_pixels > 0:
        min_usable = max(16, int(alpha_pixels * 0.01))
        if effective_pixels < min_usable:
            return alpha_mask
    return effective


def apply_pixel_plugins(layer, step: int, total_steps: int, canvas=None):
    """Apply pixel plugins for a layer and return a new pixmap."""
    plugins = getattr(layer, "plugins", [])
    if not plugins:
        return layer.image

    image = qpixmap_to_numpy(layer.image).copy()
    mask = resolve_layer_mask(layer, image)
    changed = False

    for plugin in plugins:
        if not getattr(plugin, "enabled", True):
            continue
        update_pixels = getattr(plugin, "update_pixels", None)
        if update_pixels is None:
            continue
        try:
            updated = update_pixels(
                image=image,
                mask=mask,
                step=step,
                total_steps=total_steps,
                layer=layer,
                canvas=canvas,
            )
            if updated is not None:
                image = updated
                changed = True
        except Exception as error:
            logger.error(
                f"Pixel plugin '{getattr(plugin, 'name', type(plugin).__name__)}' failed: {error}"
            )

    if not changed:
        return layer.image

    image = np.ascontiguousarray(image.astype(np.uint8))
    qimg = QImage(image.data, image.shape[1], image.shape[0], QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())
