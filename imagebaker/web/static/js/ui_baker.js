/**
 * ImageBaker Web - Baker UI & Grouped Layout Controls
 */
(function(window) {
  "use strict";

  const { state, bkrView, showToast, openModal, closeAllModals } = window.ImageBaker;
  const utils = window.ImageBaker.utils;
  const escapeHtml = (utils && utils.escapeHtml) ? utils.escapeHtml : (s => s);
  const api = window.ImageBaker.api;

  let canvasPage = 0;

  function initBakerUI() {
    bindBakerActionButtons();
    bindLayerSliders();
    bindModals();
  }

  function renderCanvasList() {
    const container = document.getElementById("canvas-list-items");
    const pageInfo = document.getElementById("canvas-page-info");
    const prevBtn = document.getElementById("canvas-prev-btn");
    const nextBtn = document.getElementById("canvas-next-btn");
    if (!container) return;

    const canvases = state.baker.canvases || [];
    const pageSize = 10;
    const total = canvases.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (canvasPage >= totalPages) canvasPage = totalPages - 1;
    if (canvasPage < 0) canvasPage = 0;

    const start = canvasPage * pageSize;
    const end = Math.min(start + pageSize, total);

    container.innerHTML = "";
    for (let i = start; i < end; i++) {
      const c = canvases[i];
      const isSelected = (c.canvas_id === state.baker.current_canvas_id) || Boolean(c.selected);
      const row = document.createElement("div");
      row.className = `list-item ${isSelected ? "selected" : ""}`;
      row.innerHTML = `
        <img class="item-thumb" src="${c.thumbnail || c.thumb_url || ''}" alt="${utils.escapeHtml(c.name)}" />
        <div class="item-text-col">
          <div class="item-title">${utils.escapeHtml(c.name)}</div>
          <div class="item-subtitle">${c.layer_count || 0} layers • ${c.state_count || 0} states</div>
        </div>
      `;
      row.addEventListener("click", async () => {
        try {
          const res = await api.manageCanvas({ action: "select", canvas_id: c.canvas_id });
          if (res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
          }
        } catch (err) {
          showToast("baker", err.message);
        }
      });
      container.appendChild(row);
    }

    if (pageInfo) {
      pageInfo.textContent = total === 0 ? "No canvases" : `Showing ${start + 1} to ${end} of ${total}`;
    }
    if (prevBtn) prevBtn.disabled = canvasPage === 0;
    if (nextBtn) nextBtn.disabled = end >= total;
  }

  function renderLayerLists() {
    const containers = [
      document.getElementById("baker-layer-list-items"),
      document.getElementById("layerify-layer-list-items")
    ];

    const layers = state.baker.layers || [];
    const bkrBadge = document.getElementById("badge-bkr-layers-total");
    const lyrBadge = document.getElementById("badge-lyr-layers-total");
    if (bkrBadge) bkrBadge.textContent = String(layers.length);
    if (lyrBadge) lyrBadge.textContent = String(layers.length);

    containers.forEach(container => {
      if (!container) return;
      container.innerHTML = "";

      layers.forEach((lyr, idx) => {
        const row = document.createElement("div");
        row.className = `list-item ${lyr.selected ? "selected" : ""}`;
        row.innerHTML = `
          <img class="item-thumb" src="${lyr.thumb_url || ''}" alt="${utils.escapeHtml(lyr.layer_name || lyr.name)}" />
          <div class="item-text-col">
            <div class="item-title">${utils.escapeHtml(lyr.layer_name || lyr.name || `Layer ${idx + 1}`)}</div>
            <div class="item-subtitle">${lyr.label || 'Unlabeled'}</div>
          </div>
          <div class="item-actions">
            <button class="icon-btn-xs btn-lyr-vis" title="Toggle layer visibility">${lyr.visible !== false ? "👀" : "🚫"}</button>
            <button class="icon-btn-xs btn-lyr-del" title="Delete layer">🗑️</button>
          </div>
        `;

        row.addEventListener("click", e => {
          if (e.target.closest(".btn-lyr-vis") || e.target.closest(".btn-lyr-del")) return;
          const multi = e.ctrlKey || e.metaKey || e.shiftKey;
          layers.forEach((l, i) => {
            if (multi) {
              if (i === idx) l.selected = !l.selected;
            } else {
              l.selected = (i === idx);
            }
          });
          window.ImageBaker.canvasBaker.drawBakerCanvas();
          renderLayerLists();
          renderLayerSettings();
        });

        row.querySelector(".btn-lyr-vis").addEventListener("click", async e => {
          e.stopPropagation();
          lyr.visible = (lyr.visible === false);
          window.ImageBaker.canvasBaker.drawBakerCanvas();
          renderLayerLists();
          await window.ImageBaker.canvasBaker.syncLayersToServer(false, "Toggled layer visibility");
        });

        row.querySelector(".btn-lyr-del").addEventListener("click", async e => {
          e.stopPropagation();
          layers.splice(idx, 1);
          window.ImageBaker.canvasBaker.drawBakerCanvas();
          renderLayerLists();
          renderLayerSettings();
          await window.ImageBaker.canvasBaker.syncLayersToServer(true, "Deleted layer");
        });

        container.appendChild(row);
      });
    });
  }

  function renderLayerSettings() {
    const banner = document.getElementById("selected-layer-banner");
    const layers = state.baker.layers || [];
    const selected = layers.filter(l => l.selected);

    if (selected.length === 0) {
      if (banner) banner.textContent = "No BaseLayer Selected";
      disableLayerSliders(true);
      return;
    }

    disableLayerSliders(false);
    const lyr = selected[0];
    if (banner) {
      banner.textContent = selected.length === 1
        ? `${lyr.layer_name || lyr.name || "Layer"} Settings`
        : `${selected.length} Layers Selected`;
    }

    setSliderVal("slider-opacity", "val-opacity", Math.round(lyr.opacity ?? 255));
    setSliderVal("slider-xpos", "val-xpos", Math.round(lyr.position ? lyr.position[0] : 0));
    setSliderVal("slider-ypos", "val-ypos", Math.round(lyr.position ? lyr.position[1] : 0));
    setSliderVal("slider-scalex", "val-scalex", Math.round((lyr.scale_x ?? 1.0) * 100), (v) => (v / 100).toFixed(2));
    setSliderVal("slider-scaley", "val-scaley", Math.round((lyr.scale_y ?? 1.0) * 100), (v) => (v / 100).toFixed(2));
    setSliderVal("slider-rotation", "val-rotation", Math.round(lyr.rotation ?? 0));
    setSliderVal("slider-edge-opacity", "val-edge-opacity", Math.round(lyr.edge_opacity ?? 255));
    setSliderVal("slider-edge-width", "val-edge-width", Math.round(lyr.edge_width ?? 1));

    const captionInput = document.getElementById("input-layer-caption");
    if (captionInput) {
      captionInput.value = lyr.caption || "";
    }
  }

  function setSliderVal(sliderId, readoutId, val, formatFn = null) {
    const slider = document.getElementById(sliderId);
    const readout = document.getElementById(readoutId);
    if (slider) slider.value = val;
    if (readout) readout.textContent = formatFn ? formatFn(val) : String(val);
  }

  function disableLayerSliders(disabled) {
    const ids = [
      "slider-opacity", "slider-xpos", "slider-ypos",
      "slider-scalex", "slider-scaley", "slider-rotation",
      "slider-edge-opacity", "slider-edge-width", "input-layer-caption"
    ];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = disabled;
    });
  }

  function bindLayerSliders() {
    const bindings = [
      {
        sliderId: "slider-opacity",
        valId: "val-opacity",
        apply: (lyr, val) => lyr.opacity = parseInt(val, 10),
      },
      {
        sliderId: "slider-xpos",
        valId: "val-xpos",
        apply: (lyr, val) => lyr.position = [parseInt(val, 10), lyr.position ? lyr.position[1] : 0],
      },
      {
        sliderId: "slider-ypos",
        valId: "val-ypos",
        apply: (lyr, val) => lyr.position = [lyr.position ? lyr.position[0] : 0, parseInt(val, 10)],
      },
      {
        sliderId: "slider-scalex",
        valId: "val-scalex",
        format: v => (v / 100).toFixed(2),
        apply: (lyr, val) => lyr.scale_x = parseFloat(val) / 100,
      },
      {
        sliderId: "slider-scaley",
        valId: "val-scaley",
        format: v => (v / 100).toFixed(2),
        apply: (lyr, val) => lyr.scale_y = parseFloat(val) / 100,
      },
      {
        sliderId: "slider-rotation",
        valId: "val-rotation",
        apply: (lyr, val) => lyr.rotation = parseInt(val, 10),
      },
      {
        sliderId: "slider-edge-opacity",
        valId: "val-edge-opacity",
        apply: (lyr, val) => lyr.edge_opacity = parseInt(val, 10),
      },
      {
        sliderId: "slider-edge-width",
        valId: "val-edge-width",
        apply: (lyr, val) => lyr.edge_width = parseInt(val, 10),
      },
    ];

    bindings.forEach(b => {
      const slider = document.getElementById(b.sliderId);
      const readout = document.getElementById(b.valId);
      if (!slider) return;

      slider.addEventListener("input", () => {
        const val = slider.value;
        if (readout) readout.textContent = b.format ? b.format(val) : val;
        const layers = state.baker.layers || [];
        layers.filter(l => l.selected).forEach(l => b.apply(l, val));
        window.ImageBaker.canvasBaker.drawBakerCanvas();
      });

      slider.addEventListener("change", async () => {
        await window.ImageBaker.canvasBaker.syncLayersToServer(true, `Updated ${b.valId}`);
      });
    });

    const captionInput = document.getElementById("input-layer-caption");
    if (captionInput) {
      captionInput.addEventListener("change", async () => {
        const val = captionInput.value.trim();
        const layers = state.baker.layers || [];
        layers.filter(l => l.selected).forEach(l => l.caption = val);
        await window.ImageBaker.canvasBaker.syncLayersToServer(true, "Updated layer caption");
      });
    }
  }

  function bindBakerActionButtons() {
    const createBtn = document.getElementById("btn-create-canvas");
    if (createBtn) {
      createBtn.addEventListener("click", () => {
        const input = document.getElementById("input-create-canvas-name");
        if (input) input.value = `Canvas ${(state.baker.canvases || []).length + 1}`;
        openModal("modal-create-canvas");
      });
    }

    const addBlankBtn = document.getElementById("btn-add-blank-layer");
    if (addBlankBtn) {
      addBlankBtn.addEventListener("click", async () => {
        showToast("baker", "Adding blank layer...");
        const res = await api.addBlankLayer("Blank Layer", "#ffffff");
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", "Added blank layer");
        }
      });
    }

    const saveStateBtn = document.getElementById("btn-save-state");
    if (saveStateBtn) {
      saveStateBtn.addEventListener("click", async () => {
        const steps = parseInt(document.getElementById("input-bake-steps")?.value || "1", 10);
        showToast("baker", "Saving state...");
        const res = await api.manageStates({ action: "save", steps });
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", res.message || "State saved");
        }
      });
    }

    const randStatesBtn = document.getElementById("btn-randomize-states");
    if (randStatesBtn) {
      randStatesBtn.addEventListener("click", async () => {
        const steps = parseInt(document.getElementById("input-bake-steps")?.value || "1", 10);
        showToast("baker", `Generating ${steps} randomized state(s)...`);
        const res = await api.manageStates({ action: "randomize", steps });
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", res.message || "States randomized");
        }
      });
    }

    const playBtn = document.getElementById("btn-play-states");
    if (playBtn) {
      playBtn.addEventListener("click", () => {
        if (state.baker.is_playing) {
          window.ImageBaker.canvasBaker.stopPlayingStates();
        } else {
          window.ImageBaker.canvasBaker.startPlayingStates();
        }
      });
    }

    const clearStatesBtn = document.getElementById("btn-clear-states");
    if (clearStatesBtn) {
      clearStatesBtn.addEventListener("click", async () => {
        if (!confirm("Clear all saved states on this canvas?")) return;
        const res = await api.manageStates({ action: "clear" });
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", "States cleared");
        }
      });
    }

    const timelineSlider = document.getElementById("slider-state-timeline");
    if (timelineSlider) {
      timelineSlider.addEventListener("input", async () => {
        const step = parseInt(timelineSlider.value, 10);
        const res = await api.manageStates({ action: "seek", step });
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
        }
      });
    }

    // Export Current State
    const exportCurrentBtn = document.getElementById("btn-export-current-state");
    if (exportCurrentBtn) {
      exportCurrentBtn.addEventListener("click", () => {
        openExportPrompt("current_local", "Export Current State", "Bake and export current canvas state.");
      });
    }

    // Export All States
    const exportStatesBtn = document.getElementById("btn-export-states");
    if (exportStatesBtn) {
      exportStatesBtn.addEventListener("click", () => {
        openExportPrompt("all_local", "Export All States", "Bake and export all saved states in the timeline.");
      });
    }

    // Annotate States (send to Layerify)
    const annotateStatesBtn = document.getElementById("btn-annotate-states");
    if (annotateStatesBtn) {
      annotateStatesBtn.addEventListener("click", async () => {
        showToast("baker", "Baking states to Layerify tab...");
        const res = await api.exportBaker("annotate_states");
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", "Transferred baked frames to Layerify tab");
        }
      });
    }

    // Group Layers
    const groupBtn = document.getElementById("btn-group-layers-baker") || document.getElementById("btn-group-layers-tool");
    if (groupBtn) {
      groupBtn.addEventListener("click", async () => {
        const res = await api.performBakerLayerAction("group");
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", res.message || "Layers grouped");
        }
      });
    }

    // Convert Geometry
    const convBtn = document.getElementById("btn-convert-ann-type");
    if (convBtn) {
      convBtn.addEventListener("click", async () => {
        const res = await api.performBakerLayerAction("convert_annotation_type");
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", res.message || "Converted geometry");
        }
      });
    }

    // Baker Undo / Redo
    const undoBtn = document.getElementById("btn-baker-undo");
    if (undoBtn) {
      undoBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        const res = await api.performBakerLayerAction("undo");
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
        }
      });
    }

    const redoBtn = document.getElementById("btn-baker-redo");
    if (redoBtn) {
      redoBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        const res = await api.performBakerLayerAction("redo");
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
        }
      });
    }

    // Predict State
    const predictStateBtn = document.getElementById("btn-predict-state");
    if (predictStateBtn) {
      predictStateBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        showToast("baker", "Baking state & running prediction...");
        const res = await api.exportBaker("predict_state");
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", "Transferred baked frame to Layerify and ran prediction");
        }
      });
    }

    // Plugin Options Dropdown
    const pluginBtn = document.getElementById("btn-plugin-options");
    const pluginMenu = document.getElementById("menu-plugin-options");
    if (pluginBtn && pluginMenu) {
      pluginBtn.addEventListener("click", e => {
        e.stopPropagation();
        pluginMenu.classList.toggle("hidden");
      });
      document.addEventListener("click", e => {
        if (!e.target.closest("#plugin-dropdown-wrap")) {
          pluginMenu.classList.add("hidden");
        }
      });
    }

    const reloadPluginsBtn = document.getElementById("btn-reload-plugins");
    if (reloadPluginsBtn) {
      reloadPluginsBtn.addEventListener("click", async () => {
        try {
          const res = await api.managePlugins({ action: "reload" });
          if (res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            showToast("baker", "Reloaded plugins");
          }
        } catch (err) {
          showToast("baker", err.message);
        }
      });
    }

    const clearPluginsBtn = document.getElementById("btn-clear-plugins");
    if (clearPluginsBtn) {
      clearPluginsBtn.addEventListener("click", async () => {
        try {
          const res = await api.managePlugins({ action: "clear" });
          if (res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            showToast("baker", "Cleared plugin selection");
          }
        } catch (err) {
          showToast("baker", err.message);
        }
      });
    }

    // Draw / Erase Modes and Color
    const drawModeBtn = document.getElementById("btn-draw-mode");
    const eraseModeBtn = document.getElementById("btn-erase-mode");
    if (drawModeBtn) {
      drawModeBtn.addEventListener("click", e => {
        e.currentTarget.blur();
        bkrView.drawingMode = !bkrView.drawingMode;
        if (bkrView.drawingMode) bkrView.eraseMode = false;
        drawModeBtn.classList.toggle("active", bkrView.drawingMode);
        if (eraseModeBtn) eraseModeBtn.classList.toggle("active", bkrView.eraseMode);
        window.ImageBaker.canvasBaker.drawBakerCanvas();
      });
    }
    if (eraseModeBtn) {
      eraseModeBtn.addEventListener("click", e => {
        e.currentTarget.blur();
        bkrView.eraseMode = !bkrView.eraseMode;
        if (bkrView.eraseMode) bkrView.drawingMode = false;
        eraseModeBtn.classList.toggle("active", bkrView.eraseMode);
        if (drawModeBtn) drawModeBtn.classList.toggle("active", bkrView.drawingMode);
        window.ImageBaker.canvasBaker.drawBakerCanvas();
      });
    }

    const brushColorBtn = document.getElementById("btn-brush-color");
    const brushColorPicker = document.getElementById("input-brush-color-picker");
    if (brushColorBtn && brushColorPicker) {
      brushColorBtn.addEventListener("click", e => {
        e.currentTarget.blur();
        brushColorPicker.click();
      });
      brushColorPicker.addEventListener("input", e => {
        bkrView.brushColor = e.target.value;
      });
    }
  }

  function renderPluginDropdown() {
    const listEl = document.getElementById("plugin-checkbox-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    const available = state.baker.available_plugins || [];
    const selectedSet = new Set(state.baker.selected_plugins || []);

    if (available.length === 0) {
      const empty = document.createElement("div");
      empty.className = "item-subtitle";
      empty.style.padding = "4px 8px";
      empty.textContent = "No plugins found";
      listEl.appendChild(empty);
      return;
    }

    available.forEach(pName => {
      const lbl = document.createElement("label");
      lbl.className = "dropdown-item";
      lbl.innerHTML = `
        <input type="checkbox" value="${utils.escapeHtml(pName)}" ${selectedSet.has(pName) ? "checked" : ""} />
        <span>${utils.escapeHtml(pName)}</span>
      `;
      lbl.querySelector("input").addEventListener("change", async () => {
        const checked = Array.from(
          listEl.querySelectorAll("input[type='checkbox']:checked")
        ).map(el => el.value);
        try {
          const res = await api.managePlugins({ action: "set", plugins: checked });
          if (res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
          }
        } catch (err) {
          showToast("baker", err.message);
        }
      });
      listEl.appendChild(lbl);
    });
  }

  function openExportPrompt(mode, title, desc) {
    const titleEl = document.getElementById("baker-export-prompt-title");
    const descEl = document.getElementById("baker-export-prompt-desc");
    if (titleEl) titleEl.textContent = title;
    if (descEl) descEl.textContent = desc;

    const confirmBtn = document.getElementById("btn-confirm-baker-export");
    if (confirmBtn) {
      confirmBtn.onclick = async () => {
        const fmt = document.getElementById("select-baker-export-format")?.value || "default";
        const download = Boolean(document.getElementById("cb-baker-download-zip")?.checked);
        closeAllModals();
        showToast("baker", `Exporting ${mode} (${fmt.toUpperCase()})...`);
        const res = await api.exportBaker(mode, fmt);
        if (res.ok) {
          showToast("baker", res.message || "Export complete");
          if (download && res.download_url) {
            window.location.href = res.download_url;
          }
        }
      };
    }
    openModal("modal-baker-export-prompt");
  }

  function bindModals() {
    const confirmCreateCanvas = document.getElementById("btn-confirm-create-canvas");
    if (confirmCreateCanvas) {
      confirmCreateCanvas.addEventListener("click", async () => {
        const name = document.getElementById("input-create-canvas-name")?.value.trim() || "Canvas";
        closeAllModals();
        const res = await api.manageCanvas({ action: "create", name });
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("baker", `Created canvas "${name}"`);
        }
      });
    }
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.uiBaker = {
    initBakerUI,
    renderCanvasList,
    renderLayerLists,
    renderLayerSettings,
    renderPluginDropdown,
  };
})(window);
