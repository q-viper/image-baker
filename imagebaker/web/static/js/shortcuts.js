/**
 * ImageBaker Web - Keyboard Shortcuts Manager
 */
(function(window) {
  "use strict";

  const { state, lyrView, DEFAULT_SHORTCUTS, isModalOpen, isTypingInTextField, showToast, openModal, closeAllModals } = window.ImageBaker;
  const api = window.ImageBaker.api;

  const SHORTCUT_ITEMS = [
    { action: "select", label: "Select / Idle Mode" },
    { action: "polygon", label: "Polygon Mode" },
    { action: "point", label: "Point Mode" },
    { action: "rectangle", label: "Rectangle Mode" },
    { action: "pan", label: "Pan Mode" },
    { action: "brush", label: "Brush Mode" },
    { action: "predict", label: "Predict (AI Model)" },
    { action: "cycle_model", label: "Cycle AI Model" },
    { action: "layerify", label: "Extract / Layerify" },
    { action: "caption", label: "Edit Caption" },
    { action: "toggle_visibility", label: "Show / Hide Selection" },
    { action: "fit_view", label: "Fit Viewport" },
    { action: "toggle_grid", label: "Toggle Gridlines" },
    { action: "prev_item", label: "Previous Image / Canvas" },
    { action: "next_item", label: "Next Image / Canvas" },
  ];

  let draftShortcuts = {};
  let listeningAction = null;

  function getShortcuts() {
    return {
      ...(DEFAULT_SHORTCUTS || {}),
      ...(state.shortcuts || {}),
    };
  }

  function formatKeyLabel(k) {
    return String(k || "").toUpperCase();
  }

  function applyShortcutLabelsToUI() {
    const sc = getShortcuts();
    document.querySelectorAll("[data-shortcut-kbd]").forEach(el => {
      const action = el.getAttribute("data-shortcut-kbd");
      if (action && sc[action]) {
        el.textContent = formatKeyLabel(sc[action]);
      }
    });
    document.querySelectorAll("[data-shortcut-help]").forEach(el => {
      const action = el.getAttribute("data-shortcut-help");
      if (action && sc[action]) {
        el.textContent = formatKeyLabel(sc[action]);
      }
    });

    const titleMap = {
      "strip-mode-idle": `Select / Move / Resize Mode (${formatKeyLabel(sc.select)} or Esc or Right-Click)`,
      "strip-mode-rectangle": `Rectangle Mode (${formatKeyLabel(sc.rectangle)})`,
      "strip-mode-polygon": `Polygon Mode (${formatKeyLabel(sc.polygon)}) — Enter, Double-Click, or click 1st point to close`,
      "strip-mode-point": `Point Mode (${formatKeyLabel(sc.point)})`,
      "strip-mode-brush": `Brush Segmentation Mask Mode (${formatKeyLabel(sc.brush)})`,
      "strip-mode-pan": `Pan Canvas (${formatKeyLabel(sc.pan)} or Ctrl + Drag)`,
      "strip-btn-caption": `Edit Selected Region Caption / Label (${formatKeyLabel(sc.caption)})`,
      "strip-btn-vis": `Toggle Selected Region Visibility (${formatKeyLabel(sc.toggle_visibility)})`,
      "btn-predict": `Run model prediction on the current image (${formatKeyLabel(sc.predict)}).`,
      "select-model": `Select a model for prediction (${formatKeyLabel(sc.cycle_model)} to cycle).`,
      "btn-layerify-selected": `Extract selected visible annotations into Baker layers (${formatKeyLabel(sc.layerify)}).`,
      "btn-zoom-fit": `Fit to View (${formatKeyLabel(sc.fit_view)})`,
      "btn-top-grid": `Toggle Gridlines (${formatKeyLabel(sc.toggle_grid)})`,
      "btn-header-prev": `Previous Image / Canvas (${formatKeyLabel(sc.prev_item)})`,
      "btn-header-next": `Next Image / Canvas (${formatKeyLabel(sc.next_item)})`,
    };
    Object.entries(titleMap).forEach(([id, title]) => {
      const el = document.getElementById(id);
      if (el) el.title = title;
    });
    const predictBtn = document.getElementById("btn-predict");
    if (predictBtn) {
      predictBtn.textContent = `🔮 Predict (${formatKeyLabel(sc.predict)})`;
    }
  }

  function renderShortcutsModalList() {
    const container = document.getElementById("shortcuts-config-list");
    if (!container) return;
    container.innerHTML = "";
    SHORTCUT_ITEMS.forEach(item => {
      const row = document.createElement("div");
      row.className = "shortcut-config-row";
      const lbl = document.createElement("span");
      lbl.className = "shortcut-config-label";
      lbl.textContent = item.label;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "shortcut-key-btn" + (listeningAction === item.action ? " listening" : "");
      btn.setAttribute("data-config-action", item.action);
      btn.textContent = listeningAction === item.action ? "..." : formatKeyLabel(draftShortcuts[item.action]);
      btn.title = "Click and press a key to rebind";
      btn.addEventListener("click", () => {
        listeningAction = listeningAction === item.action ? null : item.action;
        renderShortcutsModalList();
      });

      row.appendChild(lbl);
      row.appendChild(btn);
      container.appendChild(row);
    });
  }

  function openShortcutsModal() {
    draftShortcuts = { ...getShortcuts() };
    listeningAction = null;
    renderShortcutsModalList();
    openModal("modal-configure-shortcuts");
  }

  function initShortcutsModal() {
    const saveBtn = document.getElementById("btn-save-shortcuts");
    const resetBtn = document.getElementById("btn-reset-shortcuts");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        listeningAction = null;
        try {
          const res = await api.updateSettings({ shortcuts: draftShortcuts });
          if (res && res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            closeAllModals();
            showToast(state.active_tab === "Baker" ? "baker" : "layerify", "Shortcuts saved");
          }
        } catch (err) {
          showToast(state.active_tab === "Baker" ? "baker" : "layerify", "Failed to save shortcuts: " + err.message);
        }
      });
    }
    if (resetBtn) {
      resetBtn.addEventListener("click", async () => {
        listeningAction = null;
        try {
          const res = await api.updateSettings({ reset_shortcuts: true });
          if (res && res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            draftShortcuts = { ...getShortcuts() };
            renderShortcutsModalList();
            showToast(state.active_tab === "Baker" ? "baker" : "layerify", "Shortcuts reset to defaults");
          }
        } catch (err) {
          showToast(state.active_tab === "Baker" ? "baker" : "layerify", "Failed to reset shortcuts: " + err.message);
        }
      });
    }
  }

  function initShortcuts() {
    initShortcutsModal();
    applyShortcutLabelsToUI();

    window.addEventListener("keydown", async e => {
      // Capture key when user is rebinding a shortcut inside the Configure Shortcuts modal
      if (listeningAction) {
        const modal = document.getElementById("modal-configure-shortcuts");
        if (modal && !modal.classList.contains("hidden")) {
          e.preventDefault();
          e.stopPropagation();
          if (e.key === "Escape") {
            listeningAction = null;
            renderShortcutsModalList();
            return;
          }
          if (!e.ctrlKey && !e.metaKey && !e.altKey && e.key && e.key.length === 1) {
            const newKey = e.key.toLowerCase();
            const prevKey = draftShortcuts[listeningAction];
            // Swap if another action already holds this key
            for (const item of SHORTCUT_ITEMS) {
              if (item.action !== listeningAction && draftShortcuts[item.action] === newKey) {
                draftShortcuts[item.action] = prevKey;
                break;
              }
            }
            draftShortcuts[listeningAction] = newKey;
            listeningAction = null;
            renderShortcutsModalList();
          }
          return;
        }
        listeningAction = null;
      }

      // Don't trigger shortcuts if user is typing into an input field or a modal is open
      if (isTypingInTextField(e.target) || isModalOpen()) {
        if (e.key === "Escape" && isModalOpen()) {
          window.ImageBaker.closeAllModals();
        }
        return;
      }

      const isMac = navigator.platform.toUpperCase().indexOf("MAC") >= 0;
      const cmdOrCtrl = isMac ? e.metaKey : e.ctrlKey;
      const key = e.key.toLowerCase();

      // =======================================================================
      // Ctrl / Cmd Shortcuts
      // =======================================================================
      if (cmdOrCtrl) {
        // 1. Copy: Ctrl + C
        if (key === "c") {
          e.preventDefault();
          if (state.active_tab === "Layerify") {
            try {
              const sel = (state.layerify?.annotations || []).filter(a => a.selected);
              if (sel.length === 0) {
                showToast("layerify", "No annotation selected to copy.");
                return;
              }
              const res = await api.performAnnotationAction("copy", {
                annotation_ids: sel.map(a => a.annotation_id)
              });
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("layerify", res.message || "Copied annotation(s)");
              }
            } catch (err) {
              console.error("Copy annotation error:", err);
            }
          } else if (state.active_tab === "Baker") {
            try {
              const sel = (state.baker?.layers || []).filter(l => l.selected);
              if (sel.length === 0) {
                showToast("baker", "No layer selected to copy.");
                return;
              }
              const res = await api.performBakerLayerAction("copy", {
                layer_ids: sel.map(l => l.layer_id)
              });
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("baker", res.message || "Copied layer(s)");
              }
            } catch (err) {
              console.error("Copy layer error:", err);
            }
          }
          return;
        }

        // 2. Paste: Ctrl + V
        if (key === "v") {
          e.preventDefault();
          if (state.active_tab === "Layerify") {
            try {
              const res = await api.performAnnotationAction("paste");
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("layerify", res.message || "Pasted annotation(s)");
              }
            } catch (err) {
              console.error("Paste annotation error:", err);
            }
          } else if (state.active_tab === "Baker") {
            try {
              const res = await api.performBakerLayerAction("paste");
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("baker", res.message || "Pasted layer(s)");
              }
            } catch (err) {
              console.error("Paste layer error:", err);
            }
          }
          return;
        }

        // 3. Undo: Ctrl + Z
        if (key === "z" && !e.shiftKey) {
          e.preventDefault();
          if (state.active_tab === "Layerify") {
            window.ImageBaker.canvasLayerify.performLayerifyUndo();
          } else if (state.active_tab === "Baker") {
            try {
              const res = await api.performBakerLayerAction("undo");
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("baker", res.message || "Undo");
              }
            } catch (err) {
              console.error("Undo error:", err);
            }
          }
          return;
        }

        // 4. Redo: Ctrl + Y or Ctrl + Shift + Z
        if (key === "y" || (e.shiftKey && key === "z")) {
          e.preventDefault();
          if (state.active_tab === "Layerify") {
            window.ImageBaker.canvasLayerify.performLayerifyRedo();
          } else if (state.active_tab === "Baker") {
            try {
              const res = await api.performBakerLayerAction("redo");
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("baker", res.message || "Redo");
              }
            } catch (err) {
              console.error("Redo error:", err);
            }
          }
          return;
        }

        // 5. Select All: Ctrl + A
        if (key === "a") {
          e.preventDefault();
          if (state.active_tab === "Layerify") {
            const annotations = state.layerify?.annotations || [];
            annotations.forEach(a => a.selected = true);
            window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
            window.ImageBaker.uiLayerify.renderAnnotationList();
            await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(false, "Selected all annotations");
          } else if (state.active_tab === "Baker") {
            const layers = state.baker?.layers || [];
            layers.forEach(l => l.selected = true);
            window.ImageBaker.canvasBaker.drawBakerCanvas();
            window.ImageBaker.uiBaker.renderLayerLists();
            window.ImageBaker.uiBaker.renderLayerSettings();
            await window.ImageBaker.canvasBaker.syncLayersToServer(false, "Selected all layers");
          }
          return;
        }

        // 6. Save: Ctrl + S
        if (key === "s" && !e.shiftKey) {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            const saveStateBtn = document.getElementById("btn-save-state");
            if (saveStateBtn) saveStateBtn.click();
          } else if (state.active_tab === "Layerify") {
            const saveAnnBtn = document.getElementById("btn-save-annotations");
            if (saveAnnBtn) saveAnnBtn.click();
          }
          return;
        }

        // 7. Group / Ungroup Layers: Ctrl + G
        if (key === "g") {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            try {
              const selected = (state.baker?.layers || []).filter(l => l.selected);
              const selIds = selected.map(l => l.layer_id);
              const isGroupedSelected = selected.length === 1 && (selected[0].is_group || (selected[0].grouped_layers && selected[0].grouped_layers.length >= 2));
              const action = isGroupedSelected ? "ungroup" : "group";
              const res = await api.performBakerLayerAction(action, { layer_ids: selIds });
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("baker", res.message || (action === "ungroup" ? "Layer ungrouped" : "Layers grouped"));
              } else if (res && !res.ok) {
                showToast("baker", res.message || `Failed to ${action} layers`);
              }
            } catch (err) {
              console.error("Group/Ungroup layers error:", err);
            }
          }
          return;
        }

        // 8. Add Blank Layer: Ctrl + N
        if (key === "n") {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            try {
              const res = await api.addBlankLayer("Blank Layer", "#ffffff");
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("baker", "Added blank layer");
              }
            } catch (err) {
              console.error("Add blank layer error:", err);
            }
          }
          return;
        }

        // 9. Draw Mode: Ctrl + D
        if (key === "d") {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            const drawBtn = document.getElementById("btn-draw-mode");
            if (drawBtn) drawBtn.click();
          }
          return;
        }

        // 10. Erase Mode: Ctrl + E
        if (key === "e") {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            const eraseBtn = document.getElementById("btn-erase-mode");
            if (eraseBtn) eraseBtn.click();
          }
          return;
        }

        // 11. Reorder Layer: Ctrl + Up / W or Ctrl + Down
        if (key === "arrowup" || key === "w") {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            const sel = (state.baker.layers || []).find(l => l.selected);
            if (sel) {
              api.reorderBakerLayers({ direction: "up", layer_id: sel.layer_id }).then(res => {
                if (res && res.state) window.ImageBaker.applyServerState(res.state);
              });
            }
          }
          return;
        }
        if (key === "arrowdown") {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            const sel = (state.baker.layers || []).find(l => l.selected);
            if (sel) {
              api.reorderBakerLayers({ direction: "down", layer_id: sel.layer_id }).then(res => {
                if (res && res.state) window.ImageBaker.applyServerState(res.state);
              });
            }
          }
          return;
        }

        return;
      }

      // =======================================================================
      // Single Key & Shift Shortcuts (when not holding Ctrl/Cmd)
      // Strictly isolated by active tab (Layerify vs Baker)
      // =======================================================================
      if (!cmdOrCtrl && !e.altKey) {
        const sc = getShortcuts();

        if (key === "escape") {
          if (state.active_tab === "Layerify") {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Idle");
          } else if (state.active_tab === "Baker") {
            e.preventDefault();
            const bkrView = window.ImageBaker.bkrView;
            if (bkrView && bkrView.isPlaying) {
              window.ImageBaker.canvasBaker.stopPlayingStates();
            } else if (bkrView && (bkrView.drawingMode || bkrView.eraseMode)) {
              bkrView.drawingMode = false;
              bkrView.eraseMode = false;
              const drawBtn = document.getElementById("btn-draw-mode");
              const eraseBtn = document.getElementById("btn-erase-mode");
              if (drawBtn) drawBtn.classList.remove("active");
              if (eraseBtn) eraseBtn.classList.remove("active");
              window.ImageBaker.canvasBaker.drawBakerCanvas();
            } else {
              const layers = state.baker?.layers || [];
              if (layers.some(l => l.selected)) {
                layers.forEach(l => l.selected = false);
                window.ImageBaker.canvasBaker.drawBakerCanvas();
                window.ImageBaker.uiBaker.renderLayerLists();
                window.ImageBaker.uiBaker.renderLayerSettings();
                window.ImageBaker.canvasBaker.syncLayersToServer(false, "Deselected all layers");
              }
            }
          }
          return;
        }

        if (key === "enter") {
          if (state.active_tab === "Layerify" && lyrView.activeMode === "Polygon" && lyrView.activePolyDraft && lyrView.activePolyDraft.length >= 3) {
            e.preventDefault();
            const finishBtn = document.getElementById("btn-finish-polygon");
            if (finishBtn) finishBtn.click();
          }
          return;
        }

        if (key === " ") {
          if (state.active_tab === "Baker") {
            e.preventDefault();
            const playBtn = document.getElementById("btn-play-states");
            if (playBtn) playBtn.click();
          }
          return;
        }

        // Configurable Layerify tool mode shortcuts
        if (state.active_tab === "Layerify") {
          if (key === sc.select) {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Idle");
            return;
          }
          if (key === sc.rectangle) {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Rectangle");
            return;
          }
          if (key === sc.polygon) {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Polygon");
            return;
          }
          if (key === sc.point) {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Point");
            return;
          }
          if (key === sc.brush) {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Brush");
            return;
          }
          if (key === sc.pan) {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Pan");
            return;
          }
          if (key === sc.layerify) {
            e.preventDefault();
            const selAnns = (state.layerify?.annotations || []).filter(a => a.selected && a.visible);
            if (selAnns.length > 0) {
              window.ImageBaker.uiLayerify.runLayerifySelected(selAnns.map(a => a.annotation_id));
            } else {
              window.ImageBaker.uiLayerify.runLayerifyAll();
            }
            return;
          }
          if (key === sc.cycle_model) {
            e.preventDefault();
            window.ImageBaker.uiLayerify.cycleModel();
            return;
          }
          if (key === sc.predict) {
            e.preventDefault();
            window.ImageBaker.uiLayerify.runModelPrediction();
            return;
          }
        } else if (state.active_tab === "Baker") {
          if (key === "e") {
            e.preventDefault();
            const eraseBtn = document.getElementById("btn-erase-mode");
            if (eraseBtn) eraseBtn.click();
            return;
          }
          if (key === "d") {
            e.preventDefault();
            const drawBtn = document.getElementById("btn-draw-mode");
            if (drawBtn) drawBtn.click();
            return;
          }
          if (key === "w") {
            e.preventDefault();
            const sel = (state.baker?.layers || []).find(l => l.selected);
            if (sel) {
              api.reorderBakerLayers({ direction: "up", layer_id: sel.layer_id }).then(res => {
                if (res && res.state) window.ImageBaker.applyServerState(res.state);
              });
            }
            return;
          }
          if (key === "s") {
            e.preventDefault();
            const sel = (state.baker?.layers || []).find(l => l.selected);
            if (sel) {
              api.reorderBakerLayers({ direction: "down", layer_id: sel.layer_id }).then(res => {
                if (res && res.state) window.ImageBaker.applyServerState(res.state);
              });
            }
            return;
          }
          if (key === "r") {
            e.preventDefault();
            const layers = state.baker?.layers || [];
            const sel = layers.filter(l => l.selected);
            if (sel.length > 0) {
              const delta = e.shiftKey ? -5 : 5;
              sel.forEach(l => {
                l.rotation = (((l.rotation || 0) + delta) % 360 + 360) % 360;
              });
              window.ImageBaker.canvasBaker.drawBakerCanvas();
              window.ImageBaker.uiBaker.renderLayerSettings();
              window.ImageBaker.canvasBaker.syncLayersToServer(true, `Rotated ${sel.length} layer(s) by ${delta}°`);
            }
            return;
          }
          if (key === sc.predict) {
            e.preventDefault();
            const predictStateBtn = document.getElementById("btn-predict-state");
            if (predictStateBtn) predictStateBtn.click();
            return;
          }
        }

        // Shared configurable shortcuts (Navigation, Fit, Grid, Visibility, Caption)
        if (key === sc.prev_item) {
          e.preventDefault();
          if (window.ImageBaker.stepHeaderNavigation) {
            window.ImageBaker.stepHeaderNavigation(-1);
          }
          return;
        }
        if (key === sc.next_item) {
          e.preventDefault();
          if (window.ImageBaker.stepHeaderNavigation) {
            window.ImageBaker.stepHeaderNavigation(1);
          }
          return;
        }
        if (key === sc.fit_view) {
          if (state.active_tab === "Layerify") {
            e.preventDefault();
            window.ImageBaker.canvasLayerify.fitLayerifyImageIfNeeded();
          } else if (state.active_tab === "Baker") {
            e.preventDefault();
            window.ImageBaker.canvasBaker.fitBakerLayersIfNeeded(true);
          }
          return;
        }
        if (key === sc.toggle_grid) {
          if (state.active_tab === "Layerify" || state.active_tab === "Baker") {
            e.preventDefault();
            const gridBtn = document.getElementById("btn-top-grid");
            if (gridBtn) gridBtn.click();
          }
          return;
        }
        if (key === sc.toggle_visibility) {
          e.preventDefault();
          if (state.active_tab === "Layerify") {
            const annotations = state.layerify?.annotations || [];
            const sel = annotations.filter(a => a.selected);
            const targets = sel.length > 0 ? sel : annotations;
            if (targets.length > 0) {
              const anyVis = targets.some(a => a.visible !== false);
              targets.forEach(a => a.visible = !anyVis);
              window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
              window.ImageBaker.uiLayerify.renderAnnotationList();
              window.ImageBaker.canvasLayerify.syncAnnotationsToServer(false, "Toggled visibility");
            }
          } else if (state.active_tab === "Baker") {
            const layers = state.baker?.layers || [];
            const sel = layers.filter(l => l.selected);
            const targets = sel.length > 0 ? sel : layers;
            if (targets.length > 0) {
              const anyVis = targets.some(l => l.visible !== false);
              targets.forEach(l => l.visible = !anyVis);
              window.ImageBaker.canvasBaker.drawBakerCanvas();
              window.ImageBaker.uiBaker.renderLayerLists();
              window.ImageBaker.canvasBaker.syncLayersToServer(false, "Toggled layer visibility");
            }
          }
          return;
        }
        if (key === sc.caption) {
          e.preventDefault();
          if (state.active_tab === "Layerify") {
            const selIdx = (state.layerify.annotations || []).findIndex(a => a.selected);
            if (selIdx >= 0) {
              window.ImageBaker.uiLayerify.openEditCaptionModal(selIdx);
            }
          } else if (state.active_tab === "Baker") {
            const capInput = document.getElementById("input-layer-caption");
            if (capInput && !capInput.disabled) {
              capInput.focus();
              capInput.select();
            }
          }
          return;
        }

        switch (key) {
          // Arrow keys nudge
          case "arrowleft":
          case "arrowright":
          case "arrowup":
          case "arrowdown":
            if (state.active_tab === "Layerify") {
              const annotations = state.layerify?.annotations || [];
              const selected = annotations.filter(a => a.selected);
              if (selected.length > 0) {
                e.preventDefault();
                const step = e.shiftKey ? 10 : 1;
                const dx = (key === "arrowleft" ? -step : key === "arrowright" ? step : 0);
                const dy = (key === "arrowup" ? -step : key === "arrowdown" ? step : 0);
                const selVtx = window.ImageBaker.lyrView?.selectedPolyVertex;
                const vtxTarget = selVtx && selected.length === 1 && selected[0].annotation_id === selVtx.annId
                  && selected[0].polygon && selected[0].polygon[selVtx.pointIdx]
                  ? selected[0]
                  : null;
                if (vtxTarget) {
                  const pt = vtxTarget.polygon[selVtx.pointIdx];
                  vtxTarget.polygon[selVtx.pointIdx] = [pt[0] + dx, pt[1] + dy];
                  if (vtxTarget.rectangle && vtxTarget.polygon.length >= 3) {
                    const xs = vtxTarget.polygon.map(p => p[0]);
                    const ys = vtxTarget.polygon.map(p => p[1]);
                    vtxTarget.rectangle = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
                  }
                  window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
                  window.ImageBaker.uiLayerify.renderAnnotationList();
                  window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, "Nudged polygon vertex");
                } else {
                  selected.forEach(a => {
                    if (a.rectangle && a.rectangle.length === 4) {
                      a.rectangle = [
                        a.rectangle[0] + dx,
                        a.rectangle[1] + dy,
                        a.rectangle[2] + dx,
                        a.rectangle[3] + dy
                      ];
                    }
                    if (a.polygon) {
                      a.polygon = a.polygon.map(pt => [pt[0] + dx, pt[1] + dy]);
                    }
                    if (a.points) {
                      a.points = a.points.map(pt => [pt[0] + dx, pt[1] + dy]);
                    }
                  });
                  window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
                  window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, "Nudged annotation");
                }
              }
            } else if (state.active_tab === "Baker") {
              const layers = state.baker?.layers || [];
              const selected = layers.filter(l => l.selected);
              if (selected.length > 0) {
                e.preventDefault();
                const step = e.shiftKey ? 20 : 1;
                const dx = (key === "arrowleft" ? -step : key === "arrowright" ? step : 0);
                const dy = (key === "arrowup" ? -step : key === "arrowdown" ? step : 0);
                selected.forEach(l => {
                  l.position = [
                    (l.position ? l.position[0] : 0) + dx,
                    (l.position ? l.position[1] : 0) + dy
                  ];
                });
                window.ImageBaker.canvasBaker.drawBakerCanvas();
                window.ImageBaker.uiBaker.renderLayerSettings();
                window.ImageBaker.canvasBaker.syncLayersToServer(true, "Nudged layer");
              }
            }
            break;

          // Delete / Backspace
          case "delete":
          case "backspace":
            e.preventDefault();
            if (state.active_tab === "Layerify") {
              const annotations = state.layerify.annotations || [];
              const sel = annotations.filter(a => a.selected);
              const selVtx = window.ImageBaker.lyrView?.selectedPolyVertex;
              if (
                sel.length === 1 &&
                selVtx &&
                sel[0].annotation_id === selVtx.annId &&
                sel[0].polygon &&
                sel[0].polygon[selVtx.pointIdx]
              ) {
                if (sel[0].polygon.length > 3) {
                  sel[0].polygon.splice(selVtx.pointIdx, 1);
                  const xs = sel[0].polygon.map(p => p[0]);
                  const ys = sel[0].polygon.map(p => p[1]);
                  sel[0].rectangle = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
                  window.ImageBaker.lyrView.selectedPolyVertex = {
                    annId: sel[0].annotation_id,
                    pointIdx: Math.min(selVtx.pointIdx, sel[0].polygon.length - 1),
                  };
                  window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
                  window.ImageBaker.uiLayerify.renderAnnotationList();
                  window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, "Removed selected polygon vertex");
                  showToast("layerify", "Removed polygon vertex");
                } else {
                  showToast("layerify", "Polygon must have at least 3 points");
                }
                break;
              }
              if (sel.length > 0) {
                window.ImageBaker.lyrView.selectedPolyVertex = null;
                state.layerify.annotations = annotations.filter(a => !a.selected);
                window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
                window.ImageBaker.uiLayerify.renderAnnotationList();
                const selIds = sel.map(a => a.annotation_id);
                api.performAnnotationAction("delete", { annotation_ids: selIds }).then(res => {
                  if (res && res.state) {
                    window.ImageBaker.applyServerState(res.state);
                  }
                }).catch(() => {
                  window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, "Deleted annotation(s)");
                });
              }
            } else if (state.active_tab === "Baker") {
              const layers = state.baker?.layers || [];
              const sel = layers.filter(l => l.selected);
              if (sel.length > 0) {
                state.baker.layers = layers.filter(l => !l.selected);
                window.ImageBaker.canvasBaker.drawBakerCanvas();
                window.ImageBaker.uiBaker.renderLayerLists();
                window.ImageBaker.uiBaker.renderLayerSettings();
                const selIds = sel.map(l => l.layer_id);
                api.performBakerLayerAction("delete", { layer_ids: selIds }).then(res => {
                  if (res && res.state) {
                    window.ImageBaker.applyServerState(res.state);
                  }
                }).catch(err => {
                  console.error("Failed to delete selected layers:", err);
                });
              }
            }
            break;
        }

        // Digit hotkeys 0-9 to select class label (ONLY on Layerify tab)
        if (state.active_tab === "Layerify" && /^[0-9]$/.test(e.key)) {
          const digit = parseInt(e.key, 10);
          const labels = state.layerify.labels || [];
          if (digit >= 0 && digit < labels.length) {
            e.preventDefault();
            window.ImageBaker.uiLayerify.selectLabelAndMaybeAssign(labels[digit].name);
          }
        }
      }
    });
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.shortcuts = {
    initShortcuts,
    getShortcuts,
    applyShortcutLabelsToUI,
    openShortcutsModal,
  };
})(window);

