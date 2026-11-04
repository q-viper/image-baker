/**
 * ImageBaker Web - Central State & Viewport Context
 */
(function(window) {
  "use strict";

  const utils = window.ImageBaker.utils;

  const state = {
    version: "0.0.0",
    is_debug: false,
    project_name: "ImageBaker",
    project_dir: "",
    theme_mode: "dark",
    active_tab: "Layerify",
    show_gridlines: true,
    grid_spacing: 50,
    message: "Ready",
    status_bar: {
      active_tab: "Layerify",
      current_image: null,
      current_canvas: null,
      message: "Ready",
    },
    configs: {
      layer_config: { thumbnail_page_size: 15 },
      bake_config: { fps: 30 },
    },
    layerify: {
      images: [],
      curr_image_idx: null,
      current_image_index: null,
      current_image_name: null,
      current_image: null,
      annotations: [],
      labels: [],
      default_label: "Undefined",
      current_label: "Undefined",
      selected_label: "Undefined",
      current_predict_prompt: "",
      models: [],
      current_model: null,
      can_undo: false,
      can_redo: false,
      clipboard_count: 0,
    },
    baker: {
      canvases: [],
      current_canvas_id: 1,
      current_canvas: null,
      layers: [],
      states: [],
      current_step: 0,
      total_states: 0,
      selected_layer: null,
      selected_layer_id: null,
      selected_plugins: [],
      can_undo: false,
      can_redo: false,
      is_playing: false,
    },
    plugins: [],
  };

  const lyrView = {
    canvas: null,
    ctx: null,
    wrap: null,
    img: null,
    imgUrl: null,
    imgW: 0,
    imgH: 0,
    zoom: 1.0,
    offsetX: 40,
    offsetY: 40,
    activeMode: "Rectangle",
    isPanning: false,
    panStartX: 0,
    panStartY: 0,
    panStartOffX: 0,
    panStartOffY: 0,
    isInteracting: false,
    dragStartImg: null,
    draggingAnnIdx: -1,
    resizingAnnIdx: -1,
    resizeHandleId: null,
    hoverAnnIdx: -1,
    hoverHandleId: null,
    activeRectDraft: null,
    activePolyDraft: [],
    mouseImgX: 0,
    mouseImgY: 0,
    isMouseOver: false,
    brushSize: 18,
    activeBrushStroke: [],
    maskImageCache: new Map(),
    labelPillRects: [],
  };

  const bkrView = {
    canvas: null,
    ctx: null,
    wrap: null,
    zoom: 1.0,
    offsetX: 60,
    offsetY: 60,
    isPanning: false,
    panStartX: 0,
    panStartY: 0,
    panStartOffX: 0,
    panStartOffY: 0,
    draggingLayerId: null,
    dragStartScene: null,
    activeHandle: null,
    hoverHandle: null,
    hoverLayerId: null,
    sceneMouseX: 0,
    sceneMouseY: 0,
    isMouseOver: false,
    drawMode: false,
    eraseMode: false,
    brushSize: 12,
    brushColorHex: "#ff0000",
    isDrawing: false,
    currentDrawingPoints: [],
    layerImageCache: new Map(),
    playTimerId: null,
    playFps: 12,
  };

  const CURSORS = {
    IDLE: "default",
    PAN: "grab",
    PAN_ACTIVE: "grabbing",
    RECTANGLE: "crosshair",
    POINT: "crosshair",
    POLYGON: "crosshair",
    BRUSH: utils.svgCursor(
      `<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'>
        <circle cx='12' cy='12' r='8' fill='none' stroke='#2f80ed' stroke-width='2'/>
        <circle cx='12' cy='12' r='2' fill='#2f80ed'/>
      </svg>`,
      12, 12, "crosshair"
    ),
    DRAW: utils.svgCursor(
      `<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'>
        <circle cx='12' cy='12' r='7' fill='none' stroke='#eb5757' stroke-width='2'/>
        <circle cx='12' cy='12' r='1.5' fill='#eb5757'/>
      </svg>`,
      12, 12, "crosshair"
    ),
    ERASE: utils.svgCursor(
      `<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'>
        <rect x='4' y='4' width='16' height='16' rx='3' fill='none' stroke='#f2994a' stroke-width='2'/>
        <line x1='6' y1='6' x2='18' y2='18' stroke='#f2994a' stroke-width='1.5'/>
      </svg>`,
      12, 12, "cell"
    ),
  };

  function screenToImage(sx, sy) {
    return {
      x: (sx - lyrView.offsetX) / lyrView.zoom,
      y: (sy - lyrView.offsetY) / lyrView.zoom,
    };
  }

  function imageToScreen(ix, iy) {
    return {
      x: ix * lyrView.zoom + lyrView.offsetX,
      y: iy * lyrView.zoom + lyrView.offsetY,
    };
  }

  function sceneToLayerLocal(scenePt, lyr) {
    const px = lyr.position ? lyr.position[0] : 0;
    const py = lyr.position ? lyr.position[1] : 0;
    const rot = (lyr.rotation || 0) * (Math.PI / 180.0);
    const sx = lyr.scale ? lyr.scale[0] : 1.0;
    const sy = lyr.scale ? lyr.scale[1] : 1.0;

    const dx = scenePt.x - px;
    const dy = scenePt.y - py;
    const cosA = Math.cos(-rot);
    const sinA = Math.sin(-rot);
    const unrotX = dx * cosA - dy * sinA;
    const unrotY = dx * sinA + dy * cosA;

    return {
      x: unrotX / (sx || 1.0),
      y: unrotY / (sy || 1.0),
    };
  }

  function showToast(tab, text, durationMs = 2200) {
    const toast = document.getElementById(`${tab}-toast`);
    if (!toast) return;
    toast.textContent = text;
    toast.classList.remove("hidden");
    toast.style.opacity = "1";
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.classList.add("hidden"), 300);
    }, durationMs);
  }

  function showLayerifyLoading(text = "Loading image…") {
    const overlay = document.getElementById("layerify-loading-overlay");
    const label = document.getElementById("layerify-loading-text");
    if (label) label.textContent = text;
    if (overlay) overlay.classList.remove("hidden");
  }

  function hideLayerifyLoading() {
    const overlay = document.getElementById("layerify-loading-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  function openModal(dialogId) {
    const overlay = document.getElementById("modal-overlay");
    if (overlay) overlay.classList.remove("hidden");
    const target = document.getElementById(dialogId);
    if (target) {
      target.classList.remove("hidden");
      const firstInput = target.querySelector("input:not([type=hidden]), select, textarea, button.btn-primary");
      if (firstInput) setTimeout(() => firstInput.focus(), 60);
    }
  }

  function closeAllModals() {
    const overlay = document.getElementById("modal-overlay");
    if (overlay) overlay.classList.add("hidden");
    document.querySelectorAll(".modal-dialog").forEach(d => d.classList.add("hidden"));
  }

  function isModalOpen() {
    const overlay = document.getElementById("modal-overlay");
    return overlay && !overlay.classList.contains("hidden");
  }

  function isTypingInTextField(target) {
    if (!target) return false;
    const tag = target.tagName ? target.tagName.toLowerCase() : "";
    return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
  }

  function getCurrentSelectedLabelColor() {
    const currLbl = (state.layerify.current_label || "").trim() || "Undefined";
    const found = (state.layerify.labels || []).find(l => l.name === currLbl);
    return found ? found.color_hex : "#2f80ed";
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.state = state;
  window.ImageBaker.lyrView = lyrView;
  window.ImageBaker.bkrView = bkrView;
  window.ImageBaker.CURSORS = CURSORS;
  window.ImageBaker.screenToImage = screenToImage;
  window.ImageBaker.imageToScreen = imageToScreen;
  window.ImageBaker.sceneToLayerLocal = sceneToLayerLocal;
  window.ImageBaker.showToast = showToast;
  window.ImageBaker.showLayerifyLoading = showLayerifyLoading;
  window.ImageBaker.hideLayerifyLoading = hideLayerifyLoading;
  window.ImageBaker.openModal = openModal;
  window.ImageBaker.closeAllModals = closeAllModals;
  window.ImageBaker.isModalOpen = isModalOpen;
  window.ImageBaker.isTypingInTextField = isTypingInTextField;
  window.ImageBaker.getCurrentSelectedLabelColor = getCurrentSelectedLabelColor;
})(window);
