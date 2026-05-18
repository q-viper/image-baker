import numpy as np

from imagebaker.plugins.base_plugin import BasePlugin

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


class GaussianBlur(BasePlugin):
    """Iterative Gaussian blur plugin with mask-aware blending."""

    plugin_name = "GaussianBlur"

    def __init__(
        self,
        kernel_size: int = 11,
        max_iterations: int = 12,
        sigma: float = 1.4,
        enabled: bool = True,
    ):
        super().__init__(name=self.plugin_name, enabled=enabled)
        self.kernel_size = int(kernel_size)
        self.max_iterations = int(max_iterations)
        self.sigma = float(sigma)

    def _normalized_kernel(self):
        k = max(3, int(self.kernel_size))
        if k % 2 == 0:
            k += 1
        return k

    def _iterations_for_step(self, step: int, total_steps: int):
        steps = max(1, int(total_steps))
        ratio = (step + 1) / steps
        iters = int(round(ratio * max(1, self.max_iterations)))
        return max(2, iters)

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

        k = self._normalized_kernel()
        iterations = self._iterations_for_step(step, total_steps)
        blurred = image.copy()
        for _ in range(iterations):
            blurred = cv2.GaussianBlur(blurred, (k, k), self.sigma)

        if mask is None:
            return blurred

        mask_bool = mask > 0
        if not np.any(mask_bool):
            return image

        out = image.copy()
        out[mask_bool] = blurred[mask_bool]
        return out

    def describe(self) -> str:
        return (
            f"{self.name}(k={self._normalized_kernel()}, max_iter={self.max_iterations}, sigma={self.sigma:.2f})"
        )
