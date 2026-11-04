"use strict";

(() => {
  // ==================== GLOBAL CLIENT STATE ====================
  let appState = null;

  // Pagination state
  let imagePage = 0;
  let canvasPage = 0;

  // Layerify Canvas Viewport & Interaction State
  const lyrView = {
    zoom: 1.0,
    offsetX: 20,
    offsetY: 20,
    img: null,
    imgKey: "",
    mode: "Rectangle", // Matches Windows LayerifyTab default startup mode
    modeBeforeSpace: null,
    annotations: [],
    hoveredIdx: null,
    hoverPosImg: null, // {x, y} in image coords
    hoverScreenPos: null, // {x, y} in canvas coords
    isLoadingImage: false,
    isPanning: false,
    panStart: { x: 0, y: 0 },
    // Drawing in-progress
    rectStart: null,
    rectEnd: null,
    polyPoints: [],
    brushSize: 18,
    brushPainting: false,
    brushCanvas: null,
    brushCtx: null,
    lastBrushPt: null,
    maskImgCache: new Map(), // mask_png_b64 -> HTMLImageElement
    // Editing in-progress
    draggingAnnIdx: null,
    dragStartImg: null,
    draggingHandle: null, // { annIdx, type: "rect"|"poly"|"point", handleIdx }
    dirtyDuringDrag: false,
    selectionChangedOnMouseDown: false,
    labelPillRects: [], // [{ annIdx, x, y, w, h }] in screen coords
  };

  // Baker Canvas Viewport & Interaction State
  const bkrView = {
    zoom: 1.0,
    offsetX: 20,
    offsetY: 20,
    layers: [],
    layerImgCache: new Map(), // url -> HTMLImageElement
    isPanning: false,
    panStart: { x: 0, y: 0 },
    // Transform interaction
    action: null, // "move" | "scale" | "rotate" | "draw" | "erase"
    activeHandleIdx: null,
    dragStartScene: null,
    dirtyDuringDrag: false,
    // Brush state
    drawingMode: false,
    eraseMode: false,
    brushColor: [255, 0, 0, 255],
    brushSize: 5,
    currentStroke: [],
    hoverCanvasPos: null,
    // Timeline playback
    playTimer: null,
  };

  // Modal state
  let annIoMode = "save"; // "save" | "load"
  let editCaptionContext = null; // { type: "layerify", annIdx } | { type: "baker" }

  // ==================== DOM REFERENCES ====================
  const el = (id) => document.getElementById(id);

  const lyrCanvas = el("layerify-canvas");
  const lyrCtx = lyrCanvas.getContext("2d");
  const bkrCanvas = el("baker-canvas");
  const bkrCtx = bkrCanvas.getContext("2d");

  // ==================== API HELPERS ====================
  async function apiGet(path) {
    const res = await fetch(path, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.message || data.error || `Request failed (${res.status})`);
    }
    return data;
  }

  async function apiPost(path, payload = {}) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.message || data.error || `Request failed (${res.status})`);
    }
    return data;
  }

  function showToast(tab, text, durationMs = 2200) {
    const toast = el(tab === "Baker" ? "baker-toast" : "layerify-toast");
    if (!toast) return;
    toast.textContent = text;
    toast.classList.remove("hidden");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toast.classList.add("hidden");
    }, durationMs);
  }

  // ==================== STATE SYNCHRONIZATION ====================
  function applyServerState(state, options = {}) {
    if (!state) return;
    appState = state;

    // 1. Theme & Grid (Top-Right Theme + Legacy Buttons)
    const isDark = state.theme_mode === "dark";
    document.body.classList.toggle("theme-dark", isDark);
    document.body.classList.toggle("theme-light", !isDark);

    const themeLabel = `Theme: ${isDark ? "Dark" : "Light"}`;
    if (el("btn-layerify-theme")) el("btn-layerify-theme").textContent = themeLabel;
    if (el("btn-baker-theme")) el("btn-baker-theme").textContent = themeLabel;
    if (el("top-theme-text")) el("top-theme-text").textContent = themeLabel;
    if (el("top-theme-icon")) el("top-theme-icon").textContent = isDark ? "☀️" : "🌙";

    const gridOn = Boolean(state.show_gridlines);
    const gridLabel = `Grid: ${gridOn ? "On" : "Off"}`;
    if (el("btn-layerify-grid")) {
      el("btn-layerify-grid").textContent = gridLabel;
      el("btn-layerify-grid").classList.toggle("active", gridOn);
    }
    if (el("btn-baker-grid")) {
      el("btn-baker-grid").textContent = gridLabel;
      el("btn-baker-grid").classList.toggle("active", gridOn);
    }
    if (el("btn-top-grid")) {
      el("btn-top-grid").textContent = gridLabel;
      el("btn-top-grid").classList.toggle("active", gridOn);
    }

    if (el("header-debug-badge")) {
      el("header-debug-badge").classList.toggle("hidden", !state.is_debug);
    }

    // 2. Active Tab
    const activeTab = state.active_tab || "Layerify";
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === activeTab);
    });
    el("view-layerify").classList.toggle("active", activeTab === "Layerify");
    el("view-baker").classList.toggle("active", activeTab === "Baker");
    el("view-help").classList.toggle("active", activeTab === "Help");

    // 3. Status Bar
    el("status-bar-text").textContent = state.status_bar || state.status_message || "Ready";

    // 4. Layerify State
    const lyr = state.layerify || {};
    if (!options.preserveLocalAnnotations) {
      lyrView.annotations = structuredClone(lyr.annotations || []);
    }
    preloadAnnotationMasks(lyrView.annotations);
    syncLayerifyImage(lyr);
    renderImageList(lyr);
    renderAnnotationList(lyrView.annotations);
    renderLabelAndModelControls(lyr);

    // 5. Baker State
    const bkr = state.baker || {};
    if (!options.preserveLocalLayers) {
      bkrView.layers = structuredClone(bkr.layers || []);
    }
    renderCanvasList(bkr);
    renderLayerLists(bkrView.layers);
    renderLayerSettings(bkrView.layers);
    renderBakerToolbar(bkr);

    // 6. Header Context & Zoom Readout
    updateTopHeaderContext();
    updateZoomReadout();

    // 7. Redraw canvases
    requestAnimationFrame(() => {
      resizeCanvases();
      drawLayerifyCanvas();
      drawBakerCanvas();
    });
  }

  function updateTopHeaderContext() {
    const lbl = el("header-context-label");
    if (!lbl || !appState) return;
    const activeTab = appState.active_tab || "Layerify";
    if (activeTab === "Layerify") {
      const imgs = appState.layerify?.images || [];
      const curIdx = appState.layerify?.current_image_index;
      if (!imgs.length || curIdx === null || curIdx === undefined) {
        lbl.textContent = "No Images Loaded";
      } else {
        const curName = appState.layerify?.current_image_name || `Image #${curIdx + 1}`;
        lbl.textContent = `${curIdx + 1} / ${imgs.length} — ${curName}`;
      }
    } else if (activeTab === "Baker") {
      const canvases = appState.baker?.canvases || [];
      const curCanvas = canvases.find((c) => c.selected) || canvases[0];
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
    const activeTab = appState?.active_tab || "Layerify";
    const z = activeTab === "Baker" ? bkrView.zoom : lyrView.zoom;
    btn.textContent = `${Math.round(z * 100)}%`;
  }

  function preloadAnnotationMasks(annotations) {
    (annotations || []).forEach((ann) => {
      if (ann.mask_png_b64 && !lyrView.maskImgCache.has(ann.mask_png_b64)) {
        const mImg = new Image();
        mImg.onload = () => {
          lyrView.maskImgCache.set(ann.mask_png_b64, mImg);
          drawLayerifyCanvas();
        };
        mImg.src = `data:image/png;base64,${ann.mask_png_b64}`;
      }
    });
  }

  // ==================== LAYERIFY UI RENDERING ====================
  function showLayerifyLoading(text = "Loading image…") {
    const overlay = el("layerify-loading-overlay");
    const label = el("layerify-loading-text");
    if (label) label.textContent = text;
    if (overlay) overlay.classList.remove("hidden");
  }

  function hideLayerifyLoading() {
    const overlay = el("layerify-loading-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  function syncLayerifyImage(lyr) {
    const idx = lyr.current_image_index;
    const rev = lyr.current_image_revision || 0;
    if (idx === null || idx === undefined || idx < 0) {
      lyrView.img = null;
      lyrView.imgKey = "";
      lyrView.isLoadingImage = false;
      hideLayerifyLoading();
      drawLayerifyCanvas();
      return;
    }
    const key = `${idx}:${rev}:${lyr.current_image_name}`;
    if (lyrView.imgKey === key && lyrView.img) {
      hideLayerifyLoading();
      return;
    }
    lyrView.imgKey = key;
    lyrView.img = null;
    lyrView.isLoadingImage = true;
    showLayerifyLoading(`Loading ${lyr.current_image_name || "image"}…`);
    drawLayerifyCanvas();

    const img = new Image();
    img.onload = () => {
      if (lyrView.imgKey !== key) return;
      lyrView.img = img;
      lyrView.isLoadingImage = false;
      hideLayerifyLoading();
      // Fit image nicely on first load
      fitLayerifyImageIfNeeded();
      drawLayerifyCanvas();
      updateZoomReadout();
    };
    img.onerror = () => {
      if (lyrView.imgKey !== key) return;
      lyrView.isLoadingImage = false;
      hideLayerifyLoading();
      drawLayerifyCanvas();
    };
    img.src = `/api/layerify/image?index=${idx}&rev=${rev}`;
  }

  function fitLayerifyImageIfNeeded() {
    if (!lyrView.img) return;
    const w = lyrCanvas.width || 800;
    const h = lyrCanvas.height || 600;
    const scaleX = (w - 40) / Math.max(1, lyrView.img.width);
    const scaleY = (h - 40) / Math.max(1, lyrView.img.height);
    const fitScale = Math.min(1.0, Math.max(0.1, Math.min(scaleX, scaleY)));
    lyrView.zoom = fitScale;
    lyrView.offsetX = Math.max(12, Math.floor((w - lyrView.img.width * fitScale) / 2));
    lyrView.offsetY = Math.max(12, Math.floor((h - lyrView.img.height * fitScale) / 2));
  }

  function renderImageList(lyr) {
    const container = el("image-list-items");
    const pageInfo = el("img-page-info");
    const prevBtn = el("img-prev-btn");
    const nextBtn = el("img-next-btn");

    const images = lyr.images || [];
    if (el("badge-image-total")) el("badge-image-total").textContent = String(images.length);
    const pageSize = (appState?.configs?.layer_config?.thumbnail_page_size) || 10;
    const total = images.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (imagePage >= totalPages) imagePage = totalPages - 1;
    if (imagePage < 0) imagePage = 0;

    const start = imagePage * pageSize;
    const end = Math.min(start + pageSize, total);

    container.innerHTML = "";
    for (let i = start; i < end; i++) {
      const item = images[i];
      const row = document.createElement("div");
      row.className = `list-item ${item.selected ? "selected" : ""}`;
      row.innerHTML = `
        <img class="item-thumb" src="${item.thumbnail}" alt="${escapeHtml(item.name)}" />
        <div class="item-text-col">
          <div class="item-title" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
          <div class="item-subtitle">${item.width} × ${item.height}</div>
        </div>
      `;
      row.addEventListener("click", async () => {
        try {
          showLayerifyLoading(`Loading ${item.full_name || item.name}…`);
          const res = await apiPost("/api/layerify/select-image", { index: item.index });
          applyServerState(res.state);
        } catch (err) {
          hideLayerifyLoading();
          showToast("Layerify", err.message);
        }
      });
      container.appendChild(row);
    }

    if (total === 0) {
      pageInfo.textContent = "No items";
    } else {
      pageInfo.textContent = `Showing ${start + 1} to ${end} of ${total}`;
    }
    prevBtn.disabled = imagePage === 0;
    nextBtn.disabled = end >= total;
  }

  function getAnnotationGeometryTag(ann) {
    if (ann.mask_png_b64) return { icon: "🖌️", tag: "Brush" };
    if (ann.polygon && ann.polygon.length >= 3) return { icon: "🔷", tag: `Poly(${ann.polygon.length})` };
    if (ann.rectangle && ann.rectangle.length === 4) return { icon: "🔳", tag: "Rect" };
    if (ann.points && ann.points.length > 0) return { icon: "📍", tag: "Point" };
    return { icon: "•", tag: "Region" };
  }

  function renderAnnotationList(annotations) {
    const container = el("annotation-list-items");
    container.innerHTML = "";
    if (el("badge-ann-total")) el("badge-ann-total").textContent = String(annotations.length);

    // Update Selected Region Inspector Banner
    const inspector = el("selected-region-inspector");
    const selIndices = annotations.map((a, i) => (a.selected ? i : -1)).filter((i) => i >= 0);
    if (inspector) {
      if (selIndices.length === 1) {
        const idx = selIndices[0];
        const ann = annotations[idx];
        const geom = getAnnotationGeometryTag(ann);
        inspector.classList.remove("hidden");
        el("inspector-region-name").textContent = `#${idx + 1} ${geom.icon} ${ann.label} (${geom.tag})`;
        el("inspector-region-sub").textContent = ann.caption
          ? `💬 "${ann.caption}"`
          : "Press 0-9 to relabel • C to add caption • L to bake";
      } else if (selIndices.length > 1) {
        inspector.classList.remove("hidden");
        el("inspector-region-name").textContent = `${selIndices.length} Regions Selected`;
        el("inspector-region-sub").textContent = "Press 0-9 to relabel all • L to bake • Del to delete";
      } else {
        inspector.classList.add("hidden");
      }
    }

    annotations.forEach((ann, idx) => {
      const row = document.createElement("div");
      row.className = `list-item ${ann.selected ? "selected" : ""}`;
      const [r, g, b] = ann.color || [255, 128, 0];
      const geom = getAnnotationGeometryTag(ann);
      const scoreText =
        ann.score !== null && ann.score !== undefined
          ? `${ann.annotator || "manual"} (${Number(ann.score).toFixed(2)})`
          : ann.annotator || "manual";
      const capPart = ann.caption ? ` • 💬 "${ann.caption}"` : "";
      const visEmoji = ann.visible !== false ? "👀" : "👁️";

      row.innerHTML = `
        <div class="item-color-swatch" style="background-color: rgb(${r},${g},${b});"></div>
        <div class="item-text-col">
          <div class="item-title" title="${escapeHtml(ann.label)}">#${idx + 1} ${geom.icon} ${escapeHtml(ann.label)}</div>
          <div class="item-subtitle">${escapeHtml(geom.tag)} • ${escapeHtml(scoreText)}${escapeHtml(capPart)}</div>
        </div>
        <div class="item-actions">
          <button class="icon-btn btn-ann-cap" title="Edit Label / Caption (C)">💬</button>
          <button class="icon-btn btn-ann-bake" title="Bake layer from annotation (L)">🖨</button>
          <button class="icon-btn btn-ann-vis" title="Toggle visibility (H)">${visEmoji}</button>
          <button class="icon-btn btn-ann-del" title="Delete annotation (Del)">🗑️</button>
        </div>
      `;

      row.addEventListener("mouseenter", () => {
        lyrView.hoveredIdx = idx;
        drawLayerifyCanvas();
      });
      row.addEventListener("mouseleave", () => {
        if (lyrView.hoveredIdx === idx) {
          lyrView.hoveredIdx = null;
          drawLayerifyCanvas();
        }
      });

      row.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        const multi = e.ctrlKey || e.metaKey || e.shiftKey;
        lyrView.annotations.forEach((a, i) => {
          if (i === idx) {
            a.selected = multi ? !a.selected : true;
          } else if (!multi) {
            a.selected = false;
          }
        });
        syncAnnotationsToServer(false, "Selected annotation");
      });

      row.addEventListener("dblclick", (e) => {
        if (e.target.closest("button")) return;
        openEditCaptionModal({ type: "layerify", annIdx: idx });
      });

      row.querySelector(".btn-ann-cap").addEventListener("click", (e) => {
        e.stopPropagation();
        openEditCaptionModal({ type: "layerify", annIdx: idx });
      });

      row.querySelector(".btn-ann-bake").addEventListener("click", async (e) => {
        e.stopPropagation();
        await layerifyAnnotations([ann.annotation_id]);
      });

      row.querySelector(".btn-ann-vis").addEventListener("click", (e) => {
        e.stopPropagation();
        ann.visible = ann.visible === false ? true : false;
        syncAnnotationsToServer(true, `Visibility: ${ann.label}`);
      });

      row.querySelector(".btn-ann-del").addEventListener("click", (e) => {
        e.stopPropagation();
        lyrView.annotations.splice(idx, 1);
        syncAnnotationsToServer(true, `Deleted annotation: ${ann.label}`);
      });

      container.appendChild(row);
    });
  }

  async function selectLabelAndMaybeAssign(labelName) {
    try {
      const res = await apiPost("/api/layerify/labels", {
        action: "select",
        label: labelName,
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Layerify", err.message);
    }
  }

  function renderLabelAndModelControls(lyr) {
    const labelSelect = el("select-label");
    const labels = lyr.labels || [];
    if (labelSelect) {
      labelSelect.innerHTML = "";
      labels.forEach((lbl) => {
        const opt = document.createElement("option");
        opt.value = lbl.name;
        opt.textContent = lbl.name;
        if (lbl.name === lyr.selected_label) opt.selected = true;
        labelSelect.appendChild(opt);
      });
    }

    // Render Label Studio-style clickable label chips with hotkeys [0]..[9]
    const chipsWrap = el("ls-label-chips");
    if (chipsWrap) {
      chipsWrap.innerHTML = "";
      labels.forEach((lbl, idx) => {
        const [r, g, b] = lbl.color || [255, 255, 255];
        const hex = rgbToHex(r, g, b);
        const isCurrent = lbl.name === (lyr.selected_label || "Undefined");
        const chip = document.createElement("button");
        chip.className = `ls-label-chip ${isCurrent ? "active" : ""}`;
        if (isCurrent) {
          chip.style.borderColor = hex;
        }
        chip.title =
          lbl.name === "Undefined"
            ? `Default label "Undefined" (active when no other label is selected)`
            : `Select label "${lbl.name}" ${idx < 10 ? `(Hotkey: ${idx})` : ""} — Click again to deselect to Undefined, or double-click to edit`;
        chip.innerHTML = `
          <span class="ls-chip-swatch" style="background-color: ${hex};"></span>
          <span>${escapeHtml(lbl.name)}</span>
          ${idx < 10 ? `<kbd class="ls-chip-key">${idx}</kbd>` : ""}
        `;
        chip.addEventListener("click", () => {
          chip.blur();
          const nextLabel =
            isCurrent && lbl.name !== "Undefined" ? "Undefined" : lbl.name;
          selectLabelAndMaybeAssign(nextLabel);
        });
        chip.addEventListener("dblclick", (e) => {
          e.stopPropagation();
          openManageLabelsDialog();
        });
        chipsWrap.appendChild(chip);
      });
    }

    const curLblObj = labels.find((l) => l.name === lyr.selected_label);
    if (curLblObj && curLblObj.color && el("input-label-color-picker")) {
      const [r, g, b] = curLblObj.color;
      el("input-label-color-picker").value = rgbToHex(r, g, b);
    }

    const modelSelect = el("select-model");
    if (modelSelect) {
      const models = lyr.models || ["None"];
      modelSelect.innerHTML = "";
      models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (m === lyr.selected_model) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    }

    const canPredict =
      lyr.selected_model && lyr.selected_model !== "None" && lyr.current_image_index !== null;
    if (el("btn-predict")) el("btn-predict").disabled = !canPredict;
    if (el("btn-predict-state")) {
      el("btn-predict-state").disabled = !(lyr.selected_model && lyr.selected_model !== "None");
    }
    if (el("strip-btn-undo")) {
      el("strip-btn-undo").disabled = !(lyr.can_undo || lyrView.polyPoints.length > 0);
    }
    if (el("strip-btn-redo")) {
      el("strip-btn-redo").disabled = !lyr.can_redo;
    }

    const manageModal = el("modal-manage-label");
    if (manageModal && !manageModal.classList.contains("hidden")) {
      renderManageLabelsModal();
    }
  }

  // ==================== BAKER UI RENDERING ====================
  function renderCanvasList(bkr) {
    const container = el("canvas-list-items");
    const pageInfo = el("canvas-page-info");
    const prevBtn = el("canvas-prev-btn");
    const nextBtn = el("canvas-next-btn");

    const canvases = bkr.canvases || [];
    const pageSize = 5;
    const total = canvases.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (canvasPage >= totalPages) canvasPage = totalPages - 1;
    if (canvasPage < 0) canvasPage = 0;

    const start = canvasPage * pageSize;
    const end = Math.min(start + pageSize, total);

    container.innerHTML = "";
    for (let i = start; i < end; i++) {
      const c = canvases[i];
      const row = document.createElement("div");
      row.className = `list-item ${c.selected ? "selected" : ""}`;
      row.innerHTML = `
        <img class="item-thumb" src="${c.thumbnail}" alt="${escapeHtml(c.name)}" />
        <div class="item-text-col">
          <div class="item-title" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</div>
          <div class="item-subtitle">${c.num_layers} layer(s) • ${c.num_states} state(s)</div>
        </div>
        <div class="item-actions">
          <button class="icon-btn btn-canvas-del" title="Delete Canvas">🗑️</button>
        </div>
      `;

      row.addEventListener("click", async (e) => {
        if (e.target.closest("button")) return;
        try {
          const res = await apiPost("/api/baker/canvas", {
            action: "select",
            canvas_id: c.canvas_id,
          });
          applyServerState(res.state);
        } catch (err) {
          showToast("Baker", err.message);
        }
      });

      row.querySelector(".btn-canvas-del").addEventListener("click", async (e) => {
        e.stopPropagation();
        if (canvases.length <= 1) {
          showToast("Baker", "Cannot delete the last remaining canvas.");
          return;
        }
        try {
          const res = await apiPost("/api/baker/canvas", {
            action: "delete",
            canvas_id: c.canvas_id,
          });
          applyServerState(res.state);
        } catch (err) {
          showToast("Baker", err.message);
        }
      });

      container.appendChild(row);
    }

    pageInfo.textContent = `Showing ${end - start} of ${total}`;
    prevBtn.disabled = canvasPage === 0;
    nextBtn.disabled = end >= total;
  }

  function renderLayerLists(layers) {
    if (el("badge-lyr-layers-total")) el("badge-lyr-layers-total").textContent = String(layers.length);
    if (el("badge-bkr-layers-total")) el("badge-bkr-layers-total").textContent = String(layers.length);
    const containers = [el("layerify-layer-list-items"), el("baker-layer-list-items")];
    const selectedPluginCount = (appState?.baker?.selected_plugins || []).length;

    containers.forEach((container) => {
      if (!container) return;
      container.innerHTML = "";

      layers.forEach((lyr, idx) => {
        const row = document.createElement("div");
        row.className = `list-item ${lyr.selected ? "selected" : ""}`;
        row.draggable = true;
        row.dataset.layerId = String(lyr.layer_id);

        const posX = Math.round(lyr.position?.[0] || 0);
        const posY = Math.round(lyr.position?.[1] || 0);
        const sx = Number(lyr.scale_x ?? 1).toFixed(2);
        const sy = Number(lyr.scale_y ?? 1).toFixed(2);
        const op = Math.round(lyr.opacity ?? 255);
        const eo = Math.round(lyr.edge_opacity ?? 255);
        const subtitle = `X:(${posX},${posY}) Scale:${sx},${sy} O:${op} E:${eo} (P:${selectedPluginCount})`;
        const visEmoji = lyr.visible !== false ? "👀" : "👁️";

        row.innerHTML = `
          <img class="item-thumb" src="${lyr.thumbnail}" alt="${escapeHtml(lyr.label)}" />
          <div class="item-text-col">
            <div class="item-title" title="ID: ${lyr.layer_id} (${escapeHtml(lyr.layer_name)})">${escapeHtml(lyr.label)}</div>
            <div class="item-subtitle" title="${escapeHtml(subtitle)}">${escapeHtml(subtitle)}</div>
          </div>
          <div class="item-actions">
            <button class="icon-btn btn-lyr-vis" title="Toggle Layer Visibility">${visEmoji}</button>
            <button class="icon-btn btn-lyr-del" title="Delete Layer">🗑️</button>
            <input type="checkbox" class="chk-lyr-export" title="Export annotation for this layer" ${lyr.allow_annotation_export !== false ? "checked" : ""} />
          </div>
        `;

        // Click to select
        row.addEventListener("click", (e) => {
          if (e.target.closest("button") || e.target.closest("input")) return;
          const multi = e.ctrlKey || e.metaKey;
          bkrView.layers.forEach((item, i) => {
            if (i === idx) {
              item.selected = multi ? !item.selected : true;
            } else if (!multi) {
              item.selected = false;
            }
          });
          syncLayersToServer(false, `Selected layer ${lyr.label}`);
        });

        // Visibility toggle
        row.querySelector(".btn-lyr-vis").addEventListener("click", (e) => {
          e.stopPropagation();
          bkrView.layers[idx].visible = bkrView.layers[idx].visible === false ? true : false;
          syncLayersToServer(true, `Visibility toggled: ${lyr.label}`);
        });

        // Delete button
        row.querySelector(".btn-lyr-del").addEventListener("click", async (e) => {
          e.stopPropagation();
          try {
            const res = await apiPost("/api/baker/layers/action", {
              action: "delete",
              layer_id: lyr.layer_id,
            });
            applyServerState(res.state);
          } catch (err) {
            showToast("Baker", err.message);
          }
        });

        // Export checkbox
        row.querySelector(".chk-lyr-export").addEventListener("change", (e) => {
          e.stopPropagation();
          bkrView.layers[idx].allow_annotation_export = e.target.checked;
          syncLayersToServer(false, `Export toggled: ${lyr.label}`);
        });

        // Drag and Drop reordering
        row.addEventListener("dragstart", (e) => {
          row.classList.add("dragging");
          e.dataTransfer.setData("text/plain", String(lyr.layer_id));
        });
        row.addEventListener("dragend", () => {
          row.classList.remove("dragging");
        });
        row.addEventListener("dragover", (e) => {
          e.preventDefault();
        });
        row.addEventListener("drop", async (e) => {
          e.preventDefault();
          const draggedId = Number(e.dataTransfer.getData("text/plain"));
          const targetId = lyr.layer_id;
          if (!draggedId || draggedId === targetId) return;
          const currentOrder = bkrView.layers.map((l) => l.layer_id);
          const fromIdx = currentOrder.indexOf(draggedId);
          const toIdx = currentOrder.indexOf(targetId);
          if (fromIdx < 0 || toIdx < 0) return;
          currentOrder.splice(fromIdx, 1);
          currentOrder.splice(toIdx, 0, draggedId);
          try {
            const res = await apiPost("/api/baker/layers/reorder", { order: currentOrder });
            applyServerState(res.state);
          } catch (err) {
            showToast("Baker", err.message);
          }
        });

        container.appendChild(row);
      });
    });
  }

  function renderLayerSettings(layers) {
    const selected = layers.filter((l) => l.selected);
    const active = selected.length === 1 ? selected[0] : null;
    const disabled = !active;

    const sliders = [
      "slider-opacity",
      "slider-xpos",
      "slider-ypos",
      "slider-scalex",
      "slider-scaley",
      "slider-rotation",
      "slider-edge-opacity",
      "slider-edge-width",
      "input-layer-caption",
    ];
    sliders.forEach((id) => {
      el(id).disabled = disabled;
    });

    if (!active) {
      if (el("selected-layer-banner")) {
        el("selected-layer-banner").textContent =
          selected.length > 1 ? `${selected.length} Layers Selected` : "No BaseLayer Selected";
      }
      el("val-opacity").textContent = "255";
      el("val-xpos").textContent = "0";
      el("val-ypos").textContent = "0";
      el("val-scalex").textContent = "1.00";
      el("val-scaley").textContent = "1.00";
      el("val-rotation").textContent = "0";
      el("val-edge-opacity").textContent = "255";
      el("val-edge-width").textContent = "0";
      el("input-layer-caption").value = "";
      return;
    }

    if (el("selected-layer-banner")) {
      el("selected-layer-banner").textContent = `${active.label} (ID: ${active.layer_id})`;
    }

    const op = Math.round(active.opacity ?? 255);
    const x = Math.round(active.position?.[0] ?? 0);
    const y = Math.round(active.position?.[1] ?? 0);
    const sx = Number(active.scale_x ?? 1.0);
    const sy = Number(active.scale_y ?? 1.0);
    const rot = Math.round(active.rotation ?? 0);
    const eo = Math.round(active.edge_opacity ?? 255);
    const ew = Math.round(active.edge_width ?? 1);

    el("slider-opacity").value = String(op);
    el("val-opacity").textContent = String(op);

    el("slider-xpos").value = String(x);
    el("val-xpos").textContent = String(x);

    el("slider-ypos").value = String(y);
    el("val-ypos").textContent = String(y);

    el("slider-scalex").value = String(Math.round(sx * 100));
    el("val-scalex").textContent = sx.toFixed(2);

    el("slider-scaley").value = String(Math.round(sy * 100));
    el("val-scaley").textContent = sy.toFixed(2);

    el("slider-rotation").value = String(rot);
    el("val-rotation").textContent = String(rot);

    el("slider-edge-opacity").value = String(eo);
    el("val-edge-opacity").textContent = String(eo);

    el("slider-edge-width").value = String(ew);
    el("val-edge-width").textContent = String(ew);

    if (document.activeElement !== el("input-layer-caption")) {
      el("input-layer-caption").value = active.caption || "";
    }
  }

  function renderBakerToolbar(bkr) {
    const numStates = bkr.num_states || 0;
    const currentStep = bkr.current_state_step || 0;
    const slider = el("slider-state-timeline");
    const badge = el("label-state-step");

    if (numStates > 0) {
      slider.disabled = false;
      slider.min = "0";
      slider.max = String(numStates - 1);
      slider.value = String(Math.min(currentStep, numStates - 1));
      badge.textContent = `${Math.min(currentStep, numStates - 1) + 1} / ${numStates}`;
    } else {
      slider.disabled = true;
      slider.min = "0";
      slider.max = "0";
      slider.value = "0";
      badge.textContent = "0 / 0";
      stopPlayingStates();
    }

    const hasStates = numStates > 0;
    el("btn-play-states").disabled = !hasStates;
    el("btn-clear-states").disabled = !hasStates;
    el("btn-annotate-states").disabled = !hasStates;
    el("btn-export-states").disabled = !hasStates;
    if (el("btn-baker-undo")) el("btn-baker-undo").disabled = !bkr.can_undo;
    if (el("btn-baker-redo")) el("btn-baker-redo").disabled = !bkr.can_redo;

    // Plugin list
    const pluginListEl = el("plugin-checkbox-list");
    pluginListEl.innerHTML = "";
    const available = bkr.available_plugins || [];
    const selectedSet = new Set(bkr.selected_plugins || []);

    if (available.length === 0) {
      const empty = document.createElement("div");
      empty.className = "item-subtitle";
      empty.style.padding = "4px 8px";
      empty.textContent = "No plugins found";
      pluginListEl.appendChild(empty);
    } else {
      available.forEach((pName) => {
        const lbl = document.createElement("label");
        lbl.className = "dropdown-item";
        lbl.innerHTML = `
          <input type="checkbox" value="${escapeHtml(pName)}" ${selectedSet.has(pName) ? "checked" : ""} />
          <span>${escapeHtml(pName)}</span>
        `;
        lbl.querySelector("input").addEventListener("change", async () => {
          const checked = Array.from(
            pluginListEl.querySelectorAll("input[type='checkbox']:checked")
          ).map((el) => el.value);
          try {
            const res = await apiPost("/api/baker/plugins", {
              action: "set",
              plugins: checked,
            });
            applyServerState(res.state);
          } catch (err) {
            showToast("Baker", err.message);
          }
        });
        pluginListEl.appendChild(lbl);
      });
    }
  }

  // ==================== CANVAS GEOMETRY & DRAWING ====================
  function resizeCanvases() {
    const lyrWrap = el("layerify-canvas-wrap");
    if (lyrWrap && lyrWrap.clientWidth > 0 && lyrWrap.clientHeight > 0) {
      if (lyrCanvas.width !== lyrWrap.clientWidth || lyrCanvas.height !== lyrWrap.clientHeight) {
        lyrCanvas.width = lyrWrap.clientWidth;
        lyrCanvas.height = lyrWrap.clientHeight;
      }
    }
    const bkrWrap = el("baker-canvas-wrap");
    if (bkrWrap && bkrWrap.clientWidth > 0 && bkrWrap.clientHeight > 0) {
      if (bkrCanvas.width !== bkrWrap.clientWidth || bkrCanvas.height !== bkrWrap.clientHeight) {
        bkrCanvas.width = bkrWrap.clientWidth;
        bkrCanvas.height = bkrWrap.clientHeight;
      }
    }
  }

  function drawGridlines(ctx, width, height, offsetX, offsetY, zoom, hoverPos = null, imgW = null, imgH = null) {
    if (!appState?.show_gridlines) return;
    const isDark = appState?.theme_mode === "dark";
    const z = Math.max(0.001, zoom);

    // Determine target image dimension
    const targetW = Math.max(1, imgW || (lyrView.img ? lyrView.img.width : 1000));
    const targetH = Math.max(1, imgH || (lyrView.img ? lyrView.img.height : 1000));

    // Choose fine, mid, and major steps in image pixel units relative to image dimension
    // As deep as possible: down to 1px when zoom is sufficient
    const candidateSteps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000];
    let fineStep = candidateSteps[candidateSteps.length - 1];
    for (const s of candidateSteps) {
      if (s * z >= 5.0) {
        fineStep = s;
        break;
      }
    }
    let midStep = fineStep * 5;
    if (fineStep === 2) midStep = 10;
    else if (fineStep === 20 || fineStep === 25) midStep = 100;
    else if (fineStep === 200 || fineStep === 250) midStep = 1000;

    let majorStep = midStep * 5;
    if (midStep === 10) majorStep = 50;
    else if (midStep === 100) majorStep = 500;

    const imgScreenX0 = offsetX;
    const imgScreenY0 = offsetY;

    // Viewport visible range in image coordinates (with margin)
    const minImgX = Math.floor((-offsetX) / (fineStep * z)) * fineStep;
    const maxImgX = Math.ceil((width - offsetX) / (fineStep * z)) * fineStep;
    const minImgY = Math.floor((-offsetY) / (fineStep * z)) * fineStep;
    const maxImgY = Math.ceil((height - offsetY) / (fineStep * z)) * fineStep;

    ctx.save();

    // 1. Draw Deep Fine Grid Lines
    ctx.lineWidth = 0.75;
    ctx.strokeStyle = isDark
      ? "rgba(148, 163, 184, 0.18)"
      : "rgba(100, 116, 139, 0.16)";
    ctx.beginPath();
    for (let ix = minImgX; ix <= maxImgX; ix += fineStep) {
      if (ix % midStep === 0) continue;
      const sx = Math.round(offsetX + ix * z) + 0.5;
      if (sx >= -1 && sx <= width + 1) {
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, height);
      }
    }
    for (let iy = minImgY; iy <= maxImgY; iy += fineStep) {
      if (iy % midStep === 0) continue;
      const sy = Math.round(offsetY + iy * z) + 0.5;
      if (sy >= -1 && sy <= height + 1) {
        ctx.moveTo(0, sy);
        ctx.lineTo(width, sy);
      }
    }
    ctx.stroke();

    // 2. Draw Medium Grid Lines
    ctx.lineWidth = 1.0;
    ctx.strokeStyle = isDark
      ? "rgba(148, 163, 184, 0.38)"
      : "rgba(71, 85, 105, 0.35)";
    ctx.beginPath();
    for (let ix = minImgX; ix <= maxImgX; ix += fineStep) {
      if (ix % midStep !== 0 || ix % majorStep === 0) continue;
      const sx = Math.round(offsetX + ix * z) + 0.5;
      if (sx >= -1 && sx <= width + 1) {
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, height);
      }
    }
    for (let iy = minImgY; iy <= maxImgY; iy += fineStep) {
      if (iy % midStep !== 0 || iy % majorStep === 0) continue;
      const sy = Math.round(offsetY + iy * z) + 0.5;
      if (sy >= -1 && sy <= height + 1) {
        ctx.moveTo(0, sy);
        ctx.lineTo(width, sy);
      }
    }
    ctx.stroke();

    // 3. Draw Major Grid Lines
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = isDark
      ? "rgba(186, 230, 253, 0.62)"
      : "rgba(30, 58, 138, 0.58)";
    ctx.beginPath();
    for (let ix = minImgX; ix <= maxImgX; ix += fineStep) {
      if (ix % majorStep !== 0) continue;
      const sx = Math.round(offsetX + ix * z) + 0.5;
      if (sx >= -1 && sx <= width + 1) {
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, height);
      }
    }
    for (let iy = minImgY; iy <= maxImgY; iy += fineStep) {
      if (iy % majorStep !== 0) continue;
      const sy = Math.round(offsetY + iy * z) + 0.5;
      if (sy >= -1 && sy <= height + 1) {
        ctx.moveTo(0, sy);
        ctx.lineTo(width, sy);
      }
    }
    ctx.stroke();

    // 4. Prominent Image Dimension Boundary Frame
    ctx.lineWidth = 1.75;
    ctx.strokeStyle = isDark ? "rgba(56, 189, 248, 0.85)" : "rgba(37, 99, 235, 0.85)";
    ctx.strokeRect(
      Math.round(imgScreenX0) + 0.5,
      Math.round(imgScreenY0) + 0.5,
      Math.round(targetW * z),
      Math.round(targetH * z)
    );

    // 5. Interactive Deep Snapping with Image Coordinate Tag
    if (
      hoverPos &&
      hoverPos.x >= 0 &&
      hoverPos.x < width &&
      hoverPos.y >= 0 &&
      hoverPos.y < height
    ) {
      const curImgX = (hoverPos.x - offsetX) / z;
      const curImgY = (hoverPos.y - offsetY) / z;
      const snapImgX = Math.round(curImgX / fineStep) * fineStep;
      const snapImgY = Math.round(curImgY / fineStep) * fineStep;
      const snapScreenX = Math.round(offsetX + snapImgX * z);
      const snapScreenY = Math.round(offsetY + snapImgY * z);

      const highlightColor = isDark
        ? "rgba(56, 189, 248, 0.9)"
        : "rgba(37, 99, 235, 0.9)";
      ctx.strokeStyle = highlightColor;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(snapScreenX + 0.5, 0);
      ctx.lineTo(snapScreenX + 0.5, height);
      ctx.moveTo(0, snapScreenY + 0.5);
      ctx.lineTo(width, snapScreenY + 0.5);
      ctx.stroke();

      ctx.fillStyle = highlightColor;
      ctx.beginPath();
      ctx.arc(snapScreenX, snapScreenY, 3.5, 0, Math.PI * 2);
      ctx.fill();

      // Precision Coordinate Readout Tag
      const coordText = `(${snapImgX}, ${snapImgY}) [${fineStep}px grid]`;
      ctx.font = "600 10.5px monospace";
      const tw = ctx.measureText(coordText).width;
      const tx = Math.min(width - tw - 12, Math.max(6, snapScreenX + 8));
      const ty = Math.min(height - 18, Math.max(18, snapScreenY - 8));
      ctx.fillStyle = isDark ? "rgba(15, 23, 42, 0.88)" : "rgba(255, 255, 255, 0.92)";
      roundRect(ctx, tx - 4, ty - 12, tw + 8, 16, 3);
      ctx.fill();
      ctx.strokeStyle = highlightColor;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = isDark ? "#38bdf8" : "#1d4ed8";
      ctx.fillText(coordText, tx, ty);
    }

    ctx.restore();
  }

  // Create diagonal crosshatch pattern matching Qt.DiagCrossPattern
  const hatchPatternCache = new Map();
  function getDiagCrossPattern(ctx, r, g, b, alpha = 0.45) {
    const key = `${r},${g},${b},${alpha}`;
    if (hatchPatternCache.has(key)) return hatchPatternCache.get(key);
    const pCanvas = document.createElement("canvas");
    pCanvas.width = 10;
    pCanvas.height = 10;
    const pCtx = pCanvas.getContext("2d");
    pCtx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
    pCtx.lineWidth = 1;
    pCtx.beginPath();
    pCtx.moveTo(0, 0);
    pCtx.lineTo(10, 10);
    pCtx.moveTo(10, 0);
    pCtx.lineTo(0, 10);
    pCtx.stroke();
    const pat = ctx.createPattern(pCanvas, "repeat");
    hatchPatternCache.set(key, pat);
    return pat;
  }

  // ==================== LAYERIFY CANVAS RENDERING ====================
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

  function drawLayerifyCanvas() {
    const w = lyrCanvas.width;
    const h = lyrCanvas.height;
    lyrCtx.clearRect(0, 0, w, h);

    lyrView.labelPillRects = [];

    if (!lyrView.img) {
      lyrCtx.save();
      lyrCtx.fillStyle = appState?.theme_mode === "dark" ? "#9eb0ca" : "#4b5a70";
      lyrCtx.font = "14px 'Segoe UI', sans-serif";
      lyrCtx.textAlign = "center";
      lyrCtx.fillText(
        lyrView.isLoadingImage
          ? "Loading image…"
          : "Select a folder or upload images to begin annotating.",
        w / 2,
        h / 2
      );
      lyrCtx.restore();
      drawGridlines(lyrCtx, w, h, lyrView.offsetX, lyrView.offsetY, lyrView.zoom, lyrView.hoverScreenPos);
      return;
    }

    lyrCtx.save();
    lyrCtx.translate(lyrView.offsetX, lyrView.offsetY);
    lyrCtx.scale(lyrView.zoom, lyrView.zoom);

    // Draw base image
    lyrCtx.drawImage(lyrView.img, 0, 0);

    // Draw annotations in image space
    const handleRadius = 5 / lyrView.zoom;
    lyrView.annotations.forEach((ann, idx) => {
      if (ann.visible === false) return;
      const [r, g, b] = ann.color || [255, 128, 0];
      const isSelected = Boolean(ann.selected);
      const isHovered = lyrView.hoveredIdx === idx;
      const strokeW = (isSelected ? 2.5 : 1.8) / lyrView.zoom;

      lyrCtx.strokeStyle = `rgb(${r}, ${g}, ${b})`;
      lyrCtx.lineWidth = strokeW;

      // 0. Mask overlay if present (Brush / Segmentation model)
      if (ann.mask_png_b64) {
        const mImg = lyrView.maskImgCache.get(ann.mask_png_b64);
        if (mImg && mImg.complete) {
          lyrCtx.save();
          lyrCtx.globalAlpha = isSelected ? 0.5 : 0.34;
          const mx = Number(ann.mask_offset_x || 0);
          const my = Number(ann.mask_offset_y || 0);
          lyrCtx.drawImage(mImg, mx, my);
          lyrCtx.restore();
        }
      }

      // 1. Points
      if (ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        ann.points.forEach((pt) => {
          lyrCtx.beginPath();
          lyrCtx.arc(pt[0], pt[1], (isSelected ? 6.5 : 5) / lyrView.zoom, 0, Math.PI * 2);
          lyrCtx.fillStyle = `rgb(${r}, ${g}, ${b})`;
          lyrCtx.fill();
          lyrCtx.strokeStyle = isSelected ? "#ffff00" : "#ffffff";
          lyrCtx.lineWidth = 1.6 / lyrView.zoom;
          lyrCtx.stroke();
        });
      }

      // 2. Rectangle
      if (ann.rectangle && ann.rectangle.length === 4) {
        const [x1, y1, x2, y2] = ann.rectangle;
        const rx = Math.min(x1, x2);
        const ry = Math.min(y1, y2);
        const rw = Math.abs(x2 - x1);
        const rh = Math.abs(y2 - y1);

        if (isSelected || isHovered) {
          lyrCtx.fillStyle = getDiagCrossPattern(lyrCtx, r, g, b, 0.55);
          lyrCtx.fillRect(rx, ry, rw, rh);
        }
        lyrCtx.strokeStyle = isSelected ? "#facc15" : `rgb(${r}, ${g}, ${b})`;
        lyrCtx.lineWidth = strokeW;
        lyrCtx.strokeRect(rx, ry, rw, rh);

        if (isSelected || isHovered) {
          const handles = getRectHandles(ann.rectangle);
          handles.forEach((hp) => {
            lyrCtx.beginPath();
            lyrCtx.arc(hp.x, hp.y, handleRadius, 0, Math.PI * 2);
            lyrCtx.fillStyle = `rgb(${r}, ${g}, ${b})`;
            lyrCtx.fill();
            lyrCtx.strokeStyle = "#ffffff";
            lyrCtx.lineWidth = 1.2 / lyrView.zoom;
            lyrCtx.stroke();
          });
        }
      }

      // 3. Polygon
      if (ann.polygon && ann.polygon.length >= 3) {
        lyrCtx.beginPath();
        ann.polygon.forEach((pt, i) => {
          if (i === 0) lyrCtx.moveTo(pt[0], pt[1]);
          else lyrCtx.lineTo(pt[0], pt[1]);
        });
        lyrCtx.closePath();

        if (isSelected || isHovered) {
          lyrCtx.fillStyle = getDiagCrossPattern(lyrCtx, r, g, b, 0.55);
          lyrCtx.fill();
        }
        lyrCtx.strokeStyle = isSelected ? "#facc15" : `rgb(${r}, ${g}, ${b})`;
        lyrCtx.lineWidth = strokeW;
        lyrCtx.stroke();

        if (isSelected || isHovered) {
          ann.polygon.forEach((pt) => {
            lyrCtx.beginPath();
            lyrCtx.arc(pt[0], pt[1], handleRadius, 0, Math.PI * 2);
            lyrCtx.fillStyle = `rgb(${r}, ${g}, ${b})`;
            lyrCtx.fill();
            lyrCtx.strokeStyle = "#ffffff";
            lyrCtx.lineWidth = 1.2 / lyrView.zoom;
            lyrCtx.stroke();
          });
        }
      }
    });

    // Draw in-progress rectangle, polygon, or brush stroke
    const curColor = getCurrentSelectedLabelColor();
    const [cr, cg, cb] = curColor;
    if (lyrView.mode === "Rectangle" && lyrView.rectStart && lyrView.rectEnd) {
      const rx = Math.min(lyrView.rectStart.x, lyrView.rectEnd.x);
      const ry = Math.min(lyrView.rectStart.y, lyrView.rectEnd.y);
      const rw = Math.abs(lyrView.rectEnd.x - lyrView.rectStart.x);
      const rh = Math.abs(lyrView.rectEnd.y - lyrView.rectStart.y);
      lyrCtx.fillStyle = getDiagCrossPattern(lyrCtx, cr, cg, cb, 0.45);
      lyrCtx.fillRect(rx, ry, rw, rh);
      lyrCtx.strokeStyle = `rgb(${cr}, ${cg}, ${cb})`;
      lyrCtx.lineWidth = 2 / lyrView.zoom;
      lyrCtx.strokeRect(rx, ry, rw, rh);
    }

    if (lyrView.mode === "Polygon" && lyrView.polyPoints.length > 0) {
      lyrCtx.beginPath();
      lyrView.polyPoints.forEach((pt, i) => {
        if (i === 0) lyrCtx.moveTo(pt.x, pt.y);
        else lyrCtx.lineTo(pt.x, pt.y);
      });
      if (lyrView.hoverPosImg) {
        lyrCtx.lineTo(lyrView.hoverPosImg.x, lyrView.hoverPosImg.y);
      }
      lyrCtx.strokeStyle = `rgb(${cr}, ${cg}, ${cb})`;
      lyrCtx.lineWidth = 2 / lyrView.zoom;
      lyrCtx.stroke();

      const firstPt = lyrView.polyPoints[0];
      const canClose = lyrView.polyPoints.length >= 3;
      const isNearFirst =
        canClose &&
        lyrView.hoverPosImg &&
        Math.hypot(lyrView.hoverPosImg.x - firstPt.x, lyrView.hoverPosImg.y - firstPt.y) <=
          11 / lyrView.zoom;

      lyrView.polyPoints.forEach((pt, idx) => {
        lyrCtx.beginPath();
        const rad = idx === 0 && isNearFirst ? (handleRadius * 1.65) : handleRadius;
        lyrCtx.arc(pt.x, pt.y, rad, 0, Math.PI * 2);
        lyrCtx.fillStyle = idx === 0 && canClose ? "#10b981" : `rgb(${cr}, ${cg}, ${cb})`;
        lyrCtx.fill();
        lyrCtx.strokeStyle = idx === 0 && isNearFirst ? "#ffff00" : "#ffffff";
        lyrCtx.lineWidth = (idx === 0 && isNearFirst ? 2.2 : 1.2) / lyrView.zoom;
        lyrCtx.stroke();
      });
    }

    // Draw active Brush mask preview & cursor circle
    if (lyrView.mode === "Brush") {
      if (lyrView.brushPainting && lyrView.brushCanvas) {
        lyrCtx.save();
        lyrCtx.globalAlpha = 0.55;
        lyrCtx.drawImage(lyrView.brushCanvas, 0, 0);
        lyrCtx.restore();
      }
      if (lyrView.hoverPosImg) {
        lyrCtx.beginPath();
        lyrCtx.arc(
          lyrView.hoverPosImg.x,
          lyrView.hoverPosImg.y,
          lyrView.brushSize / 2,
          0,
          Math.PI * 2
        );
        lyrCtx.strokeStyle = "#ffffff";
        lyrCtx.lineWidth = 1.5 / lyrView.zoom;
        lyrCtx.stroke();
        lyrCtx.beginPath();
        lyrCtx.arc(
          lyrView.hoverPosImg.x,
          lyrView.hoverPosImg.y,
          lyrView.brushSize / 2,
          0,
          Math.PI * 2
        );
        lyrCtx.setLineDash([3 / lyrView.zoom, 3 / lyrView.zoom]);
        lyrCtx.strokeStyle = `rgb(${cr}, ${cg}, ${cb})`;
        lyrCtx.stroke();
        lyrCtx.setLineDash([]);
      }
    }

    // Hover crosshair guide lines in drawing modes
    if (
      lyrView.hoverPosImg &&
      (lyrView.mode === "Point" || lyrView.mode === "Polygon" || lyrView.mode === "Rectangle")
    ) {
      const hx = lyrView.hoverPosImg.x;
      const hy = lyrView.hoverPosImg.y;
      if (hx >= 0 && hy >= 0 && hx <= lyrView.img.width && hy <= lyrView.img.height) {
        lyrCtx.save();
        lyrCtx.setLineDash([4 / lyrView.zoom, 4 / lyrView.zoom]);
        lyrCtx.strokeStyle = "rgba(140, 140, 140, 0.85)";
        lyrCtx.lineWidth = 1 / lyrView.zoom;
        lyrCtx.beginPath();
        lyrCtx.moveTo(hx, 0);
        lyrCtx.lineTo(hx, lyrView.img.height);
        lyrCtx.moveTo(0, hy);
        lyrCtx.lineTo(lyrView.img.width, hy);
        lyrCtx.stroke();
        lyrCtx.restore();
      }
    }

    lyrCtx.restore();

    // Draw Label & Caption Pills in screen space for crisp text
    lyrCtx.save();
    lyrCtx.font = "600 11.5px 'Segoe UI', sans-serif";
    lyrView.annotations.forEach((ann, idx) => {
      if (ann.visible === false) return;
      const anchor = getAnnotationAnchorPoint(ann);
      if (!anchor) return;
      const scr = imageToScreen(anchor.x, anchor.y);
      const [r, g, b] = ann.color || [255, 128, 0];

      const labelText =
        ann.score !== null && ann.score !== undefined
          ? `#${idx + 1} ${ann.label}: ${Number(ann.score).toFixed(2)}`
          : `#${idx + 1} ${ann.label}`;
      const padX = 6;
      const pillH = 20;
      const textW = lyrCtx.measureText(labelText).width;
      const pillW = textW + padX * 2;
      const pillX = scr.x;
      const pillY = scr.y - pillH - 4;

      lyrCtx.fillStyle = ann.selected ? "#facc15" : `rgba(${r}, ${g}, ${b}, 0.88)`;
      roundRect(lyrCtx, pillX, pillY, pillW, pillH, 4);
      lyrCtx.fill();

      // Contrast text color
      const lum = ann.selected ? 220 : 0.299 * r + 0.587 * g + 0.114 * b;
      lyrCtx.fillStyle = lum > 150 ? "#111827" : "#ffffff";
      lyrCtx.fillText(labelText, pillX + padX, pillY + 14);

      lyrView.labelPillRects.push({
        annIdx: idx,
        x: pillX,
        y: pillY,
        w: pillW,
        h: pillH,
      });

      if (ann.caption) {
        const capText = `💬 ${ann.caption}`;
        const capW = lyrCtx.measureText(capText).width + padX * 2;
        const capY = pillY - pillH - 3;
        lyrCtx.fillStyle = "rgba(0, 0, 0, 0.78)";
        roundRect(lyrCtx, pillX, capY, capW, pillH, 4);
        lyrCtx.fill();
        lyrCtx.fillStyle = "#ffffff";
        lyrCtx.fillText(capText, pillX + padX, capY + 14);
      }
    });
    lyrCtx.restore();

    // Draw grid overlay IN FRONT OF the image and annotations
    drawGridlines(
      lyrCtx,
      w,
      h,
      lyrView.offsetX,
      lyrView.offsetY,
      lyrView.zoom,
      lyrView.hoverScreenPos,
      lyrView.img ? lyrView.img.width : null,
      lyrView.img ? lyrView.img.height : null
    );
  }

  function getAnnotationAnchorPoint(ann) {
    if (ann.rectangle && ann.rectangle.length === 4) {
      return {
        x: Math.min(ann.rectangle[0], ann.rectangle[2]),
        y: Math.min(ann.rectangle[1], ann.rectangle[3]),
      };
    }
    if (ann.polygon && ann.polygon.length > 0) {
      return { x: ann.polygon[0][0], y: ann.polygon[0][1] };
    }
    if (ann.points && ann.points.length > 0) {
      return { x: ann.points[0][0], y: ann.points[0][1] };
    }
    return null;
  }

  function getRectHandles(rect) {
    const [x1, y1, x2, y2] = rect;
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    return [
      { x: x1, y: y1 }, // 0: TL
      { x: x2, y: y1 }, // 1: TR
      { x: x2, y: y2 }, // 2: BR
      { x: x1, y: y2 }, // 3: BL
      { x: mx, y: y1 }, // 4: T
      { x: x2, y: my }, // 5: R
      { x: mx, y: y2 }, // 6: B
      { x: x1, y: my }, // 7: L
    ];
  }

  function hitTestAnnotation(ix, iy) {
    const tol = 7 / lyrView.zoom;
    // Check if clicked/hovered over any label pill in screen space first
    const scr = imageToScreen(ix, iy);
    for (let p = lyrView.labelPillRects.length - 1; p >= 0; p--) {
      const pill = lyrView.labelPillRects[p];
      if (
        scr.x >= pill.x - 2 &&
        scr.x <= pill.x + pill.w + 2 &&
        scr.y >= pill.y - 2 &&
        scr.y <= pill.y + pill.h + 2
      ) {
        return pill.annIdx;
      }
    }

    // Check point annotations first
    for (let i = lyrView.annotations.length - 1; i >= 0; i--) {
      const ann = lyrView.annotations[i];
      if (ann.visible === false) continue;
      if (ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        for (const pt of ann.points) {
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol * 1.3) return i;
        }
      }
    }
    // Check smallest containing rectangle/polygon first so nested regions are easy to select
    const hits = [];
    for (let i = lyrView.annotations.length - 1; i >= 0; i--) {
      const ann = lyrView.annotations[i];
      if (ann.visible === false) continue;
      if (ann.polygon && ann.polygon.length >= 3) {
        let onVert = false;
        for (const pt of ann.polygon) {
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol) {
            onVert = true;
            break;
          }
        }
        if (onVert || pointInPolygon(ix, iy, ann.polygon)) {
          const xs = ann.polygon.map((p) => p[0]);
          const ys = ann.polygon.map((p) => p[1]);
          const area = Math.max(1, (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys)));
          hits.push({ idx: i, area });
          continue;
        }
      }
      if (ann.rectangle && ann.rectangle.length === 4) {
        const [x1, y1, x2, y2] = ann.rectangle;
        const rx1 = Math.min(x1, x2);
        const ry1 = Math.min(y1, y2);
        const rx2 = Math.max(x1, x2);
        const ry2 = Math.max(y1, y2);
        if (ix >= rx1 - tol && ix <= rx2 + tol && iy >= ry1 - tol && iy <= ry2 + tol) {
          const area = Math.max(1, (rx2 - rx1) * (ry2 - ry1));
          hits.push({ idx: i, area });
        }
      }
    }
    if (hits.length > 0) {
      hits.sort((a, b) => a.area - b.area);
      return hits[0].idx;
    }
    return null;
  }

  function hitTestAnnotationHandle(ix, iy) {
    const tol = 8.5 / lyrView.zoom;
    // Check selected annotations first, then other visible annotations (matches Windows AnnotableLayer)
    const indices = [];
    for (let i = lyrView.annotations.length - 1; i >= 0; i--) {
      if (lyrView.annotations[i].visible !== false && lyrView.annotations[i].selected) indices.push(i);
    }
    for (let i = lyrView.annotations.length - 1; i >= 0; i--) {
      if (lyrView.annotations[i].visible !== false && !lyrView.annotations[i].selected) indices.push(i);
    }

    for (const i of indices) {
      const ann = lyrView.annotations[i];

      if (ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        for (let p = 0; p < ann.points.length; p++) {
          const pt = ann.points[p];
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol * 1.2) {
            return { annIdx: i, type: "point", handleIdx: p };
          }
        }
      }
      if (ann.rectangle && ann.rectangle.length === 4) {
        const handles = getRectHandles(ann.rectangle);
        for (let h = 0; h < handles.length; h++) {
          if (Math.hypot(ix - handles[h].x, iy - handles[h].y) <= tol) {
            return { annIdx: i, type: "rect", handleIdx: h };
          }
        }
      }
      if (ann.polygon && ann.polygon.length >= 3) {
        for (let v = 0; v < ann.polygon.length; v++) {
          const pt = ann.polygon[v];
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol) {
            return { annIdx: i, type: "poly", handleIdx: v };
          }
        }
      }
    }
    return null;
  }

  // ==================== DISTINCT MODE CURSORS (SVG data-URIs) ====================
  function svgCursor(svgBody, hotX, hotY, fallback) {
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 28 28'>${svgBody}</svg>`;
    return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}") ${hotX} ${hotY}, ${fallback}`;
  }
  const CROSS_BASE =
    "<g stroke='white' stroke-width='3' stroke-linecap='round'><path d='M3 10h5M12 10h5M10 3v5M10 12v5'/></g>" +
    "<g stroke='%23141820' stroke-width='1.5' stroke-linecap='round'><path d='M3 10h5M12 10h5M10 3v5M10 12v5'/></g>";
  const MODE_CURSORS = {
    Idle: "default",
    Point: svgCursor(
      CROSS_BASE.replace(/%23/g, "#") +
        "<circle cx='10' cy='10' r='3' fill='#00d2ff' stroke='white' stroke-width='1.5'/>" +
        "<circle cx='21' cy='21' r='4.5' fill='none' stroke='#00b4e6' stroke-width='1.8'/>",
      10, 10, "crosshair"
    ),
    Rectangle: svgCursor(
      CROSS_BASE.replace(/%23/g, "#") +
        "<rect x='14' y='15' width='11' height='9' fill='rgba(59,130,246,0.3)' stroke='white' stroke-width='2.5'/>" +
        "<rect x='14' y='15' width='11' height='9' fill='none' stroke='#3b82f6' stroke-width='1.5'/>",
      10, 10, "crosshair"
    ),
    Polygon: svgCursor(
      CROSS_BASE.replace(/%23/g, "#") +
        "<polygon points='15,24 14,17 20,14 25,19 23,25' fill='rgba(16,185,129,0.3)' stroke='white' stroke-width='2.5'/>" +
        "<polygon points='15,24 14,17 20,14 25,19 23,25' fill='none' stroke='#10b981' stroke-width='1.5'/>" +
        "<g fill='#10b981'><circle cx='15' cy='24' r='1.6'/><circle cx='14' cy='17' r='1.6'/><circle cx='20' cy='14' r='1.6'/><circle cx='25' cy='19' r='1.6'/><circle cx='23' cy='25' r='1.6'/></g>",
      10, 10, "crosshair"
    ),
    Brush: "none", // brush circle drawn on canvas
    Pan: "grab",
    Draw: svgCursor(
      "<path d='M4 24 L7 17 L19 5 L23 9 L11 21 Z' fill='#ef4444' stroke='white' stroke-width='1.5'/>" +
        "<path d='M4 24 L7 17 L11 21 Z' fill='#141820'/>",
      4, 24, "crosshair"
    ),
    Erase: svgCursor(
      "<rect x='6' y='8' width='16' height='10' rx='2' transform='rotate(-35 14 13)' fill='#f9a8d4' stroke='#141820' stroke-width='1.5'/>" +
        "<line x1='4' y1='25' x2='24' y2='25' stroke='#141820' stroke-width='1.5'/>",
      6, 22, "cell"
    ),
  };

  function updateBakerCursor(hit = null) {
    if (!bkrCanvas || bkrView.isPanning) return;
    if (bkrView.drawingMode) {
      bkrCanvas.style.cursor = MODE_CURSORS.Draw;
    } else if (bkrView.eraseMode) {
      bkrCanvas.style.cursor = MODE_CURSORS.Erase;
    } else if (hit && hit.hitType === "rotate") {
      bkrCanvas.style.cursor = "alias";
    } else if (hit && hit.hitType === "scale") {
      const resizeMap = ["nwse-resize", "ns-resize", "nesw-resize", "ew-resize", "nwse-resize", "ns-resize", "nesw-resize", "ew-resize"];
      bkrCanvas.style.cursor = resizeMap[hit.handleIdx] || "nwse-resize";
    } else if (hit && hit.hitType === "body") {
      bkrCanvas.style.cursor = "move";
    } else {
      bkrCanvas.style.cursor = "default";
    }
  }

  // ==================== LAYERIFY CANVAS EVENTS ====================
  function updateLayerifyHud() {
    const pill = el("hud-mode-pill");
    const hint = el("hud-mode-hint");
    const brushWrap = el("hud-brush-wrap");
    const finishPolyBtn = el("btn-finish-polygon");

    const modeInfo = {
      Idle: {
        label: "Mode: Select / Edit (V)",
        hint: "Click any region to select • Drag inside to move • Drag handles to resize • 0-9 relabels",
        cursor: MODE_CURSORS.Idle,
      },
      Rectangle: {
        label: "Mode: Rectangle (E)",
        hint: "Drag to draw rectangle • Click existing region to select or drag its handles",
        cursor: MODE_CURSORS.Rectangle,
      },
      Polygon: {
        label: "Mode: Polygon (W)",
        hint: "Click to add points • Click 1st point, Enter, or Double-Click to finish • Right-Click removes point",
        cursor: MODE_CURSORS.Polygon,
      },
      Point: {
        label: "Mode: Point (Q)",
        hint: "Click to place key/prompt point • Drag existing point to move",
        cursor: MODE_CURSORS.Point,
      },
      Brush: {
        label: "Mode: Brush Mask (B)",
        hint: "Paint over object to create segmentation mask & polygon • Alt+Wheel adjusts size",
        cursor: MODE_CURSORS.Brush,
      },
      Pan: {
        label: "Mode: Pan (Space)",
        hint: "Drag anywhere on canvas to pan viewport • Scroll wheel to zoom",
        cursor: MODE_CURSORS.Pan,
      },
    };
    const info = modeInfo[lyrView.mode] || modeInfo.Idle;
    if (pill) pill.textContent = info.label;
    if (hint) hint.textContent = info.hint;
    if (brushWrap) brushWrap.classList.toggle("hidden", lyrView.mode !== "Brush");
    if (finishPolyBtn) {
      finishPolyBtn.classList.toggle(
        "hidden",
        !(lyrView.mode === "Polygon" && lyrView.polyPoints.length >= 3)
      );
    }
    lyrCanvas.style.cursor = info.cursor;
  }

  function setLayerifyMode(mode) {
    lyrView.mode = mode;
    lyrView.rectStart = null;
    lyrView.rectEnd = null;
    if (mode !== "Polygon") {
      lyrView.polyPoints = [];
    }
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.mode === mode);
    });
    updateLayerifyHud();
    drawLayerifyCanvas();
  }

  function finishCurrentPolygonDrawing() {
    if (lyrView.polyPoints.length >= 3) {
      const pts = lyrView.polyPoints.map((p) => [p.x, p.y]);
      lyrView.polyPoints = [];
      updateLayerifyHud();
      addNewAnnotation({ polygon: pts });
    } else {
      lyrView.polyPoints = [];
      updateLayerifyHud();
      drawLayerifyCanvas();
    }
  }

  function startLayerifyBrushStroke(pt) {
    if (!lyrView.img) return;
    const off = document.createElement("canvas");
    off.width = lyrView.img.width;
    off.height = lyrView.img.height;
    const ctx = off.getContext("2d");
    const [r, g, b] = getCurrentSelectedLabelColor();
    const colorStr = `rgb(${r}, ${g}, ${b})`;
    ctx.fillStyle = colorStr;
    ctx.strokeStyle = colorStr;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = lyrView.brushSize;
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, lyrView.brushSize / 2, 0, Math.PI * 2);
    ctx.fill();
    lyrView.brushCanvas = off;
    lyrView.brushCtx = ctx;
    lyrView.brushPainting = true;
    lyrView.lastBrushPt = { ...pt };
  }

  function continueLayerifyBrushStroke(pt) {
    if (!lyrView.brushPainting || !lyrView.brushCtx) return;
    const ctx = lyrView.brushCtx;
    ctx.beginPath();
    ctx.moveTo(lyrView.lastBrushPt.x, lyrView.lastBrushPt.y);
    ctx.lineTo(pt.x, pt.y);
    ctx.stroke();
    lyrView.lastBrushPt = { ...pt };
  }

  function finishLayerifyBrushStroke() {
    if (!lyrView.brushPainting || !lyrView.brushCanvas) return;
    lyrView.brushPainting = false;
    const dataUrl = lyrView.brushCanvas.toDataURL("image/png");
    const b64 = dataUrl.split(",")[1];
    lyrView.brushCanvas = null;
    lyrView.brushCtx = null;
    lyrView.lastBrushPt = null;
    addNewAnnotation({ mask_png_b64: b64 });
  }

  lyrCanvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    if (lyrView.mode === "Polygon" && lyrView.polyPoints.length > 0) {
      lyrView.polyPoints.pop();
      updateLayerifyHud();
      drawLayerifyCanvas();
    } else {
      // Matches Windows AnnotableLayer right-click: switch to Idle & deselect
      let hadSel = false;
      lyrView.annotations.forEach((a) => {
        if (a.selected) hadSel = true;
        a.selected = false;
      });
      setLayerifyMode("Idle");
      renderAnnotationList(lyrView.annotations);
      drawLayerifyCanvas();
      if (hadSel) {
        syncAnnotationsToServer(false, "Idle mode (deselected)");
      }
    }
  });

  lyrCanvas.addEventListener("mousedown", (e) => {
    lyrCanvas.focus();
    const rect = lyrCanvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    lyrView.selectionChangedOnMouseDown = false;

    // Middle mouse or Pan mode or Ctrl+LeftClick in drawing mode -> Pan
    if (
      e.button === 1 ||
      lyrView.mode === "Pan" ||
      (e.button === 0 && (e.ctrlKey || e.metaKey) && lyrView.mode !== "Idle")
    ) {
      lyrView.isPanning = true;
      lyrView.panStart = { x: sx - lyrView.offsetX, y: sy - lyrView.offsetY };
      lyrCanvas.style.cursor = "grabbing";
      return;
    }

    if (e.button !== 0 || !lyrView.img) return;
    const imgPt = screenToImage(sx, sy);
    const clampedPt = {
      x: Math.max(0, Math.min(lyrView.img.width, Math.round(imgPt.x))),
      y: Math.max(0, Math.min(lyrView.img.height, Math.round(imgPt.y))),
    };

    // 1. If in Polygon mode and vertices are already placed, handle closing or adding vertex
    if (lyrView.mode === "Polygon" && lyrView.polyPoints.length > 0) {
      const firstPt = lyrView.polyPoints[0];
      const lastPt = lyrView.polyPoints[lyrView.polyPoints.length - 1];
      if (
        lyrView.polyPoints.length >= 3 &&
        Math.hypot(clampedPt.x - firstPt.x, clampedPt.y - firstPt.y) <= 11 / lyrView.zoom
      ) {
        finishCurrentPolygonDrawing();
        return;
      }
      // Avoid duplicate point on double-click
      if (Math.hypot(clampedPt.x - lastPt.x, clampedPt.y - lastPt.y) >= 3 / lyrView.zoom) {
        lyrView.polyPoints.push(clampedPt);
        updateLayerifyHud();
        drawLayerifyCanvas();
      }
      return;
    }

    // 2. If in Brush mode, start brush stroke
    if (lyrView.mode === "Brush") {
      startLayerifyBrushStroke(clampedPt);
      drawLayerifyCanvas();
      return;
    }

    // 3. Check if clicked directly on any label pill to select and drag it
    for (let p = lyrView.labelPillRects.length - 1; p >= 0; p--) {
      const pill = lyrView.labelPillRects[p];
      if (
        sx >= pill.x - 2 &&
        sx <= pill.x + pill.w + 2 &&
        sy >= pill.y - 2 &&
        sy <= pill.y + pill.h + 2
      ) {
        const ann = lyrView.annotations[pill.annIdx];
        if (ann) {
          const multi = e.ctrlKey || e.metaKey || e.shiftKey;
          lyrView.annotations.forEach((a, i) => {
            if (i === pill.annIdx) a.selected = multi ? !a.selected : true;
            else if (!multi) a.selected = false;
          });
          lyrView.draggingAnnIdx = pill.annIdx;
          lyrView.dragStartImg = imgPt;
          lyrView.dirtyDuringDrag = false;
          lyrView.selectionChangedOnMouseDown = true;
          renderAnnotationList(lyrView.annotations);
          drawLayerifyCanvas();
          return;
        }
      }
    }

    // 4. Check if clicking any annotation handle (works in ALL modes, matching Windows AnnotableLayer!)
    const handleHit = hitTestAnnotationHandle(imgPt.x, imgPt.y);
    if (handleHit) {
      lyrView.annotations.forEach((a, i) => {
        a.selected = i === handleHit.annIdx;
      });
      lyrView.draggingHandle = handleHit;
      lyrView.dirtyDuringDrag = false;
      lyrView.selectionChangedOnMouseDown = true;
      renderAnnotationList(lyrView.annotations);
      drawLayerifyCanvas();
      return;
    }

    // 4. Mode-specific drawing vs selecting existing annotations
    if (lyrView.mode === "Point") {
      addNewAnnotation({ points: [[clampedPt.x, clampedPt.y]] });
      return;
    }

    if (lyrView.mode === "Polygon") {
      lyrView.polyPoints.push(clampedPt);
      updateLayerifyHud();
      drawLayerifyCanvas();
      return;
    }

    if (lyrView.mode === "Rectangle") {
      // If clicking inside an ALREADY selected annotation, allow dragging it directly
      const hitIdx = hitTestAnnotation(imgPt.x, imgPt.y);
      if (hitIdx !== null && lyrView.annotations[hitIdx].selected) {
        lyrView.draggingAnnIdx = hitIdx;
        lyrView.dragStartImg = imgPt;
        lyrView.dirtyDuringDrag = false;
        return;
      }
      // Otherwise start rectangle drag; if released without dragging (< 3px), mouseup selects annotation under cursor!
      lyrView.rectStart = clampedPt;
      lyrView.rectEnd = clampedPt;
      drawLayerifyCanvas();
      return;
    }

    // 5. Idle / Select mode: select annotation body or pan/deselect
    const hitIdx = hitTestAnnotation(imgPt.x, imgPt.y);
    if (hitIdx !== null) {
      const multi = e.ctrlKey || e.metaKey || e.shiftKey;
      lyrView.annotations.forEach((a, i) => {
        if (i === hitIdx) {
          a.selected = multi ? !a.selected : true;
        } else if (!multi) {
          a.selected = false;
        }
      });
      lyrView.draggingAnnIdx = hitIdx;
      lyrView.dragStartImg = imgPt;
      lyrView.dirtyDuringDrag = false;
      lyrView.selectionChangedOnMouseDown = true;
      renderAnnotationList(lyrView.annotations);
      drawLayerifyCanvas();
    } else if (e.ctrlKey || e.metaKey) {
      lyrView.isPanning = true;
      lyrView.panStart = { x: sx - lyrView.offsetX, y: sy - lyrView.offsetY };
      lyrCanvas.style.cursor = "grabbing";
    } else {
      const hadSelected = lyrView.annotations.some((a) => a.selected);
      lyrView.annotations.forEach((a) => (a.selected = false));
      if (hadSelected) {
        lyrView.selectionChangedOnMouseDown = true;
      }
      renderAnnotationList(lyrView.annotations);
      drawLayerifyCanvas();
    }
  });

  lyrCanvas.addEventListener("mousemove", (e) => {
    const rect = lyrCanvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    lyrView.hoverScreenPos = { x: sx, y: sy };

    if (lyrView.isPanning) {
      lyrView.offsetX = sx - lyrView.panStart.x;
      lyrView.offsetY = sy - lyrView.panStart.y;
      drawLayerifyCanvas();
      return;
    }

    if (!lyrView.img) return;
    const imgPt = screenToImage(sx, sy);
    lyrView.hoverPosImg = {
      x: Math.max(0, Math.min(lyrView.img.width, Math.round(imgPt.x))),
      y: Math.max(0, Math.min(lyrView.img.height, Math.round(imgPt.y))),
    };
    if (el("layerify-coords-pill")) {
      el("layerify-coords-pill").textContent = `X: ${lyrView.hoverPosImg.x}, Y: ${lyrView.hoverPosImg.y}`;
    }

    if (lyrView.mode === "Brush" && lyrView.brushPainting) {
      continueLayerifyBrushStroke(lyrView.hoverPosImg);
      drawLayerifyCanvas();
      return;
    }

    if (lyrView.mode === "Rectangle" && lyrView.rectStart) {
      lyrView.rectEnd = lyrView.hoverPosImg;
      drawLayerifyCanvas();
      return;
    }

    if (lyrView.draggingHandle) {
      const { annIdx, type, handleIdx } = lyrView.draggingHandle;
      const ann = lyrView.annotations[annIdx];
      if (ann) {
        const cx = lyrView.hoverPosImg.x;
        const cy = lyrView.hoverPosImg.y;
        if (type === "point" && ann.points && ann.points[handleIdx]) {
          ann.points[handleIdx] = [cx, cy];
          lyrView.dirtyDuringDrag = true;
        } else if (type === "rect" && ann.rectangle) {
          let [x1, y1, x2, y2] = ann.rectangle;
          if (handleIdx === 0) { x1 = cx; y1 = cy; }
          else if (handleIdx === 1) { x2 = cx; y1 = cy; }
          else if (handleIdx === 2) { x2 = cx; y2 = cy; }
          else if (handleIdx === 3) { x1 = cx; y2 = cy; }
          else if (handleIdx === 4) { y1 = cy; }
          else if (handleIdx === 5) { x2 = cx; }
          else if (handleIdx === 6) { y2 = cy; }
          else if (handleIdx === 7) { x1 = cx; }
          ann.rectangle = [x1, y1, x2, y2];
          lyrView.dirtyDuringDrag = true;
        } else if (type === "poly" && ann.polygon) {
          ann.polygon[handleIdx] = [cx, cy];
          lyrView.dirtyDuringDrag = true;
        }
        drawLayerifyCanvas();
      }
      return;
    }

    if (lyrView.draggingAnnIdx !== null && lyrView.dragStartImg) {
      const dx = Math.round(imgPt.x - lyrView.dragStartImg.x);
      const dy = Math.round(imgPt.y - lyrView.dragStartImg.y);
      if (dx !== 0 || dy !== 0) {
        const ann = lyrView.annotations[lyrView.draggingAnnIdx];
        if (ann) {
          moveAnnotationByDelta(ann, dx, dy, lyrView.img.width, lyrView.img.height);
          lyrView.dragStartImg = imgPt;
          lyrView.dirtyDuringDrag = true;
          drawLayerifyCanvas();
        }
      }
      return;
    }

    const hitIdx = hitTestAnnotation(imgPt.x, imgPt.y);
    if (lyrView.hoveredIdx !== hitIdx) {
      lyrView.hoveredIdx = hitIdx;
    }
    const handleHover = hitTestAnnotationHandle(imgPt.x, imgPt.y);
    if (handleHover) {
      lyrCanvas.style.cursor = "pointer";
    } else if (lyrView.mode === "Idle" && hitIdx !== null) {
      lyrCanvas.style.cursor = "move";
    } else {
      updateLayerifyHud();
    }
    drawLayerifyCanvas();
  });

  window.addEventListener("mouseup", () => {
    if (lyrView.isPanning) {
      lyrView.isPanning = false;
      updateLayerifyHud();
    }
    if (lyrView.mode === "Brush" && lyrView.brushPainting) {
      finishLayerifyBrushStroke();
      return;
    }
    if (lyrView.mode === "Rectangle" && lyrView.rectStart && lyrView.rectEnd) {
      const x1 = Math.min(lyrView.rectStart.x, lyrView.rectEnd.x);
      const y1 = Math.min(lyrView.rectStart.y, lyrView.rectEnd.y);
      const x2 = Math.max(lyrView.rectStart.x, lyrView.rectEnd.x);
      const y2 = Math.max(lyrView.rectStart.y, lyrView.rectEnd.y);
      const clickPt = { ...lyrView.rectStart };
      lyrView.rectStart = null;
      lyrView.rectEnd = null;
      if (x2 - x1 >= 3 && y2 - y1 >= 3) {
        addNewAnnotation({ rectangle: [x1, y1, x2, y2] });
      } else {
        // Click without drag (< 3px) in Rectangle mode: select/deselect region under cursor!
        const hitIdx = hitTestAnnotation(clickPt.x, clickPt.y);
        const changed = lyrView.annotations.some(
          (a, i) => Boolean(a.selected) !== (i === hitIdx)
        );
        lyrView.annotations.forEach((a, i) => {
          a.selected = i === hitIdx;
        });
        renderAnnotationList(lyrView.annotations);
        drawLayerifyCanvas();
        if (changed) {
          syncAnnotationsToServer(
            false,
            hitIdx !== null ? "Selected annotation" : "Deselected annotations"
          );
        }
      }
      return;
    }
    if (lyrView.draggingHandle || lyrView.draggingAnnIdx !== null) {
      const shouldSyncGeom = lyrView.dirtyDuringDrag;
      const shouldSyncSel = lyrView.selectionChangedOnMouseDown;
      lyrView.draggingHandle = null;
      lyrView.draggingAnnIdx = null;
      lyrView.dragStartImg = null;
      lyrView.dirtyDuringDrag = false;
      lyrView.selectionChangedOnMouseDown = false;
      if (shouldSyncGeom) {
        syncAnnotationsToServer(true, "Updated annotation geometry");
      } else if (shouldSyncSel) {
        syncAnnotationsToServer(false, "Selected annotation");
      }
      return;
    }
    if (lyrView.selectionChangedOnMouseDown) {
      lyrView.selectionChangedOnMouseDown = false;
      syncAnnotationsToServer(false, "Updated selection");
    }
  });

  lyrCanvas.addEventListener("dblclick", (e) => {
    const rect = lyrCanvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    // Finish polygon in Polygon mode
    if (lyrView.mode === "Polygon") {
      if (lyrView.polyPoints.length >= 3) {
        finishCurrentPolygonDrawing();
      }
      return;
    }

    // Check if double-clicked on a label pill to change label/caption via modal
    for (const pill of lyrView.labelPillRects) {
      if (sx >= pill.x && sx <= pill.x + pill.w && sy >= pill.y && sy <= pill.y + pill.h) {
        openEditCaptionModal({ type: "layerify", annIdx: pill.annIdx });
        return;
      }
    }

    // Double-click polygon vertex to remove, or polygon edge to insert vertex
    const imgPt = screenToImage(sx, sy);
    const tol = 8 / lyrView.zoom;
    for (let i = lyrView.annotations.length - 1; i >= 0; i--) {
      const ann = lyrView.annotations[i];
      if (!ann.polygon || ann.polygon.length < 3) continue;

      // Vertex removal
      for (let v = 0; v < ann.polygon.length; v++) {
        if (Math.hypot(imgPt.x - ann.polygon[v][0], imgPt.y - ann.polygon[v][1]) <= tol) {
          if (ann.polygon.length > 3) {
            ann.polygon.splice(v, 1);
            syncAnnotationsToServer(true, "Removed polygon vertex");
          }
          return;
        }
      }

      // Edge insertion
      for (let v = 0; v < ann.polygon.length; v++) {
        const p1 = ann.polygon[v];
        const p2 = ann.polygon[(v + 1) % ann.polygon.length];
        if (distToSegment(imgPt.x, imgPt.y, p1[0], p1[1], p2[0], p2[1]) <= tol) {
          ann.polygon.splice(v + 1, 0, [Math.round(imgPt.x), Math.round(imgPt.y)]);
          syncAnnotationsToServer(true, "Inserted polygon vertex");
          return;
        }
      }
    }
  });

  lyrCanvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      if (lyrView.mode === "Brush" && e.altKey) {
        const delta = e.deltaY < 0 ? 2 : -2;
        lyrView.brushSize = Math.max(3, Math.min(80, lyrView.brushSize + delta));
        if (el("input-lyr-brush-size")) el("input-lyr-brush-size").value = String(lyrView.brushSize);
        if (el("val-lyr-brush-size")) el("val-lyr-brush-size").textContent = `${lyrView.brushSize}px`;
        drawLayerifyCanvas();
        return;
      }
      const rect = lyrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const newZoom = Math.max(0.1, Math.min(10.0, lyrView.zoom * factor));
      lyrView.offsetX = sx - ((sx - lyrView.offsetX) / lyrView.zoom) * newZoom;
      lyrView.offsetY = sy - ((sy - lyrView.offsetY) / lyrView.zoom) * newZoom;
      lyrView.zoom = newZoom;
      drawLayerifyCanvas();
      updateZoomReadout();
    },
    { passive: false }
  );

  function addNewAnnotation(geom) {
    const lyr = appState?.layerify || {};
    const label = lyr.selected_label || "Undefined";
    const color = getCurrentSelectedLabelColor();
    // Select the newly created annotation so pressing 0-9, C, or L immediately acts on it!
    lyrView.annotations.forEach((a) => {
      a.selected = false;
    });
    const newAnn = {
      annotation_id: lyrView.annotations.length + 1,
      label,
      score: null,
      annotator: "manual",
      visible: true,
      selected: true,
      color,
      caption: "",
      points: geom.points || [],
      polygon: geom.polygon || [],
      rectangle: geom.rectangle || null,
      mask_png_b64: geom.mask_png_b64 || null,
    };
    lyrView.annotations.push(newAnn);
    syncAnnotationsToServer(true, `Added ${label} annotation`);
  }

  async function syncAnnotationsToServer(pushUndo = true, message = "") {
    try {
      const res = await apiPost("/api/layerify/annotations/update", {
        annotations: lyrView.annotations,
        push_undo: pushUndo,
        message,
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Layerify", err.message);
    }
  }

  async function layerifyAnnotations(annotationIds = null) {
    try {
      const res = await apiPost("/api/layerify/layerify", {
        annotation_ids: annotationIds,
      });
      applyServerState(res.state);
      showToast(appState?.active_tab || "Layerify", `Created ${res.created || 0} layer(s)`);
    } catch (err) {
      showToast("Layerify", err.message);
    }
  }

  // ==================== BAKER CANVAS RENDERING & INTERACTION ====================
  function screenToBakerScene(sx, sy) {
    return {
      x: (sx - bkrView.offsetX) / bkrView.zoom,
      y: (sy - bkrView.offsetY) / bkrView.zoom,
    };
  }

  function getLayerImageElement(lyr) {
    const canvasId = appState?.baker?.current_canvas_id || 1;
    const step = appState?.baker?.current_state_step;
    const stepParam = step !== null && step !== undefined ? `&step=${step}` : "";
    const rev = lyr.image_revision || 0;
    const url = `/api/baker/layer-image?canvas_id=${canvasId}&layer_id=${lyr.layer_id}${stepParam}&rev=${rev}`;
    if (bkrView.layerImgCache.has(url)) {
      return bkrView.layerImgCache.get(url);
    }
    const img = new Image();
    img.onload = () => {
      drawBakerCanvas();
    };
    img.src = url;
    bkrView.layerImgCache.set(url, img);
    return img;
  }

  function drawBakerCanvas() {
    const w = bkrCanvas.width;
    const h = bkrCanvas.height;
    bkrCtx.clearRect(0, 0, w, h);

    if (!bkrView.layers || bkrView.layers.length === 0) {
      bkrCtx.save();
      bkrCtx.fillStyle = appState?.theme_mode === "dark" ? "#9eb0ca" : "#4b5a70";
      bkrCtx.font = "14px 'Segoe UI', sans-serif";
      bkrCtx.textAlign = "center";
      bkrCtx.fillText(
        "Layerify annotations or click 'Add Blank Layer' to compose on this canvas.",
        w / 2,
        h / 2
      );
      bkrCtx.restore();
      drawGridlines(bkrCtx, w, h, bkrView.offsetX, bkrView.offsetY, bkrView.zoom, bkrView.hoverCanvasPos);
      return;
    }

    bkrCtx.save();
    bkrCtx.translate(bkrView.offsetX, bkrView.offsetY);
    bkrCtx.scale(bkrView.zoom, bkrView.zoom);

    // Draw layers in order
    const sortedLayers = [...bkrView.layers].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

    sortedLayers.forEach((lyr) => {
      if (lyr.visible === false) return;
      const img = getLayerImageElement(lyr);
      const lw = lyr.width || (img && img.complete ? img.width : 100);
      const lh = lyr.height || (img && img.complete ? img.height : 100);
      const posX = lyr.position?.[0] ?? 0;
      const posY = lyr.position?.[1] ?? 0;
      const sx = lyr.scale_x ?? 1.0;
      const sy = lyr.scale_y ?? 1.0;
      const rotRad = ((lyr.rotation ?? 0) * Math.PI) / 180;
      const alpha = Math.max(0, Math.min(1, (lyr.opacity ?? 255) / 255));

      bkrCtx.save();
      bkrCtx.globalAlpha = alpha;
      // Match CanvasLayer.paint: translate(position), translate(cx, cy), rotate(rotation), translate(-cx, -cy), scale(sx, sy)
      const cx = (lw * sx) / 2;
      const cy = (lh * sy) / 2;
      bkrCtx.translate(posX, posY);
      bkrCtx.translate(cx, cy);
      bkrCtx.rotate(rotRad);
      bkrCtx.translate(-cx, -cy);
      bkrCtx.scale(sx, sy);

      if (img && img.complete && img.naturalWidth > 0) {
        bkrCtx.drawImage(img, 0, 0);
      }

      // Draw drawing_states strokes on layer
      if (lyr.drawing_states && lyr.drawing_states.length > 0) {
        lyr.drawing_states.forEach((st) => {
          const pts = st.points || [];
          const [sr, sg, sb, sa] = st.color || [255, 0, 0, 255];
          const sz = st.size || 5;
          bkrCtx.fillStyle = `rgba(${sr}, ${sg}, ${sb}, ${(sa ?? 255) / 255})`;
          pts.forEach((p) => {
            bkrCtx.beginPath();
            bkrCtx.arc(p[0], p[1], sz / 2, 0, Math.PI * 2);
            bkrCtx.fill();
          });
        });
      }

      // Selection bounding box, 8 scale handles, and center rotation handle
      if (lyr.selected) {
        bkrCtx.globalAlpha = 1.0;
        bkrCtx.save();
        bkrCtx.setLineDash([5 / (bkrView.zoom * sx), 4 / (bkrView.zoom * sx)]);
        bkrCtx.strokeStyle = "#ffffff";
        bkrCtx.lineWidth = 1.5 / (bkrView.zoom * Math.max(0.2, sx));
        bkrCtx.strokeRect(0, 0, lw, lh);
        bkrCtx.restore();

        const hSize = 8 / (bkrView.zoom * Math.max(0.2, sx));
        const handles = getBakerLayerLocalHandles(lw, lh);
        bkrCtx.fillStyle = "#0066ff";
        handles.forEach((hp) => {
          bkrCtx.fillRect(hp.x - hSize / 2, hp.y - hSize / 2, hSize, hSize);
        });

        // Center rotation handle (green circle matching CanvasLayer)
        bkrCtx.beginPath();
        bkrCtx.arc(lw / 2, lh / 2, hSize * 0.75, 0, Math.PI * 2);
        bkrCtx.fillStyle = "#16a34a";
        bkrCtx.fill();
        bkrCtx.strokeStyle = "#ffffff";
        bkrCtx.lineWidth = 1 / (bkrView.zoom * Math.max(0.2, sx));
        bkrCtx.stroke();
      }

      bkrCtx.restore();
    });

    bkrCtx.restore();

    // Draw brush cursor circle if in Draw or Erase mode
    if ((bkrView.drawingMode || bkrView.eraseMode) && bkrView.hoverCanvasPos) {
      bkrCtx.save();
      const radius =
        (bkrView.eraseMode ? bkrView.brushSize * 2 : bkrView.brushSize / 2) * bkrView.zoom;
      bkrCtx.beginPath();
      bkrCtx.arc(
        bkrView.hoverCanvasPos.x,
        bkrView.hoverCanvasPos.y,
        Math.max(3, radius),
        0,
        Math.PI * 2
      );
      bkrCtx.strokeStyle = bkrView.eraseMode ? "#ffffff" : "rgba(255, 80, 80, 0.9)";
      bkrCtx.lineWidth = 1.5;
      bkrCtx.stroke();
      bkrCtx.restore();
    }

    // Draw grid overlay IN FRONT OF all Baker layers
    const curC = (appState?.baker?.canvases || [])[bkrView.canvasIdx] || null;
    drawGridlines(
      bkrCtx,
      w,
      h,
      bkrView.offsetX,
      bkrView.offsetY,
      bkrView.zoom,
      bkrView.hoverCanvasPos,
      curC ? curC.width : (bkrView.canvas_width || 1280),
      curC ? curC.height : (bkrView.canvas_height || 720)
    );
  }

  function getBakerLayerLocalHandles(lw, lh) {
    return [
      { x: 0, y: 0 }, // 0: TL
      { x: lw / 2, y: 0 }, // 1: T
      { x: lw, y: 0 }, // 2: TR
      { x: lw, y: lh / 2 }, // 3: R
      { x: lw, y: lh }, // 4: BR
      { x: lw / 2, y: lh }, // 5: B
      { x: 0, y: lh }, // 6: BL
      { x: 0, y: lh / 2 }, // 7: L
    ];
  }

  function sceneToLayerLocal(scenePt, lyr) {
    const lw = lyr.width || 100;
    const lh = lyr.height || 100;
    const posX = lyr.position?.[0] ?? 0;
    const posY = lyr.position?.[1] ?? 0;
    const sx = lyr.scale_x ?? 1.0;
    const sy = lyr.scale_y ?? 1.0;
    const rotRad = -((lyr.rotation ?? 0) * Math.PI) / 180;

    // Inverse of: translate(pos), translate(cx, cy), rotate(rot), translate(-cx, -cy), scale(sx, sy)
    const cx = (lw * sx) / 2;
    const cy = (lh * sy) / 2;
    const dx = scenePt.x - posX - cx;
    const dy = scenePt.y - posY - cy;
    const rx = dx * Math.cos(rotRad) - dy * Math.sin(rotRad) + cx;
    const ry = dx * Math.sin(rotRad) + dy * Math.cos(rotRad) + cy;
    return {
      x: rx / Math.max(0.01, sx),
      y: ry / Math.max(0.01, sy),
    };
  }

  function hitTestBakerLayer(scenePt) {
    // Check from top-most to bottom-most
    for (let i = bkrView.layers.length - 1; i >= 0; i--) {
      const lyr = bkrView.layers[i];
      if (lyr.visible === false) continue;
      const local = sceneToLayerLocal(scenePt, lyr);
      const lw = lyr.width || 100;
      const lh = lyr.height || 100;
      const tol = 10 / Math.max(0.2, bkrView.zoom * (lyr.scale_x ?? 1));

      if (lyr.selected) {
        // Center rotation handle
        if (Math.hypot(local.x - lw / 2, local.y - lh / 2) <= tol * 1.2) {
          return { layerIdx: i, hitType: "rotate", handleIdx: -1 };
        }
        // Scale handles
        const handles = getBakerLayerLocalHandles(lw, lh);
        for (let h = 0; h < handles.length; h++) {
          if (Math.hypot(local.x - handles[h].x, local.y - handles[h].y) <= tol) {
            return { layerIdx: i, hitType: "scale", handleIdx: h };
          }
        }
      }

      if (local.x >= 0 && local.x <= lw && local.y >= 0 && local.y <= lh) {
        return { layerIdx: i, hitType: "body", handleIdx: -1 };
      }
    }
    return null;
  }

  bkrCanvas.addEventListener("mousedown", (e) => {
    bkrCanvas.focus();
    const rect = bkrCanvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (e.button !== 0) return;

    const scenePt = screenToBakerScene(sx, sy);

    // Draw / Erase mode on selected layer
    if (bkrView.drawingMode || bkrView.eraseMode) {
      const selLayer = bkrView.layers.find((l) => l.selected);
      if (!selLayer) {
        showToast("Baker", "Select a layer first to draw or erase.");
        return;
      }
      const localPt = sceneToLayerLocal(scenePt, selLayer);
      bkrView.action = bkrView.drawingMode ? "draw" : "erase";
      bkrView.dirtyDuringDrag = true;
      if (bkrView.drawingMode) {
        bkrView.currentStroke = [[Math.round(localPt.x), Math.round(localPt.y)]];
        if (!selLayer.drawing_states) selLayer.drawing_states = [];
        selLayer.drawing_states.push({
          points: bkrView.currentStroke,
          color: [...bkrView.brushColor],
          size: bkrView.brushSize,
        });
      } else {
        erasePointsOnLayer(selLayer, localPt.x, localPt.y);
      }
      drawBakerCanvas();
      return;
    }

    const hit = hitTestBakerLayer(scenePt);
    if (hit) {
      const multi = e.ctrlKey || e.metaKey;
      const targetLayer = bkrView.layers[hit.layerIdx];
      if (!targetLayer.selected) {
        bkrView.layers.forEach((l, idx) => {
          if (idx === hit.layerIdx) l.selected = true;
          else if (!multi) l.selected = false;
        });
      } else if (multi && hit.hitType === "body") {
        targetLayer.selected = !targetLayer.selected;
      }

      bkrView.action = hit.hitType === "body" ? "move" : hit.hitType;
      bkrView.activeHandleIdx = hit.handleIdx;
      bkrView.dragStartScene = scenePt;
      bkrView.dirtyDuringDrag = false;
      renderLayerLists(bkrView.layers);
      renderLayerSettings(bkrView.layers);
      drawBakerCanvas();
    } else if (e.ctrlKey || e.metaKey) {
      bkrView.isPanning = true;
      bkrView.panStart = { x: sx - bkrView.offsetX, y: sy - bkrView.offsetY };
      bkrCanvas.style.cursor = "grabbing";
    } else {
      bkrView.layers.forEach((l) => (l.selected = false));
      renderLayerLists(bkrView.layers);
      renderLayerSettings(bkrView.layers);
      drawBakerCanvas();
    }
  });

  bkrCanvas.addEventListener("mousemove", (e) => {
    const rect = bkrCanvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    bkrView.hoverCanvasPos = { x: sx, y: sy };

    if (bkrView.isPanning) {
      bkrView.offsetX = sx - bkrView.panStart.x;
      bkrView.offsetY = sy - bkrView.panStart.y;
      drawBakerCanvas();
      return;
    }

    const scenePt = screenToBakerScene(sx, sy);
    if (el("baker-coords-pill")) {
      el("baker-coords-pill").textContent = `X: ${Math.round(scenePt.x)}, Y: ${Math.round(scenePt.y)}`;
    }

    if (bkrView.action === "draw" || bkrView.action === "erase") {
      const selLayer = bkrView.layers.find((l) => l.selected);
      if (selLayer) {
        const localPt = sceneToLayerLocal(scenePt, selLayer);
        if (bkrView.action === "draw" && bkrView.currentStroke) {
          bkrView.currentStroke.push([Math.round(localPt.x), Math.round(localPt.y)]);
        } else if (bkrView.action === "erase") {
          erasePointsOnLayer(selLayer, localPt.x, localPt.y);
        }
        drawBakerCanvas();
      }
      return;
    }

    if (bkrView.action && bkrView.dragStartScene) {
      const dx = scenePt.x - bkrView.dragStartScene.x;
      const dy = scenePt.y - bkrView.dragStartScene.y;
      const selectedLayers = bkrView.layers.filter((l) => l.selected);

      if (bkrView.action === "move") {
        selectedLayers.forEach((l) => {
          l.position = [
            Math.round((l.position?.[0] ?? 0) + dx),
            Math.round((l.position?.[1] ?? 0) + dy),
          ];
        });
        bkrView.dragStartScene = scenePt;
        bkrView.dirtyDuringDrag = true;
        renderLayerSettings(bkrView.layers);
        drawBakerCanvas();
      } else if (bkrView.action === "rotate" && selectedLayers.length > 0) {
        const lyr = selectedLayers[0];
        const cx = (lyr.position?.[0] ?? 0) + ((lyr.width || 100) * (lyr.scale_x ?? 1)) / 2;
        const cy = (lyr.position?.[1] ?? 0) + ((lyr.height || 100) * (lyr.scale_y ?? 1)) / 2;
        const a1 = Math.atan2(bkrView.dragStartScene.y - cy, bkrView.dragStartScene.x - cx);
        const a2 = Math.atan2(scenePt.y - cy, scenePt.x - cx);
        const degDelta = ((a2 - a1) * 180) / Math.PI;
        lyr.rotation = Math.max(-180, Math.min(180, Math.round((lyr.rotation ?? 0) + degDelta)));
        bkrView.dragStartScene = scenePt;
        bkrView.dirtyDuringDrag = true;
        renderLayerSettings(bkrView.layers);
        drawBakerCanvas();
      } else if (bkrView.action === "scale" && selectedLayers.length > 0) {
        const lyr = selectedLayers[0];
        const lw = Math.max(10, lyr.width || 100);
        const lh = Math.max(10, lyr.height || 100);
        const hIdx = bkrView.activeHandleIdx;
        if ([0, 2, 3, 4, 6, 7].includes(hIdx)) {
          const signX = [0, 6, 7].includes(hIdx) ? -1 : 1;
          lyr.scale_x = Math.max(0.1, Math.min(5.0, (lyr.scale_x ?? 1) + (signX * dx) / lw));
        }
        if ([0, 1, 2, 4, 5, 6].includes(hIdx)) {
          const signY = [0, 1, 2].includes(hIdx) ? -1 : 1;
          lyr.scale_y = Math.max(0.1, Math.min(5.0, (lyr.scale_y ?? 1) + (signY * dy) / lh));
        }
        bkrView.dragStartScene = scenePt;
        bkrView.dirtyDuringDrag = true;
        renderLayerSettings(bkrView.layers);
        drawBakerCanvas();
      }
      return;
    }

    if (bkrView.drawingMode || bkrView.eraseMode) {
      updateBakerCursor();
      drawBakerCanvas();
    } else {
      updateBakerCursor(hitTestBakerLayer(scenePt));
    }
  });

  window.addEventListener("mouseup", () => {
    if (bkrView.isPanning) {
      bkrView.isPanning = false;
      updateBakerCursor();
    }
    if (bkrView.action) {
      const shouldSync = bkrView.dirtyDuringDrag;
      bkrView.action = null;
      bkrView.dragStartScene = null;
      bkrView.currentStroke = null;
      bkrView.dirtyDuringDrag = false;
      if (shouldSync) {
        syncLayersToServer(true, "Updated layer transform");
      } else {
        syncLayersToServer(false, "");
      }
    }
  });

  bkrCanvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      if (bkrView.drawingMode || bkrView.eraseMode) {
        const delta = e.deltaY < 0 ? 1 : -1;
        bkrView.brushSize = Math.max(1, Math.min(50, bkrView.brushSize + delta));
        drawBakerCanvas();
        return;
      }
      const rect = bkrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const newZoom = Math.max(0.1, Math.min(10.0, bkrView.zoom * factor));
      bkrView.offsetX = sx - ((sx - bkrView.offsetX) / bkrView.zoom) * newZoom;
      bkrView.offsetY = sy - ((sy - bkrView.offsetY) / bkrView.zoom) * newZoom;
      bkrView.zoom = newZoom;
      drawBakerCanvas();
      updateZoomReadout();
    },
    { passive: false }
  );

  function erasePointsOnLayer(lyr, lx, ly) {
    if (!lyr.drawing_states) return;
    const eraseRadius = bkrView.brushSize * 2;
    const updated = [];
    for (const st of lyr.drawing_states) {
      const remaining = (st.points || []).filter(
        (pt) => Math.hypot(pt[0] - lx, pt[1] - ly) > eraseRadius
      );
      if (remaining.length > 0) {
        updated.push({ ...st, points: remaining });
      }
    }
    lyr.drawing_states = updated;
  }

  async function syncLayersToServer(pushUndo = true, message = "") {
    try {
      const res = await apiPost("/api/baker/layers/update", {
        layers: bkrView.layers,
        push_undo: pushUndo,
        message,
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Baker", err.message);
    }
  }

  // ==================== BUTTON & CONTROL BINDINGS ====================
  // Top Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.blur();
      const tab = btn.dataset.tab;
      try {
        const res = await apiPost("/api/settings", { active_tab: tab });
        applyServerState(res.state);
      } catch (err) {
        showToast(tab, err.message);
      }
    });
  });

  if (el("btn-goto-baker")) {
    el("btn-goto-baker").addEventListener("click", async (e) => {
      e.currentTarget.blur();
      const res = await apiPost("/api/settings", { active_tab: "Baker" });
      applyServerState(res.state);
    });
  }

  // Header Prev / Next Navigation
  async function stepHeaderNavigation(delta) {
    const activeTab = appState?.active_tab || "Layerify";
    if (activeTab === "Layerify") {
      const imgs = appState?.layerify?.images || [];
      if (!imgs.length) return;
      const curIdx = appState?.layerify?.current_image_index ?? 0;
      const nextIdx = Math.max(0, Math.min(imgs.length - 1, curIdx + delta));
      if (nextIdx !== curIdx) {
        const nextImg = imgs[nextIdx];
        showLayerifyLoading(`Loading ${nextImg?.name || "image"}...`, 20);
        try {
          const res = await apiPost("/api/layerify/select-image", { index: nextIdx });
          applyServerState(res.state);
        } catch (err) {
          hideLayerifyLoading();
          showToast("Layerify", err.message);
        }
      }
    } else if (activeTab === "Baker") {
      const canvases = appState?.baker?.canvases || [];
      if (!canvases.length) return;
      const curPos = Math.max(0, canvases.findIndex((c) => c.selected));
      const nextPos = Math.max(0, Math.min(canvases.length - 1, curPos + delta));
      if (nextPos !== curPos) {
        const res = await apiPost("/api/baker/canvas", {
          action: "select",
          canvas_id: canvases[nextPos].canvas_id,
        });
        applyServerState(res.state);
      }
    }
  }

  if (el("btn-header-prev")) {
    el("btn-header-prev").addEventListener("click", (e) => {
      e.currentTarget.blur();
      stepHeaderNavigation(-1);
    });
  }
  if (el("btn-header-next")) {
    el("btn-header-next").addEventListener("click", (e) => {
      e.currentTarget.blur();
      stepHeaderNavigation(1);
    });
  }

  // Top-Right Zoom Controls
  function zoomActiveViewport(factor) {
    const activeTab = appState?.active_tab || "Layerify";
    if (activeTab === "Layerify") {
      const cx = lyrCanvas.width / 2;
      const cy = lyrCanvas.height / 2;
      const newZoom = Math.max(0.1, Math.min(10.0, lyrView.zoom * factor));
      lyrView.offsetX = cx - ((cx - lyrView.offsetX) / lyrView.zoom) * newZoom;
      lyrView.offsetY = cy - ((syCenter(lyrCanvas) - lyrView.offsetY) / lyrView.zoom) * newZoom;
      lyrView.zoom = newZoom;
      drawLayerifyCanvas();
    } else if (activeTab === "Baker") {
      const cx = bkrCanvas.width / 2;
      const cy = bkrCanvas.height / 2;
      const newZoom = Math.max(0.1, Math.min(10.0, bkrView.zoom * factor));
      bkrView.offsetX = cx - ((cx - bkrView.offsetX) / bkrView.zoom) * newZoom;
      bkrView.offsetY = cy - ((cy - bkrView.offsetY) / bkrView.zoom) * newZoom;
      bkrView.zoom = newZoom;
      drawBakerCanvas();
    }
    updateZoomReadout();
  }
  function syCenter(c) {
    return c.height / 2;
  }

  if (el("btn-zoom-in")) {
    el("btn-zoom-in").addEventListener("click", (e) => {
      e.currentTarget.blur();
      zoomActiveViewport(1.2);
    });
  }
  if (el("btn-zoom-out")) {
    el("btn-zoom-out").addEventListener("click", (e) => {
      e.currentTarget.blur();
      zoomActiveViewport(1 / 1.2);
    });
  }
  if (el("btn-zoom-reset")) {
    el("btn-zoom-reset").addEventListener("click", (e) => {
      e.currentTarget.blur();
      if ((appState?.active_tab || "Layerify") === "Baker") {
        bkrView.zoom = 1.0;
        bkrView.offsetX = 20;
        bkrView.offsetY = 20;
        drawBakerCanvas();
      } else {
        lyrView.zoom = 1.0;
        lyrView.offsetX = 20;
        lyrView.offsetY = 20;
        drawLayerifyCanvas();
      }
      updateZoomReadout();
    });
  }
  if (el("btn-zoom-fit")) {
    el("btn-zoom-fit").addEventListener("click", (e) => {
      e.currentTarget.blur();
      fitLayerifyImageIfNeeded();
      drawLayerifyCanvas();
      updateZoomReadout();
    });
  }

  // Pagination Buttons
  el("img-prev-btn").addEventListener("click", () => {
    if (imagePage > 0) {
      imagePage--;
      renderImageList(appState?.layerify || {});
    }
  });
  el("img-next-btn").addEventListener("click", () => {
    imagePage++;
    renderImageList(appState?.layerify || {});
  });
  el("canvas-prev-btn").addEventListener("click", () => {
    if (canvasPage > 0) {
      canvasPage--;
      renderCanvasList(appState?.baker || {});
    }
  });
  el("canvas-next-btn").addEventListener("click", () => {
    canvasPage++;
    renderCanvasList(appState?.baker || {});
  });

  // Layerify Drawing Mode Buttons (Left Tool Strip)
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.blur();
      setLayerifyMode(btn.dataset.mode);
    });
  });

  async function performLayerifyUndo() {
    if (lyrView.mode === "Polygon" && lyrView.polyPoints.length > 0) {
      lyrView.polyPoints.pop();
      updateLayerifyHud();
      drawLayerifyCanvas();
      return;
    }
    const res = await apiPost("/api/layerify/annotations/action", { action: "undo" });
    applyServerState(res.state);
  }

  async function performLayerifyRedo() {
    const res = await apiPost("/api/layerify/annotations/action", { action: "redo" });
    applyServerState(res.state);
  }

  // Left Tool Strip Action Buttons & HUD Controls
  if (el("strip-btn-undo")) {
    el("strip-btn-undo").addEventListener("click", async (e) => {
      e.currentTarget.blur();
      await performLayerifyUndo();
    });
  }
  if (el("strip-btn-redo")) {
    el("strip-btn-redo").addEventListener("click", async (e) => {
      e.currentTarget.blur();
      await performLayerifyRedo();
    });
  }
  if (el("strip-btn-caption")) {
    el("strip-btn-caption").addEventListener("click", (e) => {
      e.currentTarget.blur();
      const selIdx = lyrView.annotations.findIndex((a) => a.selected);
      if (selIdx < 0) {
        showToast("Layerify", "Select an annotation first to edit its caption/label.");
        return;
      }
      openEditCaptionModal({ type: "layerify", annIdx: selIdx });
    });
  }
  if (el("strip-btn-vis")) {
    el("strip-btn-vis").addEventListener("click", (e) => {
      e.currentTarget.blur();
      const sel = lyrView.annotations.filter((a) => a.selected);
      if (sel.length > 0) {
        sel.forEach((a) => (a.visible = a.visible === false ? true : false));
        syncAnnotationsToServer(true, "Toggled annotation visibility");
      } else {
        showToast("Layerify", "Select an annotation first to toggle visibility.");
      }
    });
  }
  if (el("strip-btn-delete")) {
    el("strip-btn-delete").addEventListener("click", (e) => {
      e.currentTarget.blur();
      const before = lyrView.annotations.length;
      lyrView.annotations = lyrView.annotations.filter((a) => !a.selected);
      if (lyrView.annotations.length !== before) {
        syncAnnotationsToServer(true, "Deleted selected annotation(s)");
      } else {
        showToast("Layerify", "Select an annotation first to delete it.");
      }
    });
  }
  if (el("btn-finish-polygon")) {
    el("btn-finish-polygon").addEventListener("click", (e) => {
      e.currentTarget.blur();
      finishCurrentPolygonDrawing();
    });
  }
  if (el("input-lyr-brush-size")) {
    el("input-lyr-brush-size").addEventListener("input", (e) => {
      lyrView.brushSize = Number(e.target.value) || 18;
      if (el("val-lyr-brush-size")) el("val-lyr-brush-size").textContent = `${lyrView.brushSize}px`;
      drawLayerifyCanvas();
    });
  }

  // Regions Dock Header Actions & Inspector Buttons
  if (el("btn-select-all-anns")) {
    el("btn-select-all-anns").addEventListener("click", (e) => {
      e.currentTarget.blur();
      if (!lyrView.annotations.length) return;
      const allSel = lyrView.annotations.every((a) => a.selected);
      lyrView.annotations.forEach((a) => (a.selected = !allSel));
      syncAnnotationsToServer(false, allSel ? "Deselected all annotations" : "Selected all annotations");
    });
  }
  if (el("btn-toggle-all-anns-vis")) {
    el("btn-toggle-all-anns-vis").addEventListener("click", (e) => {
      e.currentTarget.blur();
      if (!lyrView.annotations.length) return;
      const anyVis = lyrView.annotations.some((a) => a.visible !== false);
      lyrView.annotations.forEach((a) => (a.visible = !anyVis));
      syncAnnotationsToServer(true, anyVis ? "Hid all annotations" : "Showed all annotations");
    });
  }
  if (el("btn-insp-caption")) {
    el("btn-insp-caption").addEventListener("click", () => {
      const selIdx = lyrView.annotations.findIndex((a) => a.selected);
      if (selIdx >= 0) openEditCaptionModal({ type: "layerify", annIdx: selIdx });
    });
  }

  // Grid & Theme Toggles (Top-Right + Baker Toolbar)
  async function toggleGridlines(e) {
    if (e && e.currentTarget) e.currentTarget.blur();
    const next = !appState?.show_gridlines;
    const res = await apiPost("/api/settings", { show_gridlines: next });
    applyServerState(res.state);
  }
  async function toggleTheme(e) {
    if (e && e.currentTarget) e.currentTarget.blur();
    const next = appState?.theme_mode === "dark" ? "light" : "dark";
    const res = await apiPost("/api/settings", { theme_mode: next });
    applyServerState(res.state);
  }
  if (el("btn-top-grid")) el("btn-top-grid").addEventListener("click", toggleGridlines);
  if (el("btn-top-theme")) el("btn-top-theme").addEventListener("click", toggleTheme);
  if (el("btn-baker-grid")) el("btn-baker-grid").addEventListener("click", toggleGridlines);
  if (el("btn-baker-theme")) el("btn-baker-theme").addEventListener("click", toggleTheme);

  // Select Folder Modal (Left Dock)
  const openSelectFolderDialog = async (e) => {
    if (e && e.currentTarget) e.currentTarget.blur();
    openModal("modal-folder-browser");
    await browseFolder(appState?.layerify?.current_folder || "");
  };
  if (el("btn-select-folder-left")) {
    el("btn-select-folder-left").addEventListener("click", openSelectFolderDialog);
  }
  el("btn-browse-go").addEventListener("click", async () => {
    await browseFolder(el("input-folder-path").value.trim());
  });
  el("input-folder-path").addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      await browseFolder(el("input-folder-path").value.trim());
    }
  });

  async function selectServerFolderPath(folderPath) {
    if (!folderPath) return;
    try {
      showLayerifyLoading("Loading folder images...", 20);
      const res = await apiPost("/api/layerify/select-folder", { folder_path: folderPath });
      closeAllModals();
      imagePage = 0;
      applyServerState(res.state);
    } catch (err) {
      hideLayerifyLoading();
      showToast("Layerify", err.message);
    }
  }

  el("btn-confirm-select-folder").addEventListener("click", async () => {
    await selectServerFolderPath(el("input-folder-path").value.trim());
  });

  // Native OS Local Folder Picker (webkitdirectory)
  if (el("btn-pick-local-folder")) {
    el("btn-pick-local-folder").addEventListener("click", () => {
      const inp = el("hidden-folder-upload-input");
      if (inp) {
        inp.value = "";
        inp.click();
      }
    });
  }
  if (el("hidden-folder-upload-input")) {
    el("hidden-folder-upload-input").addEventListener("change", async (e) => {
      const allFiles = Array.from(e.target.files || []);
      const validExts = [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"];
      const files = allFiles.filter((f) =>
        validExts.some((ext) => f.name.toLowerCase().endsWith(ext))
      );
      if (files.length === 0) {
        showToast("Layerify", "No supported image files found in the selected folder.");
        return;
      }
      let folderName = "uploaded_folder";
      if (files[0].webkitRelativePath) {
        folderName = files[0].webkitRelativePath.split("/")[0] || folderName;
      }
      closeAllModals();
      showLayerifyLoading(`Importing ${files.length} image(s)...`, 15);
      showToast("Layerify", `Importing ${files.length} image(s) from ${folderName}...`);
      const payloadFiles = [];
      for (const f of files) {
        const b64 = await readFileAsDataUrl(f);
        payloadFiles.push({ name: f.name, data_b64: b64 });
      }
      e.target.value = "";
      try {
        const res = await apiPost("/api/layerify/upload-images", {
          files: payloadFiles,
          folder_name: folderName,
        });
        imagePage = 0;
        applyServerState(res.state);
        showToast("Layerify", `Loaded ${files.length} image(s) from ${folderName}`);
      } catch (err) {
        hideLayerifyLoading();
        showToast("Layerify", err.message);
      }
    });
  }

  async function browseFolder(pathStr) {
    try {
      const data = await apiGet(`/api/layerify/browse-folders?path=${encodeURIComponent(pathStr)}`);
      el("input-folder-path").value = data.current || "";
      el("folder-image-count-info").textContent =
        `Subfolders: ${(data.directories || []).length} • Supported images in this folder: ${data.image_count || 0}`;

      // Render quick-access path pills
      const quickWrap = el("folder-quick-paths");
      if (quickWrap) {
        quickWrap.innerHTML = "";
        (data.quick_paths || []).forEach((qp) => {
          const pill = document.createElement("button");
          pill.className = "quick-path-pill";
          pill.textContent = `📌 ${qp.name}`;
          pill.title = qp.path;
          pill.addEventListener("click", () => browseFolder(qp.path));
          quickWrap.appendChild(pill);
        });
      }

      const list = el("folder-browser-list");
      list.innerHTML = "";

      if (data.parent && data.parent !== data.current) {
        const upRow = document.createElement("div");
        upRow.className = "folder-row";
        upRow.innerHTML = `<span>📁 .. (Parent Directory)</span>`;
        upRow.addEventListener("click", () => browseFolder(data.parent));
        list.appendChild(upRow);
      }

      if (data.directories && data.directories.length > 0) {
        const sec = document.createElement("div");
        sec.className = "folder-section-title";
        sec.textContent = "Subfolders (click to browse, or click Load)";
        list.appendChild(sec);

        data.directories.forEach((dir) => {
          const row = document.createElement("div");
          row.className = "folder-row";
          row.innerHTML = `
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">📁 ${escapeHtml(dir.name)}</span>
            <button class="btn btn-xs" title="Load images from this subfolder directly">Load</button>
          `;
          row.addEventListener("click", (e) => {
            if (e.target.closest("button")) return;
            browseFolder(dir.path);
          });
          row.querySelector("button").addEventListener("click", (e) => {
            e.stopPropagation();
            selectServerFolderPath(dir.path);
          });
          list.appendChild(row);
        });
      }

      if (data.images && data.images.length > 0) {
        const imgSec = document.createElement("div");
        imgSec.className = "folder-section-title";
        imgSec.textContent = `Images in This Folder (${data.image_count})`;
        list.appendChild(imgSec);

        data.images.forEach((imgItem) => {
          const fRow = document.createElement("div");
          fRow.className = "folder-file-item";
          fRow.innerHTML = `<span>🖼️</span><span>${escapeHtml(imgItem.name)}</span>`;
          list.appendChild(fRow);
        });
      }
    } catch (err) {
      showToast("Layerify", err.message);
    }
  }

  // Upload Local Images
  const triggerImageUpload = (e) => {
    if (e && e.currentTarget) e.currentTarget.blur();
    el("hidden-image-upload-input").click();
  };
  if (el("btn-upload-images-left")) {
    el("btn-upload-images-left").addEventListener("click", triggerImageUpload);
  }
  el("hidden-image-upload-input").addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    showLayerifyLoading(`Uploading ${files.length} image(s)...`, 20);
    const payloadFiles = [];
    for (const f of files) {
      const b64 = await readFileAsDataUrl(f);
      payloadFiles.push({ name: f.name, data_b64: b64 });
    }
    e.target.value = "";
    try {
      const res = await apiPost("/api/layerify/upload-images", { files: payloadFiles });
      applyServerState(res.state);
      showToast("Layerify", `Uploaded ${res.uploaded || files.length} image(s)`);
    } catch (err) {
      hideLayerifyLoading();
      showToast("Layerify", err.message);
    }
  });

  // Save / Load Annotations Modal
  function setAnnFormatOptions(mode) {
    const sel = el("select-ann-io-format");
    const autoOpt = el("opt-ann-format-auto");
    if (autoOpt) autoOpt.classList.toggle("hidden", mode !== "load");
    if (sel) sel.value = mode === "load" ? "auto" : "default";
    syncAnnFilePathExt();
  }
  function syncAnnFilePathExt() {
    const sel = el("select-ann-io-format");
    const inp = el("input-ann-file-path");
    if (!sel || !inp || annIoMode !== "save") return;
    const fmt = sel.value;
    const stem = (inp.value.trim() || "annotations").replace(/\.(json|txt|zip)$/i, "").replace(/_coco$/i, "");
    inp.value = fmt === "yolo" ? `${stem}.txt` : fmt === "coco" ? `${stem}_coco.json` : `${stem}.json`;
  }
  if (el("select-ann-io-format")) {
    el("select-ann-io-format").addEventListener("change", syncAnnFilePathExt);
  }

  if (el("btn-save-annotations")) {
    el("btn-save-annotations").addEventListener("click", (e) => {
      e.currentTarget.blur();
      annIoMode = "save";
      el("modal-ann-io-title").textContent = "Save / Export Annotations";
      el("modal-ann-io-desc").textContent =
        "Choose a format, then save annotations for all layers or just the current layer.";
      el("group-ann-file-upload").classList.add("hidden");
      setAnnFormatOptions("save");
      openModal("modal-annotations-io");
    });
  }
  if (el("btn-load-annotations")) {
    el("btn-load-annotations").addEventListener("click", (e) => {
      e.currentTarget.blur();
      annIoMode = "load";
      el("modal-ann-io-title").textContent = "Load / Import Annotations";
      el("modal-ann-io-desc").textContent =
        "Choose a format (or Auto-Detect), then load annotations for all layers or just the current layer.";
      el("group-ann-file-upload").classList.remove("hidden");
      el("input-ann-upload-json").value = "";
      setAnnFormatOptions("load");
      openModal("modal-annotations-io");
    });
  }

  async function handleAnnotationsIo(allLayers) {
    const filePath = el("input-ann-file-path").value.trim() || "annotations.json";
    const fmt = el("select-ann-io-format")?.value || (annIoMode === "save" ? "default" : "auto");
    try {
      if (annIoMode === "save") {
        const res = await apiPost("/api/layerify/annotations/save", {
          all_layers: allLayers,
          file_path: filePath,
          format: fmt,
        });
        closeAllModals();
        applyServerState(res.state);
        const content = res.content ?? res.json_content;
        if (content) {
          downloadTextFile(res.filename || filePath.split(/[\\/]/).pop() || "annotations.json", content);
        }
        if (res.classes_txt) {
          downloadTextFile("classes.txt", res.classes_txt);
        }
        showToast("Layerify", res.message || "Annotations saved");
      } else {
        const uploadInput = el("input-ann-upload-json");
        const payload = { all_layers: allLayers, file_path: filePath, format: fmt };
        if (uploadInput.files && uploadInput.files[0]) {
          const f = uploadInput.files[0];
          if (f.name.toLowerCase().endsWith(".zip")) {
            const dataUrl = await readFileAsDataUrl(f);
            payload.content_b64 = dataUrl.split(",")[1] || "";
          } else {
            payload.json_content = await f.text();
          }
        }
        const res = await apiPost("/api/layerify/annotations/load", payload);
        closeAllModals();
        applyServerState(res.state);
        showToast("Layerify", res.message || "Annotations loaded");
      }
    } catch (err) {
      showToast("Layerify", err.message);
    }
  }
  el("btn-ann-io-single").addEventListener("click", () => handleAnnotationsIo(false));
  el("btn-ann-io-all").addEventListener("click", () => handleAnnotationsIo(true));

  // Predict, Color, Single Layerify All Button, Add Label, Clear, Model Select, Manage Labels
  async function runModelPrediction(e) {
    if (e && e.currentTarget) e.currentTarget.blur();
    try {
      showToast("Layerify", "Running model prediction...");
      const res = await apiPost("/api/layerify/model", { action: "predict" });
      applyServerState(res.state);
      showToast("Layerify", res.message || "Prediction completed");
    } catch (err) {
      showToast("Layerify", err.message);
    }
  }
  if (el("btn-predict")) {
    el("btn-predict").addEventListener("click", runModelPrediction);
  }

  const openColorPicker = (e) => {
    if (e && e.currentTarget) e.currentTarget.blur();
    el("input-label-color-picker").click();
  };
  if (el("btn-quick-label-color")) {
    el("btn-quick-label-color").addEventListener("click", openColorPicker);
  }
  el("input-label-color-picker").addEventListener("input", async (e) => {
    const rgb = hexToRgb(e.target.value);
    const label = (appState?.layerify?.selected_label || "").trim() || "Undefined";
    try {
      const res = await apiPost("/api/layerify/labels", {
        action: "color",
        label,
        color: rgb,
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Layerify", err.message);
    }
  });

  if (el("btn-layerify-all")) {
    el("btn-layerify-all").addEventListener("click", async (e) => {
      e.currentTarget.blur();
      await layerifyAnnotations(null);
    });
  }

  function openAddLabelModal(e) {
    if (e && e.currentTarget) e.currentTarget.blur();
    const palette = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"];
    const nextColor = palette[(appState?.layerify?.labels?.length || 0) % palette.length];
    el("input-new-label-name").value = "";
    el("input-new-label-color").value = nextColor;
    openModal("modal-add-label");
    setTimeout(() => el("input-new-label-name").focus(), 30);
  }

  if (el("btn-quick-add-label")) {
    el("btn-quick-add-label").addEventListener("click", openAddLabelModal);
  }

  async function submitAddLabelModal() {
    const name = el("input-new-label-name").value.trim();
    if (!name) return;
    const rgb = hexToRgb(el("input-new-label-color").value);
    closeAllModals();
    try {
      const res = await apiPost("/api/layerify/labels", {
        action: "add",
        label: name,
        color: rgb,
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Layerify", err.message);
    }
  }
  if (el("btn-confirm-add-label")) {
    el("btn-confirm-add-label").addEventListener("click", submitAddLabelModal);
    el("input-new-label-name").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitAddLabelModal();
      }
    });
  }

  // Edit Region / Layer Caption & Label Modal
  function openEditCaptionModal(ctx) {
    editCaptionContext = ctx;
    if (ctx.type === "layerify") {
      const ann = lyrView.annotations[ctx.annIdx];
      if (!ann) return;
      el("modal-edit-caption-title").textContent = `Edit Region #${ctx.annIdx + 1}`;
      el("group-edit-region-label").classList.remove("hidden");
      const sel = el("select-edit-region-label");
      sel.innerHTML = "";
      (appState?.layerify?.labels || []).forEach((l) => {
        const opt = document.createElement("option");
        opt.value = l.name;
        opt.textContent = l.name;
        if (l.name === ann.label) opt.selected = true;
        sel.appendChild(opt);
      });
      el("input-edit-region-label").value = ann.label || "";
      sel.onchange = () => {
        el("input-edit-region-label").value = sel.value;
      };
      el("input-edit-region-caption").value = ann.caption || "";
    } else if (ctx.type === "baker") {
      const selLayer = bkrView.layers.find((l) => l.selected);
      if (!selLayer) return;
      el("modal-edit-caption-title").textContent = `Edit Layer Caption (${selLayer.label})`;
      el("group-edit-region-label").classList.add("hidden");
      el("input-edit-region-caption").value = selLayer.caption || "";
    }
    openModal("modal-edit-caption");
    setTimeout(() => el("input-edit-region-caption").focus(), 30);
  }

  async function submitEditCaptionModal() {
    if (!editCaptionContext) return;
    const cap = el("input-edit-region-caption").value;
    if (editCaptionContext.type === "layerify") {
      const ann = lyrView.annotations[editCaptionContext.annIdx];
      if (ann) {
        const newLbl = el("input-edit-region-label").value.trim() || ann.label || "Undefined";
        ann.label = newLbl;
        const known = (appState?.layerify?.labels || []).find((l) => l.name === newLbl);
        if (known) ann.color = known.color;
        ann.caption = cap;
        closeAllModals();
        await syncAnnotationsToServer(true, `Updated region #${editCaptionContext.annIdx + 1}`);
      }
    } else if (editCaptionContext.type === "baker") {
      const selLayer = bkrView.layers.find((l) => l.selected);
      if (selLayer) {
        selLayer.caption = cap;
        closeAllModals();
        await syncLayersToServer(true, "Updated layer caption");
      }
    }
  }
  if (el("btn-confirm-edit-caption")) {
    el("btn-confirm-edit-caption").addEventListener("click", submitEditCaptionModal);
    el("input-edit-region-caption").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitEditCaptionModal();
      }
    });
  }

  if (el("btn-clear-annotations")) {
    el("btn-clear-annotations").addEventListener("click", async (e) => {
      e.currentTarget.blur();
      try {
        const res = await apiPost("/api/layerify/annotations/action", { action: "clear" });
        applyServerState(res.state);
      } catch (err) {
        showToast("Layerify", err.message);
      }
    });
  }

  if (el("select-model")) {
    el("select-model").addEventListener("change", async (e) => {
      const val = e.target.value;
      e.target.blur(); // Prevent trapping keyboard shortcuts!
      try {
        const res = await apiPost("/api/layerify/model", {
          action: "select",
          model_name: val,
        });
        applyServerState(res.state);
      } catch (err) {
        showToast("Layerify", err.message);
      }
    });
  }

  // Manage Labels Modal (direct cache editing for labels.json)
  function renderManageLabelsModal() {
    const listEl = el("manage-labels-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    const labels = appState?.layerify?.labels || [];
    labels.forEach((lbl) => {
      const row = document.createElement("div");
      row.className = "folder-row";
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px 8px;";

      const colorInput = document.createElement("input");
      colorInput.type = "color";
      const [r, g, b] = lbl.color || [255, 255, 255];
      colorInput.value = rgbToHex(r, g, b);
      colorInput.style.cssText = "width:30px;height:26px;padding:1px;border-radius:4px;cursor:pointer;";
      colorInput.title = `Change color for ${lbl.name}`;
      colorInput.addEventListener("change", async () => {
        try {
          const res = await apiPost("/api/layerify/labels", {
            action: "color",
            label: lbl.name,
            color: hexToRgb(colorInput.value),
          });
          applyServerState(res.state);
          renderManageLabelsModal();
        } catch (err) {
          showToast("Layerify", err.message);
        }
      });

      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.className = "text-input";
      nameInput.style.cssText = "flex:1;height:28px;font-size:12px;";
      nameInput.value = lbl.name;
      nameInput.disabled = lbl.name === "Undefined";

      const saveBtn = document.createElement("button");
      saveBtn.className = "btn btn-xs";
      saveBtn.textContent = "Save";
      saveBtn.disabled = lbl.name === "Undefined";
      const doRename = async () => {
        const nextName = nameInput.value.trim();
        if (!nextName || nextName === lbl.name) return;
        try {
          const res = await apiPost("/api/layerify/labels", {
            action: "rename",
            old_label: lbl.name,
            new_label: nextName,
          });
          applyServerState(res.state);
          renderManageLabelsModal();
        } catch (err) {
          showToast("Layerify", err.message);
        }
      };
      saveBtn.addEventListener("click", doRename);
      nameInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          doRename();
        }
      });

      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-xs btn-danger";
      delBtn.textContent = "Delete";
      delBtn.disabled = lbl.name === "Undefined";
      delBtn.addEventListener("click", async () => {
        try {
          const res = await apiPost("/api/layerify/labels", {
            action: "delete",
            label: lbl.name,
          });
          applyServerState(res.state);
          renderManageLabelsModal();
        } catch (err) {
          showToast("Layerify", err.message);
        }
      });

      row.appendChild(colorInput);
      row.appendChild(nameInput);
      row.appendChild(saveBtn);
      row.appendChild(delBtn);
      listEl.appendChild(row);
    });
  }

  const openManageLabelsDialog = (e) => {
    if (e && e.currentTarget) e.currentTarget.blur();
    renderManageLabelsModal();
    openModal("modal-manage-label");
  };
  if (el("btn-quick-manage-label")) {
    el("btn-quick-manage-label").addEventListener("click", openManageLabelsDialog);
  }
  if (el("btn-manage-add-label")) {
    const addFromManageModal = async () => {
      const inp = el("input-manage-new-label");
      const name = (inp?.value || "").trim();
      if (!name) return;
      const colorInp = el("input-manage-new-color");
      const rgb = hexToRgb(colorInp?.value || "#3b82f6");
      try {
        const res = await apiPost("/api/layerify/labels", {
          action: "add",
          label: name,
          color: rgb,
        });
        if (inp) inp.value = "";
        applyServerState(res.state);
        renderManageLabelsModal();
      } catch (err) {
        showToast("Layerify", err.message);
      }
    };
    el("btn-manage-add-label").addEventListener("click", addFromManageModal);
    if (el("input-manage-new-label")) {
      el("input-manage-new-label").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          addFromManageModal();
        }
      });
    }
  }

  // Baker Canvas List & Layer Actions (uses clean modal instead of window.prompt)
  el("btn-create-canvas").addEventListener("click", (e) => {
    e.currentTarget.blur();
    el("input-create-canvas-name").value = `Canvas_${(appState?.baker?.canvases?.length || 0) + 1}`;
    openModal("modal-create-canvas");
    setTimeout(() => el("input-create-canvas-name").focus(), 30);
  });

  async function submitCreateCanvasModal() {
    const name = el("input-create-canvas-name").value.trim() || "Canvas";
    closeAllModals();
    try {
      const res = await apiPost("/api/baker/canvas", {
        action: "create",
        name,
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Baker", err.message);
    }
  }
  if (el("btn-confirm-create-canvas")) {
    el("btn-confirm-create-canvas").addEventListener("click", submitCreateCanvasModal);
    el("input-create-canvas-name").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitCreateCanvasModal();
      }
    });
  }

  if (el("btn-baker-undo")) {
    el("btn-baker-undo").addEventListener("click", async (e) => {
      e.currentTarget.blur();
      const res = await apiPost("/api/baker/layers/action", { action: "undo" });
      applyServerState(res.state);
    });
  }
  if (el("btn-baker-redo")) {
    el("btn-baker-redo").addEventListener("click", async (e) => {
      e.currentTarget.blur();
      const res = await apiPost("/api/baker/layers/action", { action: "redo" });
      applyServerState(res.state);
    });
  }

  el("btn-add-blank-layer").addEventListener("click", async (e) => {
    e.currentTarget.blur();
    try {
      const res = await apiPost("/api/baker/layers/add-blank", {
        width: 512,
        height: 512,
        label: (appState?.layerify?.selected_label || "").trim() || "Undefined",
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Baker", err.message);
    }
  });

  async function groupSelectedLayers(e) {
    if (e && e.currentTarget) e.currentTarget.blur();
    try {
      const res = await apiPost("/api/baker/layers/action", { action: "group" });
      applyServerState(res.state);
      showToast(appState?.active_tab || "Baker", res.grouped ? "Grouped selected layers" : "Select at least 2 layers to group");
    } catch (err) {
      showToast("Baker", err.message);
    }
  }
  el("btn-group-layers-layerify").addEventListener("click", groupSelectedLayers);
  el("btn-group-layers-baker").addEventListener("click", groupSelectedLayers);
  el("btn-group-layers-tool").addEventListener("click", groupSelectedLayers);

  el("btn-convert-ann-type").addEventListener("click", async (e) => {
    e.currentTarget.blur();
    try {
      const res = await apiPost("/api/baker/layers/action", { action: "convert_ann_type" });
      applyServerState(res.state);
      if (!res.converted) {
        showToast("Baker", "Select a layer with rectangle or polygon geometry to convert.");
      }
    } catch (err) {
      showToast("Baker", err.message);
    }
  });

  // BaseLayer Settings Sliders
  function bindLayerSlider(sliderId, valId, applyFn) {
    const s = el(sliderId);
    s.addEventListener("input", () => {
      const active = bkrView.layers.find((l) => l.selected);
      if (!active) return;
      applyFn(active, Number(s.value));
      renderLayerSettings(bkrView.layers);
      drawBakerCanvas();
    });
    s.addEventListener("change", () => {
      s.blur();
      syncLayersToServer(true, `Adjusted ${sliderId.replace("slider-", "")}`);
    });
  }

  bindLayerSlider("slider-opacity", "val-opacity", (lyr, v) => {
    lyr.opacity = v;
  });
  bindLayerSlider("slider-xpos", "val-xpos", (lyr, v) => {
    lyr.position = [v, lyr.position?.[1] ?? 0];
  });
  bindLayerSlider("slider-ypos", "val-ypos", (lyr, v) => {
    lyr.position = [lyr.position?.[0] ?? 0, v];
  });
  bindLayerSlider("slider-scalex", "val-scalex", (lyr, v) => {
    lyr.scale_x = v / 100.0;
  });
  bindLayerSlider("slider-scaley", "val-scaley", (lyr, v) => {
    lyr.scale_y = v / 100.0;
  });
  bindLayerSlider("slider-rotation", "val-rotation", (lyr, v) => {
    lyr.rotation = v;
  });
  bindLayerSlider("slider-edge-opacity", "val-edge-opacity", (lyr, v) => {
    lyr.edge_opacity = v;
  });
  bindLayerSlider("slider-edge-width", "val-edge-width", (lyr, v) => {
    lyr.edge_width = v;
  });

  el("input-layer-caption").addEventListener("change", (e) => {
    const active = bkrView.layers.find((l) => l.selected);
    if (!active) return;
    active.caption = e.target.value;
    syncLayersToServer(true, "Updated layer caption");
  });

  // Baker States & Baking Buttons (passes steps & resets spinbox to 1 like Windows BakerTab)
  let pendingBakerExportMode = "states_local";
  function openBakerExportPrompt(mode, title, desc, skipLabel) {
    pendingBakerExportMode = mode;
    el("modal-baker-export-title").textContent = title;
    el("modal-baker-export-desc").textContent = desc;
    el("btn-baker-export-skip").textContent = skipLabel || "Cancel";
    openModal("modal-baker-export-prompt");
  }

  async function saveBakerState(e) {
    if (e && e.currentTarget) e.currentTarget.blur();
    const stepsInput = el("input-bake-steps");
    const steps = Math.max(1, Number((stepsInput && stepsInput.value) || 1));
    try {
      const res = await apiPost("/api/baker/states", { action: "save", steps });
      if (stepsInput) stepsInput.value = "1";
      applyServerState(res.state);
      if (res.ok !== false) {
        openBakerExportPrompt(
          "states_local",
          "State Saved — Download Baked States?",
          `${res.message || "State saved."} Do you want to bake and download all saved states with their annotations now?`,
          "Skip Download"
        );
      }
    } catch (err) {
      showToast("Baker", err.message);
    }
  }
  el("btn-save-state").addEventListener("click", saveBakerState);

  if (el("btn-baker-export-confirm")) {
    el("btn-baker-export-confirm").addEventListener("click", async () => {
      const fmt = el("select-baker-export-format")?.value || "default";
      closeAllModals();
      await triggerBakeExport(pendingBakerExportMode, null, fmt, true);
    });
  }

  el("btn-randomize-states").addEventListener("click", async (e) => {
    e.currentTarget.blur();
    const steps = Math.max(1, Number(el("input-bake-steps").value || 1));
    try {
      const res = await apiPost("/api/baker/states", {
        action: "randomize",
        steps,
      });
      applyServerState(res.state);
      showToast("Baker", `Generated ${res.generated || steps} state(s)`);
    } catch (err) {
      showToast("Baker", err.message);
    }
  });

  el("slider-state-timeline").addEventListener("input", async (e) => {
    const step = Number(e.target.value);
    try {
      const res = await apiPost("/api/baker/states", {
        action: "seek",
        step,
      });
      applyServerState(res.state);
    } catch (err) {
      showToast("Baker", err.message);
    }
  });

  el("btn-clear-states").addEventListener("click", async (e) => {
    e.currentTarget.blur();
    stopPlayingStates();
    try {
      const res = await apiPost("/api/baker/states", { action: "clear" });
      applyServerState(res.state);
    } catch (err) {
      showToast("Baker", err.message);
    }
  });

  el("btn-play-states").addEventListener("click", (e) => {
    e.currentTarget.blur();
    if (bkrView.playTimer) {
      stopPlayingStates();
    } else {
      startPlayingStates();
    }
  });

  function startPlayingStates() {
    const numStates = appState?.baker?.num_states || 0;
    if (numStates <= 0) return;
    const fps = Math.max(1, appState?.configs?.bake_config?.fps || 10);
    el("btn-play-states").textContent = "Stop States";
    el("btn-play-states").classList.add("active");

    bkrView.playTimer = setInterval(async () => {
      const total = appState?.baker?.num_states || 0;
      if (total <= 0) {
        stopPlayingStates();
        return;
      }
      const nextStep = ((appState?.baker?.current_state_step || 0) + 1) % total;
      try {
        const res = await apiPost("/api/baker/states", {
          action: "seek",
          step: nextStep,
        });
        applyServerState(res.state);
      } catch (_err) {
        stopPlayingStates();
      }
    }, Math.round(1000 / fps));
  }

  function stopPlayingStates() {
    if (bkrView.playTimer) {
      clearInterval(bkrView.playTimer);
      bkrView.playTimer = null;
    }
    el("btn-play-states").textContent = "Play States";
    el("btn-play-states").classList.remove("active");
  }

  // Export & Bake Modes
  async function triggerBakeExport(mode, e, annotationFormat = "default", download = false) {
    if (e && e.currentTarget) e.currentTarget.blur();
    stopPlayingStates();
    try {
      showToast("Baker", "Baking canvas state(s)...");
      const res = await apiPost("/api/baker/export", { mode, annotation_format: annotationFormat });
      applyServerState(res.state);
      if (download) {
        (res.exported_files || []).forEach((fp) => {
          const name = String(fp).split(/[\\/]/).pop();
          const a = document.createElement("a");
          a.href = `/api/baker/exported-file?name=${encodeURIComponent(name)}`;
          a.download = name;
          document.body.appendChild(a);
          a.click();
          a.remove();
        });
        let classesDone = false;
        (res.annotation_exports || []).forEach((ex) => {
          if (ex.content) downloadTextFile(ex.filename, ex.content);
          if (ex.classes_txt && !classesDone) {
            downloadTextFile("classes.txt", ex.classes_txt);
            classesDone = true;
          }
        });
      }
      showToast(
        appState?.active_tab || "Baker",
        res.message || `Exported ${res.count || 0} baked state(s)`
      );
    } catch (err) {
      showToast("Baker", err.message);
    }
  }

  el("btn-export-current-state").addEventListener("click", (e) => {
    e.currentTarget.blur();
    openBakerExportPrompt(
      "current_local",
      "Export Current State",
      "Choose the annotation format for the exported current state.",
      "Cancel"
    );
  });
  el("btn-predict-state").addEventListener("click", (e) =>
    triggerBakeExport("predict_state", e)
  );
  el("btn-annotate-states").addEventListener("click", (e) =>
    triggerBakeExport("annotate_states", e)
  );
  el("btn-export-states").addEventListener("click", (e) => {
    e.currentTarget.blur();
    openBakerExportPrompt(
      "states_local",
      "Export All Saved States",
      "Choose the annotation format for all exported baked states.",
      "Cancel"
    );
  });

  // Plugin Dropdown
  el("btn-plugin-options").addEventListener("click", (e) => {
    e.stopPropagation();
    el("menu-plugin-options").classList.toggle("hidden");
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#plugin-dropdown-wrap")) {
      el("menu-plugin-options").classList.add("hidden");
    }
  });
  el("btn-reload-plugins").addEventListener("click", async () => {
    try {
      const res = await apiPost("/api/baker/plugins", { action: "reload" });
      applyServerState(res.state);
    } catch (err) {
      showToast("Baker", err.message);
    }
  });
  el("btn-clear-plugins").addEventListener("click", async () => {
    try {
      const res = await apiPost("/api/baker/plugins", { action: "clear" });
      applyServerState(res.state);
    } catch (err) {
      showToast("Baker", err.message);
    }
  });

  // Draw / Erase / Brush Color
  el("btn-draw-mode").addEventListener("click", (e) => {
    e.currentTarget.blur();
    bkrView.drawingMode = !bkrView.drawingMode;
    if (bkrView.drawingMode) bkrView.eraseMode = false;
    el("btn-draw-mode").classList.toggle("active", bkrView.drawingMode);
    el("btn-erase-mode").classList.toggle("active", bkrView.eraseMode);
    updateBakerCursor();
    drawBakerCanvas();
  });
  el("btn-erase-mode").addEventListener("click", (e) => {
    e.currentTarget.blur();
    bkrView.eraseMode = !bkrView.eraseMode;
    if (bkrView.eraseMode) bkrView.drawingMode = false;
    el("btn-erase-mode").classList.toggle("active", bkrView.eraseMode);
    el("btn-draw-mode").classList.toggle("active", bkrView.drawingMode);
    updateBakerCursor();
    drawBakerCanvas();
  });
  el("btn-brush-color").addEventListener("click", (e) => {
    e.currentTarget.blur();
    el("input-brush-color-picker").click();
  });
  el("input-brush-color-picker").addEventListener("input", (e) => {
    const [r, g, b] = hexToRgb(e.target.value);
    bkrView.brushColor = [r, g, b, 255];
  });

  // ==================== KEYBOARD SHORTCUTS (WINDOWS + LABEL STUDIO PARITY) ====================
  function isModalOpen() {
    const bd = el("modal-backdrop");
    return bd && !bd.classList.contains("hidden");
  }

  function isTypingInTextField(target) {
    if (!target) return false;
    const tag = (target.tagName || "").toUpperCase();
    if (tag === "TEXTAREA" || target.isContentEditable) return true;
    if (tag === "INPUT") {
      const type = (target.type || "text").toLowerCase();
      return ["text", "number", "search", "password", "url", "email"].includes(type);
    }
    return false;
  }

  // Spacebar hold for temporary Pan Mode in Layerify
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !isTypingInTextField(e.target) && !isModalOpen()) {
      e.preventDefault();
      if ((appState?.active_tab || "Layerify") === "Layerify" && lyrView.mode !== "Pan") {
        lyrView.modeBeforeSpace = lyrView.mode;
        setLayerifyMode("Pan");
      }
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.code === "Space" && lyrView.modeBeforeSpace) {
      setLayerifyMode(lyrView.modeBeforeSpace);
      lyrView.modeBeforeSpace = null;
    }
  });

  window.addEventListener("keydown", async (e) => {
    // Allow Escape to close open modals
    if (isModalOpen()) {
      if (e.key === "Escape") {
        e.preventDefault();
        closeAllModals();
      }
      return;
    }

    // Only ignore single-key shortcuts when typing inside a text/number input or textarea (NEVER block on <select> or <button>!)
    if (isTypingInTextField(e.target)) return;

    const activeTab = appState?.active_tab || "Layerify";
    const ctrl = e.ctrlKey || e.metaKey;

    // Global shortcuts: [ and ] for prev/next image/canvas, G for grid, F for fit
    if (!ctrl && e.key === "[") {
      e.preventDefault();
      await stepHeaderNavigation(-1);
      return;
    }
    if (!ctrl && e.key === "]") {
      e.preventDefault();
      await stepHeaderNavigation(1);
      return;
    }
    if (!ctrl && e.key.toLowerCase() === "g") {
      e.preventDefault();
      await toggleGridlines();
      return;
    }
    if (!ctrl && e.key.toLowerCase() === "f") {
      e.preventDefault();
      fitLayerifyImageIfNeeded();
      drawLayerifyCanvas();
      updateZoomReadout();
      return;
    }

    if (activeTab === "Layerify") {
      if (e.key === "Escape") {
        e.preventDefault();
        setLayerifyMode("Idle");
        const hadSel = lyrView.annotations.some((a) => a.selected);
        lyrView.annotations.forEach((a) => (a.selected = false));
        renderAnnotationList(lyrView.annotations);
        drawLayerifyCanvas();
        if (hadSel) {
          syncAnnotationsToServer(false, "Idle mode");
        }
      } else if (e.key === "Enter") {
        if (lyrView.mode === "Polygon" && lyrView.polyPoints.length >= 3) {
          e.preventDefault();
          finishCurrentPolygonDrawing();
        }
      } else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        if (lyrView.mode === "Polygon" && lyrView.polyPoints.length > 0) {
          lyrView.polyPoints.pop();
          updateLayerifyHud();
          drawLayerifyCanvas();
          return;
        }
        const before = lyrView.annotations.length;
        lyrView.annotations = lyrView.annotations.filter((a) => !a.selected);
        if (lyrView.annotations.length !== before) {
          syncAnnotationsToServer(true, "Deleted selected annotation(s)");
        }
      } else if (ctrl && e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        await performLayerifyRedo();
      } else if (ctrl && e.key.toLowerCase() === "z") {
        e.preventDefault();
        await performLayerifyUndo();
      } else if (ctrl && e.key.toLowerCase() === "y") {
        e.preventDefault();
        await performLayerifyRedo();
      } else if (ctrl && e.key.toLowerCase() === "c") {
        e.preventDefault();
        const res = await apiPost("/api/layerify/annotations/action", { action: "copy" });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "v") {
        e.preventDefault();
        const res = await apiPost("/api/layerify/annotations/action", { action: "paste" });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "a") {
        e.preventDefault();
        if (lyrView.annotations.length > 0) {
          lyrView.annotations.forEach((a) => (a.selected = true));
          syncAnnotationsToServer(false, "Selected all annotations");
        }
      } else if (!ctrl && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
        const sel = lyrView.annotations.filter((a) => a.selected);
        if (sel.length > 0 && lyrView.img) {
          e.preventDefault();
          const step = e.shiftKey ? 10 : 1;
          const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
          const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
          sel.forEach((a) => moveAnnotationByDelta(a, dx, dy, lyrView.img.width, lyrView.img.height));
          drawLayerifyCanvas();
          syncAnnotationsToServer(true, "Moved annotation(s)");
        }
      } else if (!ctrl && e.key.toLowerCase() === "q") {
        e.preventDefault();
        setLayerifyMode("Point");
      } else if (!ctrl && e.key.toLowerCase() === "w") {
        e.preventDefault();
        setLayerifyMode("Polygon");
      } else if (!ctrl && e.key.toLowerCase() === "e") {
        e.preventDefault();
        setLayerifyMode("Rectangle");
      } else if (!ctrl && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setLayerifyMode("Brush");
      } else if (!ctrl && e.key.toLowerCase() === "v") {
        e.preventDefault();
        setLayerifyMode("Idle");
      } else if (!ctrl && e.key.toLowerCase() === "l") {
        e.preventDefault();
        await layerifyAnnotations(null);
      } else if (!ctrl && e.key.toLowerCase() === "p") {
        e.preventDefault();
        await runModelPrediction();
      } else if (!ctrl && /^[0-9]$/.test(e.key)) {
        e.preventDefault();
        const idx = Number(e.key);
        const labels = appState?.layerify?.labels || [];
        if (idx < labels.length) {
          await selectLabelAndMaybeAssign(labels[idx].name);
        } else {
          openAddLabelModal();
        }
      } else if (!ctrl && e.key.toLowerCase() === "h") {
        e.preventDefault();
        const sel = lyrView.annotations.filter((a) => a.selected);
        if (sel.length > 0) {
          sel.forEach((a) => (a.visible = a.visible === false ? true : false));
          syncAnnotationsToServer(true, "Toggled annotation visibility");
        }
      } else if (!ctrl && e.key.toLowerCase() === "c") {
        e.preventDefault();
        const selIdx = lyrView.annotations.findIndex((a) => a.selected);
        if (selIdx >= 0) {
          openEditCaptionModal({ type: "layerify", annIdx: selIdx });
        } else {
          showToast("Layerify", "Select an annotation first to edit its caption/label.");
        }
      }
    } else if (activeTab === "Baker") {
      const selLayers = bkrView.layers.filter((l) => l.selected);
      if (e.key === "Delete" || e.key === "Backspace") {
        if (selLayers.length > 0) {
          e.preventDefault();
          const res = await apiPost("/api/baker/layers/action", { action: "delete" });
          applyServerState(res.state);
        }
      } else if (
        (ctrl && (e.key === "ArrowUp" || e.key === "ArrowDown")) ||
        (!ctrl && (e.key.toLowerCase() === "w" || e.key.toLowerCase() === "s"))
      ) {
        e.preventDefault();
        const dir =
          e.key === "ArrowUp" || e.key.toLowerCase() === "w" ? "up" : "down";
        const res = await apiPost("/api/baker/layers/reorder", { direction: dir });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "g") {
        e.preventDefault();
        await groupSelectedLayers();
      } else if (ctrl && e.key.toLowerCase() === "s") {
        e.preventDefault();
        await saveBakerState();
      } else if (ctrl && e.key.toLowerCase() === "n") {
        e.preventDefault();
        const res = await apiPost("/api/baker/layers/add-blank", {
          width: 512,
          height: 512,
          label: (appState?.layerify?.selected_label || "").trim() || "Undefined",
        });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "d") {
        e.preventDefault();
        el("btn-draw-mode").click();
      } else if (ctrl && e.key.toLowerCase() === "e") {
        e.preventDefault();
        el("btn-erase-mode").click();
      } else if (!ctrl && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
        if (selLayers.length > 0) {
          e.preventDefault();
          const step = e.shiftKey ? 20 : 5;
          const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
          const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
          selLayers.forEach((l) => {
            l.position = [(l.position?.[0] ?? 0) + dx, (l.position?.[1] ?? 0) + dy];
          });
          syncLayersToServer(true, "Moved layer(s)");
        }
      } else if (!ctrl && e.key.toLowerCase() === "r") {
        if (selLayers.length > 0) {
          const delta = e.shiftKey ? -5 : 5;
          selLayers.forEach((l) => {
            l.rotation = Math.max(-180, Math.min(180, (l.rotation ?? 0) + delta));
          });
          syncLayersToServer(true, "Rotated layer(s)");
        }
      } else if (ctrl && e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        const res = await apiPost("/api/baker/layers/action", { action: "redo" });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "z") {
        e.preventDefault();
        const res = await apiPost("/api/baker/layers/action", { action: "undo" });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "y") {
        e.preventDefault();
        const res = await apiPost("/api/baker/layers/action", { action: "redo" });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "c") {
        e.preventDefault();
        const res = await apiPost("/api/baker/layers/action", { action: "copy" });
        applyServerState(res.state);
      } else if (ctrl && e.key.toLowerCase() === "v") {
        e.preventDefault();
        const res = await apiPost("/api/baker/layers/action", { action: "paste" });
        applyServerState(res.state);
      } else if (!ctrl && e.key.toLowerCase() === "h") {
        if (selLayers.length > 0) {
          selLayers.forEach((l) => (l.visible = l.visible === false ? true : false));
          syncLayersToServer(true, "Toggled layer visibility");
        }
      } else if (!ctrl && e.key.toLowerCase() === "c") {
        if (selLayers.length === 1) {
          openEditCaptionModal({ type: "baker" });
        }
      }
    }
  });

  // ==================== MODAL & UTILITY HELPERS ====================
  function openModal(dialogId) {
    el("modal-backdrop").classList.remove("hidden");
    document.querySelectorAll(".modal-dialog").forEach((d) => {
      d.classList.toggle("hidden", d.id !== dialogId);
    });
  }

  function closeAllModals() {
    el("modal-backdrop").classList.add("hidden");
    document.querySelectorAll(".modal-dialog").forEach((d) => d.classList.add("hidden"));
  }

  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", closeAllModals);
  });

  function getCurrentSelectedLabelColor() {
    const lyr = appState?.layerify || {};
    const cur = (lyr.labels || []).find((l) => l.name === lyr.selected_label);
    return cur?.color || [255, 128, 0];
  }

  function moveAnnotationByDelta(ann, dx, dy, maxW, maxH) {
    const clampX = (x) => Math.max(0, Math.min(maxW, x));
    const clampY = (y) => Math.max(0, Math.min(maxH, y));
    if (ann.points && ann.points.length > 0) {
      ann.points = ann.points.map((pt) => [clampX(pt[0] + dx), clampY(pt[1] + dy)]);
    }
    if (ann.polygon && ann.polygon.length > 0) {
      ann.polygon = ann.polygon.map((pt) => [clampX(pt[0] + dx), clampY(pt[1] + dy)]);
    }
    if (ann.rectangle && ann.rectangle.length === 4) {
      const [x1, y1, x2, y2] = ann.rectangle;
      ann.rectangle = [clampX(x1 + dx), clampY(y1 + dy), clampX(x2 + dx), clampY(y2 + dy)];
    }
    if (ann.mask_png_b64) {
      ann.mask_offset_x = (ann.mask_offset_x || 0) + dx;
      ann.mask_offset_y = (ann.mask_offset_y || 0) + dy;
    }
  }

  function pointInPolygon(x, y, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0];
      const yi = poly[i][1];
      const xj = poly[j][0];
      const yj = poly[j][1];
      const intersect =
        yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi;
      if (intersect) inside = !inside;
    }
    return inside;
  }

  function distToSegment(px, py, x1, y1, x2, y2) {
    const l2 = (x2 - x1) ** 2 + (y2 - y1) ** 2;
    if (l2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function rgbToHex(r, g, b) {
    return (
      "#" +
      [r, g, b]
        .map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0"))
        .join("")
    );
  }

  function hexToRgb(hex) {
    const clean = (hex || "#ff8000").replace("#", "");
    const num = parseInt(clean, 16);
    return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
      reader.readAsDataURL(file);
    });
  }

  function downloadTextFile(filename, content) {
    const lower = String(filename || "").toLowerCase();
    const mime = lower.endsWith(".txt") ? "text/plain" : "application/json";
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  window.addEventListener("resize", () => {
    resizeCanvases();
    drawLayerifyCanvas();
    drawBakerCanvas();
  });

  // ==================== INITIAL BOOTSTRAP ====================
  async function init() {
    resizeCanvases();
    try {
      const res = await apiGet("/api/state");
      applyServerState(res.state);
    } catch (err) {
      showToast("Layerify", `Failed to load initial state: ${err.message}`);
    }
  }

  init();
})();
