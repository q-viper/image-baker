/**
 * ImageBaker Web - Draggable Sidebar Splitters
 */
(function(window) {
  "use strict";

  const STORAGE_KEY_LEFT = "imagebaker_left_dock_width";
  const STORAGE_KEY_RIGHT = "imagebaker_right_dock_width";
  const MIN_WIDTH_LEFT = 180;
  const MAX_WIDTH_LEFT = 520;
  const MIN_WIDTH_RIGHT = 220;
  const MAX_WIDTH_RIGHT = 600;

  function getStoredWidth(key, defaultVal) {
    try {
      const val = parseInt(localStorage.getItem(key), 10);
      if (!isNaN(val) && val > 50) return val;
    } catch (_) {}
    return defaultVal;
  }

  function storeWidth(key, val) {
    try {
      localStorage.setItem(key, String(Math.round(val)));
    } catch (_) {}
  }

  function applyStoredSidebarWidths() {
    const leftWidth = getStoredWidth(STORAGE_KEY_LEFT, 260);
    const rightWidth = getStoredWidth(STORAGE_KEY_RIGHT, 310);

    document.querySelectorAll(".dock-left").forEach(el => {
      el.style.width = `${leftWidth}px`;
      el.style.minWidth = `${MIN_WIDTH_LEFT}px`;
      el.style.maxWidth = `${MAX_WIDTH_LEFT}px`;
    });

    document.querySelectorAll(".dock-right-stack").forEach(el => {
      el.style.width = `${rightWidth}px`;
      el.style.minWidth = `${MIN_WIDTH_RIGHT}px`;
      el.style.maxWidth = `${MAX_WIDTH_RIGHT}px`;
    });
  }

  function initSplitters(onResizeCanvases) {
    applyStoredSidebarWidths();

    const pairs = [
      {
        resizerId: "lyr-resizer-left",
        targetSelector: "#view-layerify .dock-left",
        side: "left",
        storageKey: STORAGE_KEY_LEFT,
        min: MIN_WIDTH_LEFT,
        max: MAX_WIDTH_LEFT,
      },
      {
        resizerId: "lyr-resizer-right",
        targetSelector: "#view-layerify .dock-right-stack",
        side: "right",
        storageKey: STORAGE_KEY_RIGHT,
        min: MIN_WIDTH_RIGHT,
        max: MAX_WIDTH_RIGHT,
      },
      {
        resizerId: "bkr-resizer-left",
        targetSelector: "#view-baker .dock-left",
        side: "left",
        storageKey: STORAGE_KEY_LEFT,
        min: MIN_WIDTH_LEFT,
        max: MAX_WIDTH_LEFT,
      },
      {
        resizerId: "bkr-resizer-right",
        targetSelector: "#view-baker .dock-right-stack",
        side: "right",
        storageKey: STORAGE_KEY_RIGHT,
        min: MIN_WIDTH_RIGHT,
        max: MAX_WIDTH_RIGHT,
      },
    ];

    pairs.forEach(cfg => {
      const handle = document.getElementById(cfg.resizerId);
      if (!handle) return;

      let isDragging = false;
      let startX = 0;
      let startWidth = 0;

      handle.addEventListener("pointerdown", e => {
        const target = document.querySelector(cfg.targetSelector);
        if (!target) return;

        isDragging = true;
        startX = e.clientX;
        startWidth = target.getBoundingClientRect().width;

        handle.classList.add("dragging");
        document.body.classList.add("resizing-sidebar");
        handle.setPointerCapture(e.pointerId);
        e.preventDefault();
        e.stopPropagation();
      });

      handle.addEventListener("pointermove", e => {
        if (!isDragging) return;
        const target = document.querySelector(cfg.targetSelector);
        if (!target) return;

        let delta = e.clientX - startX;
        let newWidth;
        if (cfg.side === "left") {
          newWidth = Math.max(cfg.min, Math.min(cfg.max, startWidth + delta));
        } else {
          newWidth = Math.max(cfg.min, Math.min(cfg.max, startWidth - delta));
        }

        target.style.width = `${newWidth}px`;
        target.style.flex = `0 0 ${newWidth}px`;

        // Sync with sibling docks
        if (cfg.side === "left") {
          document.querySelectorAll(".dock-left").forEach(el => {
            el.style.width = `${newWidth}px`;
            el.style.flex = `0 0 ${newWidth}px`;
          });
        } else {
          document.querySelectorAll(".dock-right-stack").forEach(el => {
            el.style.width = `${newWidth}px`;
            el.style.flex = `0 0 ${newWidth}px`;
          });
        }

        storeWidth(cfg.storageKey, newWidth);
        if (typeof onResizeCanvases === "function") {
          onResizeCanvases();
        }
      });

      const stopDrag = e => {
        if (!isDragging) return;
        isDragging = false;
        handle.classList.remove("dragging");
        document.body.classList.remove("resizing-sidebar");
        try {
          handle.releasePointerCapture(e.pointerId);
        } catch (_) {}
        if (typeof onResizeCanvases === "function") {
          onResizeCanvases();
        }
      };

      handle.addEventListener("pointerup", stopDrag);
      handle.addEventListener("pointercancel", stopDrag);
    });
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.splitters = {
    applyStoredSidebarWidths,
    initSplitters,
  };
})(window);
