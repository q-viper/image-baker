/**
 * ImageBaker Web - Keyboard Shortcuts Manager
 */
(function(window) {
  "use strict";

  const { state, lyrView, isModalOpen, isTypingInTextField, showToast } = window.ImageBaker;
  const api = window.ImageBaker.api;

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

        // 6. Save State: Ctrl + S
        if (key === "s" && !e.shiftKey) {
          e.preventDefault();
          const saveStateBtn = document.getElementById("btn-save-state");
          if (saveStateBtn) saveStateBtn.click();
          return;
        }

        // 7. Group Layers: Ctrl + G
        if (key === "g") {
          e.preventDefault();
          if (state.active_tab === "Baker") {
            try {
              const selected = (state.baker?.layers || []).filter(l => l.selected);
              const selIds = selected.map(l => l.layer_id);
              const res = await api.performBakerLayerAction("group", { layer_ids: selIds });
              if (res && res.state) {
                window.ImageBaker.applyServerState(res.state);
                showToast("baker", res.message || "Group/Ungroup layers");
              } else if (res && !res.ok) {
                showToast("baker", res.message || "Failed to group/ungroup layers");
              }
            } catch (err) {
              console.error("Group layers error:", err);
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
      // =======================================================================
      if (!cmdOrCtrl && !e.altKey) {
        switch (key) {
          // Mode switching in Layerify
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

          // Navigation [ and ]
          case "[":
            e.preventDefault();
            if (window.ImageBaker.stepHeaderNavigation) {
              window.ImageBaker.stepHeaderNavigation(-1);
            }
            break;
          case "]":
            e.preventDefault();
            if (window.ImageBaker.stepHeaderNavigation) {
              window.ImageBaker.stepHeaderNavigation(1);
            }
            break;

          // Fit viewport F
          case "f":
            e.preventDefault();
            if (state.active_tab === "Layerify") {
              window.ImageBaker.canvasLayerify.fitLayerifyImageIfNeeded();
            } else if (state.active_tab === "Baker") {
              window.ImageBaker.canvasBaker.fitBakerLayersIfNeeded(true);
            }
            break;

          // Grid toggle G
          case "g":
            e.preventDefault();
            const gridBtn = document.getElementById("btn-top-grid");
            if (gridBtn) gridBtn.click();
            break;

          // Rotate selected layer in Baker (R / Shift+R)
          case "r":
            if (state.active_tab === "Baker") {
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
            }
            break;

          // Toggle visibility H
          case "h":
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
            break;

          // Caption C
          case "c":
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
            break;

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
                selected.forEach(a => {
                  if (a.rectangle) {
                    a.rectangle = [a.rectangle[0] + dx, a.rectangle[1] + dy, a.rectangle[2], a.rectangle[3]];
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
              if (sel.length > 0) {
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

          // Layerify L (selected if any, otherwise all)
          case "l":
            e.preventDefault();
            {
              const selAnns = (state.layerify?.annotations || []).filter(a => a.selected && a.visible);
              if (selAnns.length > 0) {
                window.ImageBaker.uiLayerify.runLayerifySelected(selAnns.map(a => a.annotation_id));
              } else {
                window.ImageBaker.uiLayerify.runLayerifyAll();
              }
            }
            break;

          // Predict P
          case "p":
            e.preventDefault();
            window.ImageBaker.uiLayerify.runModelPrediction();
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

