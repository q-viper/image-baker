/**
 * ImageBaker Web - Main Application Orchestrator & Entry Point
 *
 * Coordinates modularized subsystems:
 * - State & view models (js/state.js)
 * - REST API client (js/api.js)
 * - Canvas renderers (js/canvas_layerify.js, js/canvas_baker.js, js/grid.js)
 * - UI managers (js/ui_layerify.js, js/ui_baker.js)
 * - Draggable splitters & layout (js/splitters.js)
 * - Keyboard shortcuts (js/shortcuts.js)
 */
(function(window) {
  "use strict";

  const { state, lyrView, bkrView, showToast } = window.ImageBaker;
  const api = window.ImageBaker.api;
  const canvasLayerify = window.ImageBaker.canvasLayerify;
  const canvasBaker = window.ImageBaker.canvasBaker;
  const uiLayerify = window.ImageBaker.uiLayerify;
  const uiBaker = window.ImageBaker.uiBaker;
  const splitters = window.ImageBaker.splitters;
  const shortcuts = window.ImageBaker.shortcuts;

  function el(id) {
    return document.getElementById(id);
  }

  // ==================== STATE SYNCHRONIZATION ====================
  function applyServerState(serverState, options = {}) {
    if (!serverState) return;

    const keepLocalAnns =
      options.preserveLocalAnnotations ||
      lyrView.draggingAnnIdx >= 0 ||
      lyrView.resizingAnnIdx >= 0;
    const prevImgIdx = state.layerify?.current_image_index;
    const prevAnnotations =
      keepLocalAnns && Array.isArray(state.layerify?.annotations)
        ? structuredClone(state.layerify.annotations)
        : null;
    const keepLocalLayers =
      options.preserveLocalLayers || Boolean(bkrView.draggingLayerId);
    const prevCanvasId = state.baker?.current_canvas_id;
    const prevLayers =
      keepLocalLayers && Array.isArray(state.baker?.layers)
        ? structuredClone(state.baker.layers)
        : null;

    // 1. Deep merge / assign state
    Object.assign(state, serverState);

    if (
      prevAnnotations &&
      state.layerify &&
      prevImgIdx === state.layerify.current_image_index
    ) {
      state.layerify.annotations = prevAnnotations;
    }
    if (
      prevLayers &&
      state.baker &&
      prevCanvasId === state.baker.current_canvas_id
    ) {
      state.baker.layers = prevLayers;
    }

    // 2. Theme & Grid
    const isDark = state.theme_mode === "dark";
    document.body.classList.toggle("theme-dark", isDark);
    document.body.classList.toggle("theme-light", !isDark);

    const themeLabel = `Theme: ${isDark ? "Dark" : "Light"}`;
    ["btn-layerify-theme", "btn-baker-theme", "top-theme-text"].forEach(id => {
      const btn = el(id);
      if (btn) btn.textContent = themeLabel;
    });
    const themeIcon = el("top-theme-icon");
    if (themeIcon) themeIcon.textContent = isDark ? "☀️" : "🌙";

    const gridOn = Boolean(state.show_gridlines);
    const gridLabel = `Grid: ${gridOn ? "On" : "Off"}`;
    ["btn-layerify-grid", "btn-baker-grid", "btn-top-grid"].forEach(id => {
      const btn = el(id);
      if (btn) {
        btn.textContent = gridLabel;
        btn.classList.toggle("active", gridOn);
      }
    });

    const debugBadge = el("header-debug-badge");
    if (debugBadge) {
      debugBadge.classList.toggle("hidden", !state.is_debug);
    }

    // 3. Active Tab
    const activeTab = state.active_tab || "Layerify";
    const isHelpTab = activeTab === "Help";
    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.tab === activeTab);
    });
    if (el("view-layerify")) el("view-layerify").classList.toggle("active", activeTab === "Layerify");
    if (el("view-baker")) el("view-baker").classList.toggle("active", activeTab === "Baker");
    if (el("view-help")) el("view-help").classList.toggle("active", isHelpTab);

    const topZoomGroup = el("top-zoom-group") || document.querySelector(".zoom-group");
    if (topZoomGroup) topZoomGroup.classList.toggle("hidden", isHelpTab);
    if (el("btn-zoom-fit")) el("btn-zoom-fit").classList.toggle("hidden", isHelpTab);
    if (el("btn-top-grid")) el("btn-top-grid").classList.toggle("hidden", isHelpTab);
    if (el("btn-header-prev")) el("btn-header-prev").classList.toggle("hidden", isHelpTab);
    if (el("btn-header-next")) el("btn-header-next").classList.toggle("hidden", isHelpTab);

    if (activeTab === "Baker") {
      canvasBaker.resizeBakerCanvas();
      canvasBaker.fitBakerLayersIfNeeded();
    } else if (bkrView.isPlaying) {
      canvasBaker.stopPlayingStates();
    }

    // 4. Status Bar
    const statusEl = el("status-bar-text");
    const statusText = state.status_bar || state.status_message || "Ready";
    if (statusEl) {
      if (statusEl.textContent !== statusText && statusText !== "Ready") {
        window.ImageBaker.appendLog?.("server", statusText);
      }
      statusEl.textContent = statusText;
    }

    // 5. Layerify Subsystem
    const lyr = state.layerify || {};
    if (!options.preserveLocalAnnotations) {
      lyrView.annotations = structuredClone(lyr.annotations || []);
    }
    canvasLayerify.preloadAnnotationMasks(lyrView.annotations);
    canvasLayerify.syncLayerifyImage(lyr);
    uiLayerify.renderImageList();
    uiLayerify.renderAnnotationList();
    uiLayerify.renderLabelAndModelControls();

    // 6. Baker Subsystem
    const bkr = state.baker || {};
    bkr.is_playing = Boolean(bkrView.isPlaying);
    const playBtn = el("btn-play-states");
    if (playBtn) {
      playBtn.textContent = bkr.is_playing ? "⏸ Pause" : "▶ Play States";
      playBtn.classList.toggle("active", bkr.is_playing);
    }
    if (!options.preserveLocalLayers) {
      bkrView.layers = structuredClone(bkr.layers || []);
    }
    uiBaker.renderCanvasList();
    uiBaker.renderLayerLists();
    uiBaker.renderLayerSettings();
    uiBaker.renderPluginDropdown();

    // Baker timeline step readout
    const numStates = bkr.states ? bkr.states.length : (bkr.num_states || 0);
    const curStep = bkr.current_step ?? bkr.current_state_step ?? 0;
    const stepBadge = el("label-state-step");
    if (stepBadge) {
      stepBadge.textContent = `${numStates > 0 ? curStep + 1 : 0} / ${numStates}`;
    }
    const timelineSlider = el("slider-state-timeline");
    if (timelineSlider) {
      timelineSlider.max = String(Math.max(0, numStates - 1));
      timelineSlider.value = String(Math.min(curStep, Math.max(0, numStates - 1)));
      timelineSlider.disabled = (numStates <= 1);
    }

    // Undo / Redo buttons enabled state
    const lyrUndoBtn = el("strip-btn-undo");
    if (lyrUndoBtn) lyrUndoBtn.disabled = !lyr.can_undo;
    const lyrRedoBtn = el("strip-btn-redo");
    if (lyrRedoBtn) lyrRedoBtn.disabled = !lyr.can_redo;

    const bkrUndoBtn = el("btn-baker-undo");
    if (bkrUndoBtn) bkrUndoBtn.disabled = !bkr.can_undo;
    const bkrRedoBtn = el("btn-baker-redo");
    if (bkrRedoBtn) bkrRedoBtn.disabled = !bkr.can_redo;

    // 7. Header Context & Zoom
    updateTopHeaderContext();
    updateZoomReadout();

    // 8. Canvas redrawing
    requestAnimationFrame(() => {
      if (activeTab === "Baker") {
        canvasBaker.resizeBakerCanvas();
        canvasBaker.drawBakerCanvas();
      } else {
        canvasLayerify.drawLayerifyCanvas();
      }
    });
  }

  function updateTopHeaderContext() {
    const lbl = el("header-context-label");
    if (!lbl || !state) return;
    const activeTab = state.active_tab || "Layerify";
    if (activeTab === "Layerify") {
      const imgs = state.layerify?.images || [];
      const curIdx = state.layerify?.current_image_index;
      if (!imgs.length || curIdx === null || curIdx === undefined) {
        lbl.textContent = "No Images Loaded";
      } else {
        const curName = state.layerify?.current_image_name || `Image #${curIdx + 1}`;
        lbl.textContent = `${curIdx + 1} / ${imgs.length} — ${curName}`;
      }
    } else if (activeTab === "Baker") {
      const canvases = state.baker?.canvases || [];
      const curCanvas = canvases.find(c => c.selected) || canvases[0];
      if (!curCanvas) {
        lbl.textContent = "No Canvas";
      } else {
        lbl.textContent = `Canvas: ${curCanvas.name} (${curCanvas.num_layers} layers)`;
      }
    } else {
      lbl.textContent = "Shortcuts & Help";
    }
  }

  function updateZoomReadout() {
    const btn = el("btn-zoom-reset");
    if (!btn) return;
    const activeTab = state?.active_tab || "Layerify";
    const z = (activeTab === "Baker") ? bkrView.zoom : lyrView.zoom;
    btn.textContent = `${Math.round(z * 100)}%`;
  }

  // ==================== HEADER & TOP UTILITIES ====================
  function initHeaderControls() {
    // Tab switching
    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        btn.blur();
        const tab = btn.dataset.tab;
        try {
          const res = await api.updateSettings({ active_tab: tab });
          if (res.ok && res.state) applyServerState(res.state);
        } catch (err) {
          showToast(tab, err.message);
        }
      });
    });

    const gotoBakerBtn = el("btn-goto-baker");
    if (gotoBakerBtn) {
      gotoBakerBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        const res = await api.updateSettings({ active_tab: "Baker" });
        if (res.ok && res.state) applyServerState(res.state);
      });
    }

    // Step Header Prev / Next Navigation
    async function stepHeaderNavigation(delta) {
      const activeTab = state?.active_tab || "Layerify";
      if (activeTab === "Layerify") {
        const imgs = state.layerify?.images || [];
        if (!imgs.length) return;
        const curIdx = state.layerify?.current_image_index ?? 0;
        const nextIdx = Math.max(0, Math.min(imgs.length - 1, curIdx + delta));
        if (nextIdx !== curIdx) {
          try {
            const res = await api.selectImage(nextIdx);
            if (res.ok && res.state) applyServerState(res.state);
          } catch (err) {
            showToast("Layerify", err.message);
          }
        }
      } else if (activeTab === "Baker") {
        const canvases = state.baker?.canvases || [];
        if (!canvases.length) return;
        const curPos = Math.max(0, canvases.findIndex(c => c.selected));
        const nextPos = Math.max(0, Math.min(canvases.length - 1, curPos + delta));
        if (nextPos !== curPos) {
          try {
            const res = await api.manageCanvas({ action: "select", canvas_id: canvases[nextPos].canvas_id });
            if (res.ok && res.state) applyServerState(res.state);
          } catch (err) {
            showToast("Baker", err.message);
          }
        }
      }
    }
    window.ImageBaker.stepHeaderNavigation = stepHeaderNavigation;

    if (el("btn-header-prev")) {
      el("btn-header-prev").addEventListener("click", e => {
        e.currentTarget.blur();
        stepHeaderNavigation(-1);
      });
    }
    if (el("btn-header-next")) {
      el("btn-header-next").addEventListener("click", e => {
        e.currentTarget.blur();
        stepHeaderNavigation(1);
      });
    }

    // Zoom Controls
    function zoomActiveViewport(factor) {
      const activeTab = state?.active_tab || "Layerify";
      if (activeTab === "Layerify") {
        const c = lyrView.canvas;
        if (!c) return;
        const cx = c.width / 2;
        const cy = c.height / 2;
        const newZoom = Math.max(0.05, Math.min(25.0, lyrView.zoom * factor));
        lyrView.offsetX = cx - ((cx - lyrView.offsetX) / lyrView.zoom) * newZoom;
        lyrView.offsetY = cy - ((cy - lyrView.offsetY) / lyrView.zoom) * newZoom;
        lyrView.zoom = newZoom;
        canvasLayerify.drawLayerifyCanvas();
      } else if (activeTab === "Baker") {
        const c = bkrView.canvas;
        if (!c) return;
        const cx = c.width / 2;
        const cy = c.height / 2;
        const newZoom = Math.max(0.05, Math.min(25.0, bkrView.zoom * factor));
        bkrView.offsetX = cx - ((cx - bkrView.offsetX) / bkrView.zoom) * newZoom;
        bkrView.offsetY = cy - ((cy - bkrView.offsetY) / bkrView.zoom) * newZoom;
        bkrView.zoom = newZoom;
        canvasBaker.drawBakerCanvas();
      }
      updateZoomReadout();
    }

    if (el("btn-zoom-in")) el("btn-zoom-in").addEventListener("click", () => zoomActiveViewport(1.2));
    if (el("btn-zoom-out")) el("btn-zoom-out").addEventListener("click", () => zoomActiveViewport(1 / 1.2));
    if (el("btn-zoom-reset")) {
      el("btn-zoom-reset").addEventListener("click", () => {
        const activeTab = state?.active_tab || "Layerify";
        if (activeTab === "Baker") {
          bkrView.zoom = 1.0;
          bkrView.offsetX = 20;
          bkrView.offsetY = 20;
          canvasBaker.drawBakerCanvas();
        } else {
          lyrView.zoom = 1.0;
          lyrView.offsetX = 20;
          lyrView.offsetY = 20;
          canvasLayerify.drawLayerifyCanvas();
        }
        updateZoomReadout();
      });
    }
    if (el("btn-zoom-fit")) {
      el("btn-zoom-fit").addEventListener("click", () => {
        const activeTab = state?.active_tab || "Layerify";
        if (activeTab === "Baker") {
          canvasBaker.fitBakerLayersIfNeeded(true);
        } else {
          canvasLayerify.fitLayerifyImageIfNeeded();
        }
        updateZoomReadout();
      });
    }

    // Theme & Grid toggles
    async function toggleTheme(e) {
      if (e && e.currentTarget) e.currentTarget.blur();
      const next = (state.theme_mode === "dark") ? "light" : "dark";
      const res = await api.updateSettings({ theme_mode: next });
      if (res.ok && res.state) applyServerState(res.state);
    }
    async function toggleGridlines(e) {
      if (e && e.currentTarget) e.currentTarget.blur();
      const next = !Boolean(state.show_gridlines);
      const res = await api.updateSettings({ show_gridlines: next });
      if (res.ok && res.state) applyServerState(res.state);
    }

    if (el("btn-top-theme")) el("btn-top-theme").addEventListener("click", toggleTheme);
    if (el("btn-baker-theme")) el("btn-baker-theme").addEventListener("click", toggleTheme);
    if (el("btn-top-grid")) el("btn-top-grid").addEventListener("click", toggleGridlines);
    if (el("btn-baker-grid")) el("btn-baker-grid").addEventListener("click", toggleGridlines);
  }

  // ==================== APPLICATION BOOTSTRAP ====================
  async function initApp() {
    // 1. Initialize Canvas Viewports
    canvasLayerify.initLayerifyCanvas();
    canvasBaker.initBakerCanvas();

    // 2. Initialize Draggable Splitters
    splitters.initSplitters(() => {
      canvasLayerify.resizeLayerifyCanvas();
      canvasBaker.resizeBakerCanvas();
    });

    // 3. Initialize UI event bindings
    initHeaderControls();
    uiLayerify.initLayerifyUI();
    uiBaker.initBakerUI();
    shortcuts.initShortcuts();

    const logDrawer = el("web-log-drawer");
    const toggleLogsBtn = el("btn-toggle-logs");
    const closeLogsBtn = el("btn-close-logs");
    const clearLogsBtn = el("btn-clear-logs");
    if (toggleLogsBtn && logDrawer) {
      toggleLogsBtn.addEventListener("click", () => {
        logDrawer.classList.toggle("hidden");
        toggleLogsBtn.classList.toggle("active", !logDrawer.classList.contains("hidden"));
      });
    }
    if (closeLogsBtn && logDrawer) {
      closeLogsBtn.addEventListener("click", () => {
        logDrawer.classList.add("hidden");
        if (toggleLogsBtn) toggleLogsBtn.classList.remove("active");
      });
    }
    if (clearLogsBtn) {
      clearLogsBtn.addEventListener("click", () => {
        window.ImageBaker.clearLogs?.();
      });
    }

    // 4. Window resize listener
    window.addEventListener("resize", () => {
      canvasLayerify.resizeLayerifyCanvas();
      canvasBaker.resizeBakerCanvas();
    });

    // 5. Initial Server State Fetch
    try {
      const res = await api.getState();
      if (res.ok && res.state) {
        applyServerState(res.state);
      }
    } catch (err) {
      console.error("Initial state load failed:", err);
      showToast("App", "Failed to connect to ImageBaker server");
    }

    // 6. Poller for external changes (every 4s when idle)
    setInterval(async () => {
      if (
        lyrView.isDrawing ||
        lyrView.isPanning ||
        lyrView.isSyncing ||
        lyrView.draggingAnnIdx >= 0 ||
        lyrView.resizingAnnIdx >= 0 ||
        lyrView.activeRectDraft ||
        (lyrView.activePolyDraft && lyrView.activePolyDraft.length > 0) ||
        (lyrView.activeBrushStroke && lyrView.activeBrushStroke.length > 0) ||
        bkrView.draggingLayerId ||
        bkrView.isPanning ||
        bkrView.isPlaying ||
        bkrView.isSyncing
      ) {
        return;
      }
      try {
        const res = await api.getState();
        if (res.ok && res.state) {
          applyServerState(res.state, {
            preserveLocalAnnotations: true,
            preserveLocalLayers: true,
          });
        }
      } catch (_) {}
    }, 4000);
  }

  // Expose public API
  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.applyServerState = applyServerState;
  window.ImageBaker.updateZoomReadout = updateZoomReadout;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
})(window);
