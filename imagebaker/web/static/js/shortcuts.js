/**
 * ImageBaker Web - Keyboard Shortcuts Manager
 */
(function(window) {
  "use strict";

  const { state, lyrView, isModalOpen, isTypingInTextField } = window.ImageBaker;

  function initShortcuts() {
    window.addEventListener("keydown", async e => {
      // Don't trigger shortcuts if user is typing into an input field or a modal is open
      if (isTypingInTextField(e.target) || isModalOpen()) {
        if (e.key === "Escape" && isModalOpen()) {
          window.ImageBaker.closeAllModals();
        }
        return;
      }

      const isMac = navigator.platform.toUpperCase().indexOf("MAC") >= 0;
      const cmdOrCtrl = isMac ? e.metaKey : e.ctrlKey;

      // Ctrl+Z: Undo
      if (cmdOrCtrl && !e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (state.active_tab === "Layerify") {
          window.ImageBaker.canvasLayerify.performLayerifyUndo();
        }
        return;
      }

      // Ctrl+Y or Ctrl+Shift+Z: Redo
      if ((cmdOrCtrl && e.key.toLowerCase() === "y") || (cmdOrCtrl && e.shiftKey && e.key.toLowerCase() === "z")) {
        e.preventDefault();
        if (state.active_tab === "Layerify") {
          window.ImageBaker.canvasLayerify.performLayerifyRedo();
        }
        return;
      }

      // Ctrl+S: Save Baker State
      if (cmdOrCtrl && e.key.toLowerCase() === "s") {
        e.preventDefault();
        const saveStateBtn = document.getElementById("btn-save-state");
        if (saveStateBtn) saveStateBtn.click();
        return;
      }

      // Single Key Tool Hotkeys (when active tab is Layerify)
      if (!cmdOrCtrl && !e.altKey) {
        const key = e.key.toLowerCase();
        switch (key) {
          case "v":
          case "escape":
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Idle");
            break;
          case "e":
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Rectangle");
            break;
          case "w":
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Polygon");
            break;
          case "q":
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Point");
            break;
          case "b":
            e.preventDefault();
            window.ImageBaker.canvasLayerify.setLayerifyMode("Brush");
            break;
          case "p":
            e.preventDefault();
            window.ImageBaker.uiLayerify.runModelPrediction();
            break;
          case "l":
            e.preventDefault();
            window.ImageBaker.uiLayerify.runLayerifyAll();
            break;
          case "f":
            e.preventDefault();
            if (state.active_tab === "Layerify") {
              window.ImageBaker.canvasLayerify.fitLayerifyImageIfNeeded();
            } else if (state.active_tab === "Baker") {
              window.ImageBaker.canvasBaker.fitBakerLayersIfNeeded(true);
            }
            break;
          case "g":
            e.preventDefault();
            const gridBtn = document.getElementById("btn-top-grid");
            if (gridBtn) gridBtn.click();
            break;
          case "arrowup":
          case "w":
            if (e.ctrlKey || e.metaKey) {
              e.preventDefault();
              if (state.active_tab === "Baker") {
                const sel = (state.baker.layers || []).find(l => l.selected);
                if (sel) {
                  api.reorderBakerLayers({ direction: "up", layer_id: sel.layer_id }).then(res => {
                    if (res && res.state) window.ImageBaker.applyServerState(res.state);
                  });
                }
              }
            }
            break;
          case "arrowdown":
          case "s":
            if (e.ctrlKey || e.metaKey) {
              e.preventDefault();
              if (state.active_tab === "Baker") {
                const sel = (state.baker.layers || []).find(l => l.selected);
                if (sel) {
                  api.reorderBakerLayers({ direction: "down", layer_id: sel.layer_id }).then(res => {
                    if (res && res.state) window.ImageBaker.applyServerState(res.state);
                  });
                }
              }
            }
            break;
          case "c":
            e.preventDefault();
            if (state.active_tab === "Layerify") {
              const selIdx = (state.layerify.annotations || []).findIndex(a => a.selected);
              if (selIdx >= 0) {
                window.ImageBaker.uiLayerify.openEditCaptionModal(selIdx);
              }
            }
            break;
          case "delete":
          case "backspace":
            e.preventDefault();
            if (state.active_tab === "Layerify") {
              const annotations = state.layerify.annotations || [];
              const selIndices = annotations.map((a, i) => a.selected ? i : -1).filter(i => i >= 0);
              if (selIndices.length > 0) {
                state.layerify.annotations = annotations.filter(a => !a.selected);
                window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
                window.ImageBaker.uiLayerify.renderAnnotationList();
                window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, "Deleted annotation(s)");
              }
            } else if (state.active_tab === "Baker") {
              const layers = state.baker?.layers || [];
              const sel = layers.find(l => l.selected);
              if (sel) {
                api.performBakerLayerAction("delete", { layer_id: sel.layer_id }).then(res => {
                  if (res && res.state) {
                    window.ImageBaker.applyServerState(res.state);
                  }
                }).catch(err => {
                  console.error("Failed to delete selected layer:", err);
                });
              }
            }
            break;
        }

        // Digit hotkeys 0-9 to select class label
        if (/^[0-9]$/.test(e.key)) {
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
  };
})(window);

