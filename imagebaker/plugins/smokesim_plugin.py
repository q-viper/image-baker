from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout, suppress
from io import StringIO

import numpy as np
from smokesim.augmentation import Augmentation
from smokesim.defs import ParticleProperty, SmokeProperty
from smokesim.engine import EngineTypes
from smokesim.smoke import SmokeMachine

from imagebaker.plugins.base_plugin import BasePlugin


class SmokeSim(BasePlugin):
    """
    Apply smoke simulation over a layer using the external `smokesim` package.

    Backend-only configuration:
    - origin defaults to bottom-center of the layer image.
    - any direction or particle tuning can be set via backend override dicts below.
    """

    plugin_name = "SmokeSim"
    # Match SmokeSim example-style defaults for responsive simulation.
    DEFAULT_SMOKE_COLOR = (210, 218, 224)
    DEFAULT_SMOKE_SIZE = 25
    DEFAULT_PARTICLE_COUNT = 15
    DEFAULT_MIN_LIFETIME = 200
    DEFAULT_MAX_LIFETIME = 5000
    DEFAULT_MIN_VX = -0.16
    DEFAULT_MAX_VX = 0.16
    DEFAULT_MIN_VY = -0.95
    DEFAULT_MAX_VY = -0.28
    MAX_ADVANCE_PER_CALL = 15

    # Backend-only overrides (not exposed in Baker UI)
    BACKEND_SMOKE_OVERRIDES: dict[str, object] = {}
    BACKEND_PARTICLE_OVERRIDES: dict[str, object] = {}

    def __init__(
        self,
        random_seed: int = 100,
        time_step: float = 30.0,
        simulation_step_multiplier: int = 1,
        enabled: bool = True,
    ):
        super().__init__(name=self.plugin_name, enabled=enabled)
        self.random_seed = int(random_seed)
        self.time_step = float(time_step)
        self.simulation_step_multiplier = max(1, int(simulation_step_multiplier))
        self._cache_key: tuple | None = None
        self._frames: dict[int, np.ndarray] = {}
        self._max_cached_step = -1
        self._augmentation = None

    def _image_fingerprint(self, image: np.ndarray) -> tuple:
        rgb_sum = int(image[:, :, :3].astype(np.uint64).sum())
        alpha_sum = int(image[:, :, 3].astype(np.uint64).sum())
        return (
            int(image.shape[0]),
            int(image.shape[1]),
            rgb_sum,
            alpha_sum,
            self.random_seed,
            float(self.time_step),
            int(self.simulation_step_multiplier),
            tuple(sorted(self.BACKEND_SMOKE_OVERRIDES.items())),
            tuple(sorted(self.BACKEND_PARTICLE_OVERRIDES.items())),
        )

    def _reset(self):
        augmentation = getattr(self, "_augmentation", None)
        if augmentation is not None:
            with suppress(Exception):
                augmentation.end()
        self._augmentation = None
        frames = getattr(self, "_frames", None)
        if isinstance(frames, dict):
            frames.clear()
        self._max_cached_step = -1
        self._cache_key = None

    def _particle_property(self) -> ParticleProperty:
        min_scale = max(24, int(self.DEFAULT_SMOKE_SIZE * 0.85))
        max_scale = max(min_scale + 1, int(self.DEFAULT_SMOKE_SIZE * 2.4))
        particle_property = ParticleProperty(
            random_seed=self.random_seed,
            min_lifetime=self.DEFAULT_MIN_LIFETIME,
            max_lifetime=self.DEFAULT_MAX_LIFETIME,
            min_scale=min_scale,
            max_scale=max_scale,
            min_vx=self.DEFAULT_MIN_VX,
            max_vx=self.DEFAULT_MAX_VX,
            min_vy=self.DEFAULT_MIN_VY,
            max_vy=self.DEFAULT_MAX_VY,
            smoke_sprite_size=self.DEFAULT_SMOKE_SIZE,
            color=self.DEFAULT_SMOKE_COLOR,
        )
        for key, value in self.BACKEND_PARTICLE_OVERRIDES.items():
            if hasattr(particle_property, key):
                setattr(particle_property, key, value)
        return particle_property

    def _smoke_property(self, width: int, height: int):
        smoke_property = SmokeProperty(
            random_seed=self.random_seed,
            origin=(int(width // 2), int(max(0, height - 1))),
            particle_count=self.DEFAULT_PARTICLE_COUNT,
            color=self.DEFAULT_SMOKE_COLOR,
            sprite_size=self.DEFAULT_SMOKE_SIZE,
            particle_property=self._particle_property(),
        )

        for key, value in self.BACKEND_SMOKE_OVERRIDES.items():
            if key == "particle_property":
                continue
            if hasattr(smoke_property, key):
                setattr(smoke_property, key, value)

        if "particle_property" in self.BACKEND_SMOKE_OVERRIDES:
            backend_particle = self.BACKEND_SMOKE_OVERRIDES["particle_property"]
            if isinstance(backend_particle, ParticleProperty):
                smoke_property.particle_property = backend_particle

        return smoke_property

    @staticmethod
    def _as_rgba(array: np.ndarray, fallback_alpha: int = 255) -> np.ndarray:
        """Normalize an image array to contiguous RGBA uint8."""
        if array.ndim == 2:
            rgba = np.stack([array] * 4, axis=-1)
            if fallback_alpha == 0:
                rgba[:, :, 3] = array
            else:
                rgba[:, :, 3] = fallback_alpha
            return np.ascontiguousarray(rgba.astype(np.uint8))

        if array.shape[2] == 4:
            return np.ascontiguousarray(array.astype(np.uint8))

        if array.shape[2] == 3:
            if fallback_alpha == 0:
                alpha = np.max(array, axis=2, keepdims=True).astype(np.uint8)
            else:
                alpha = np.full((array.shape[0], array.shape[1], 1), fallback_alpha, dtype=np.uint8)
            rgba = np.concatenate([array, alpha], axis=2)
            return np.ascontiguousarray(rgba.astype(np.uint8))

        # Unexpected channel count: return a safe transparent frame to avoid crashes.
        h, w = array.shape[:2]
        return np.zeros((h, w, 4), dtype=np.uint8)

    @staticmethod
    def _compose_smoke(base_rgba: np.ndarray, smoke_rgba: np.ndarray) -> np.ndarray:
        """
        Alpha-compose smoke over base while preserving base opacity and preventing
        transparent holes introduced by repeated PIL alpha pastes.
        """
        base = base_rgba.astype(np.float32) / 255.0
        smoke = smoke_rgba.astype(np.float32) / 255.0

        base_rgb = base[:, :, :3]
        base_alpha = base[:, :, 3:4]
        smoke_rgb = smoke[:, :, :3]
        smoke_alpha = smoke[:, :, 3:4]

        out_rgb = (smoke_rgb * smoke_alpha) + (base_rgb * (1.0 - smoke_alpha))
        out_alpha = base_alpha + (smoke_alpha * (1.0 - base_alpha))

        out = np.concatenate([out_rgb, out_alpha], axis=2)
        return np.ascontiguousarray(np.clip(out * 255.0, 0, 255).astype(np.uint8))

    def _ensure_sim(self, image: np.ndarray):
        key = self._image_fingerprint(image)
        if key == self._cache_key and self._augmentation is not None:
            return

        self._reset()
        self._cache_key = key
        height, width = image.shape[:2]

        smoke_machine = SmokeMachine(
            engine_type=EngineTypes.PIL,
            random_seed=self.random_seed,
            default_particle_count=self.DEFAULT_PARTICLE_COUNT,
            default_color=self.DEFAULT_SMOKE_COLOR,
            default_sprite_size=self.DEFAULT_SMOKE_SIZE,
        )
        self._augmentation = Augmentation(
            image_path=None,
            screen_dim=(int(width), int(height)),
            smoke_machine=smoke_machine,
            random_seed=self.random_seed,
            engine_type=EngineTypes.PIL,
        )

        smoke_property = self._smoke_property(width=width, height=height)
        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            self._augmentation.add_smoke(smoke_property)

    def _render_step(self, image: np.ndarray, step: int) -> np.ndarray:
        self._ensure_sim(image=image)
        target_step = max(0, int(step)) * self.simulation_step_multiplier
        if target_step <= self._max_cached_step and target_step in self._frames:
            return self._frames[target_step]

        # If seeking backward to a step not cached explicitly, return closest cached past frame.
        if target_step < self._max_cached_step:
            for idx in range(target_step, -1, -1):
                if idx in self._frames:
                    return self._frames[idx]
            return self._frames.get(self._max_cached_step, image)

        # Advance only a bounded number of frames per paint call to avoid UI freezes.
        missing = target_step - self._max_cached_step
        advance_now = min(max(0, missing), self.MAX_ADVANCE_PER_CALL)
        if advance_now == 0:
            return self._frames.get(self._max_cached_step, image)

        for next_step in range(self._max_cached_step + 1, self._max_cached_step + 1 + advance_now):
            sink = StringIO()
            with redirect_stdout(sink), redirect_stderr(sink):
                augmented, smoke_mask = self._augmentation.augment(
                    steps=1,
                    time_step=self.time_step,
                    image=image,
                )

            base_rgba = self._as_rgba(image)
            augmented_rgba = self._as_rgba(augmented)
            smoke_rgba = self._as_rgba(smoke_mask, fallback_alpha=0)

            # Prefer explicit smoke mask composition to prevent alpha decay.
            if smoke_rgba[:, :, 3].any():
                frame = self._compose_smoke(base_rgba=base_rgba, smoke_rgba=smoke_rgba)
            else:
                # Fallback if smokesim mask alpha is unavailable.
                frame = augmented_rgba
                frame[:, :, 3] = np.maximum(base_rgba[:, :, 3], frame[:, :, 3])

            self._frames[next_step] = frame
            self._max_cached_step = next_step

        return self._frames.get(target_step, self._frames.get(self._max_cached_step, image))

    def update_pixels(
        self,
        image: np.ndarray,
        mask: np.ndarray | None,
        step: int,
        total_steps: int,
        layer=None,
        canvas=None,
    ) -> np.ndarray:
        safe_step = max(0, int(step))
        return self._render_step(image=image, step=safe_step)

    def describe(self) -> str:
        color = self.DEFAULT_SMOKE_COLOR
        return (
            f"{self.name}(seed={self.random_seed}, dt={self.time_step:.1f}, "
            f"x{self.simulation_step_multiplier}, color={color})"
        )

    def copy(self) -> SmokeSim:
        """
        Create a clean copy without duplicating runtime simulation objects.

        We avoid deepcopy because smokesim runtime carries non-pickleable module/engine
        references, which breaks undo snapshots that clone layers/plugins.
        """
        return type(self)(
            random_seed=self.random_seed,
            time_step=self.time_step,
            simulation_step_multiplier=self.simulation_step_multiplier,
            enabled=self.enabled,
        )

    def __del__(self):
        with suppress(Exception):
            self._reset()
