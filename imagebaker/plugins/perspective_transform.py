import numpy as np

from imagebaker.plugins.base_plugin import BasePlugin

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


class PerspectiveTransform(BasePlugin):
    """Apply an animated perspective warp to layer pixels."""

    plugin_name = "PerspectiveTransform"

    def __init__(
        self,
        max_strength: float = 0.35,
        enabled: bool = True,
    ):
        super().__init__(name=self.plugin_name, enabled=enabled)
        self.max_strength = float(max_strength)

    def _strength_for_step(self, step: int, total_steps: int) -> float:
        steps = max(1, int(total_steps))
        ratio = float(step + 1) / float(steps)
        visible_ratio = 0.35 + (0.65 * ratio)
        return max(0.0, min(0.75, self.max_strength * visible_ratio))

    def update_pixels(
        self,
        image: np.ndarray,
        mask: np.ndarray | None,
        step: int,
        total_steps: int,
        layer=None,
        canvas=None,
    ) -> np.ndarray:
        if cv2 is None:
            return image

        h, w = image.shape[:2]
        if h < 4 or w < 4:
            return image

        strength = self._strength_for_step(step, total_steps)
        if strength <= 0.0:
            return image

        # Build a clearly visible perspective tilt/skew transform.
        inset_x = w * strength * 0.20
        inset_y = h * strength * 0.16
        skew_x = w * strength * 0.28
        skew_y = h * strength * 0.14

        src = np.array(
            [
                [0.0, 0.0],
                [float(w - 1), 0.0],
                [float(w - 1), float(h - 1)],
                [0.0, float(h - 1)],
            ],
            dtype=np.float32,
        )

        dst = np.array(
            [
                [inset_x + skew_x, inset_y],
                [float(w - 1) - inset_x + (skew_x * 0.20), inset_y + skew_y],
                [float(w - 1) - inset_x - skew_x, float(h - 1) - inset_y],
                [inset_x - (skew_x * 0.20), float(h - 1) - inset_y - skew_y],
            ],
            dtype=np.float32,
        )

        # Keep destination points safely inside the canvas bounds.
        dst[:, 0] = np.clip(dst[:, 0], 0.0, float(w - 1))
        dst[:, 1] = np.clip(dst[:, 1], 0.0, float(h - 1))

        matrix = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(
            image,
            matrix,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )

        if mask is None:
            return warped

        mask_u8 = np.where(mask > 0, 255, 0).astype(np.uint8)
        if not np.any(mask_u8):
            return image

        warped_mask = cv2.warpPerspective(
            mask_u8,
            matrix,
            (w, h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        target = (warped_mask > 0) & (warped[:, :, 3] > 0)

        out = image.copy()
        # Clear original masked area first so movement/tilt is obvious.
        out[mask_u8 > 0] = np.array([0, 0, 0, 0], dtype=np.uint8)
        out[target] = warped[target]
        return out

    def describe(self) -> str:
        return f"{self.name}(strength={self.max_strength:.2f})"
