/**
 * ImageBaker Web - Layerify UI & Action Controls
 */
(function(window) {
  "use strict";

  const { state, lyrView, showToast, showLayerifyLoading, hideLayerifyLoading, openModal, closeAllModals } = window.ImageBaker;
  const utils = window.ImageBaker.utils;
  const api = window.ImageBaker.api;

  let imagePage = 0;

  function initLayerifyUI() {
    bindActionButtons();
    bindModals();
  }

  function getAnnotationGeometryTag(ann) {
    if (ann.type === "brush" || ann.type === "brushlabels" || ann.has_mask || ann.mask_png_b64 || (ann.rle && ann.rle.length > 0)) return { icon: "🖌️", tag: "Brush" };
    if (ann.polygon && ann.polygon.length >= 3) return { icon: "🔷", tag: `Poly(${ann.polygon.length})` };
    if (ann.rectangle && ann.rectangle.length === 4) return { icon: "🔳", tag: "Rect" };
    if (ann.points && ann.points.length > 0) return { icon: "📍", tag: "Point" };
    return { icon: "•", tag: "Region" };
  }

  function renderImageList() {
    const container = document.getElementById("image-list-items");
    const pageInfo = document.getElementById("img-page-info");
    const prevBtn = document.getElementById("img-prev-btn");
    const nextBtn = document.getElementById("img-next-btn");
    if (!container) return;

    const images = state.layerify.images || [];
    const totalBadge = document.getElementById("badge-image-total");
    if (totalBadge) totalBadge.textContent = String(images.length);

    const pageSize = state.configs?.layer_config?.thumbnail_page_size || 15;
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
        <img class="item-thumb" src="${item.thumbnail}" alt="${utils.escapeHtml(item.name)}" />
        <div class="item-text-col">
          <div class="item-title" title="${utils.escapeHtml(item.name)}">${utils.escapeHtml(item.name)}</div>
          <div class="item-subtitle">${item.width} × ${item.height}</div>
        </div>
      `;
      row.addEventListener("click", async () => {
        try {
          showLayerifyLoading(`Loading ${item.full_name || item.name}…`);
          const res = await api.selectImage(item.index);
          if (res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
          }
        } catch (err) {
          hideLayerifyLoading();
          showToast("layerify", err.message);
        }
      });
      container.appendChild(row);
    }

    if (pageInfo) {
      pageInfo.textContent = total === 0 ? "No items" : `Showing ${start + 1} to ${end} of ${total}`;
    }
    if (prevBtn) prevBtn.disabled = imagePage === 0;
    if (nextBtn) nextBtn.disabled = end >= total;
  }

  function renderAnnotationList() {
    const container = document.getElementById("annotation-list-items");
    if (!container) return;
    const annotations = state.layerify.annotations || [];
    container.innerHTML = "";

    const annTotal = document.getElementById("badge-ann-total");
    if (annTotal) annTotal.textContent = String(annotations.length);

    const selectAllBtn = document.getElementById("btn-select-all-anns");
    if (selectAllBtn) {
      const allSelected = annotations.length > 0 && annotations.every(a => Boolean(a.selected));
      selectAllBtn.textContent = allSelected ? "☑" : "☐";
      selectAllBtn.classList.toggle("active", allSelected);
      selectAllBtn.disabled = annotations.length === 0;
    }

    const toggleAllVisBtn = document.getElementById("btn-toggle-all-anns-vis");
    if (toggleAllVisBtn) {
      const anyVisible = annotations.length === 0 || annotations.some(a => a.visible !== false);
      toggleAllVisBtn.textContent = anyVisible ? "👀" : "👁️";
      toggleAllVisBtn.classList.toggle("active", !anyVisible && annotations.length > 0);
      toggleAllVisBtn.disabled = annotations.length === 0;
    }

    const inspector = document.getElementById("selected-region-inspector");
    const selIndices = annotations.map((a, i) => (a.selected ? i : -1)).filter(i => i >= 0);
    if (inspector) {
      if (selIndices.length === 1) {
        const idx = selIndices[0];
        const ann = annotations[idx];
        const geom = getAnnotationGeometryTag(ann);
        inspector.classList.remove("hidden");
        const inspName = document.getElementById("inspector-region-name");
        const inspSub = document.getElementById("inspector-region-sub");
        if (inspName) inspName.textContent = `#${idx + 1} ${geom.icon} ${ann.label} (${geom.tag})`;
        if (inspSub) inspSub.textContent = ann.caption ? `💬 "${ann.caption}"` : "Click to select • Del to delete • L to bake";
      } else if (selIndices.length > 1) {
        inspector.classList.remove("hidden");
        const inspName = document.getElementById("inspector-region-name");
        const inspSub = document.getElementById("inspector-region-sub");
        if (inspName) inspName.textContent = `${selIndices.length} Regions Selected`;
        if (inspSub) inspSub.textContent = "Del to delete • L to bake";
      } else {
        inspector.classList.add("hidden");
      }
    }

    annotations.forEach((ann, idx) => {
      const row = document.createElement("div");
      row.className = `list-item ${ann.selected ? "selected" : ""}`;
      const [r, g, b] = ann.color || [47, 128, 237];
      const hex = utils.rgbToHex(r, g, b);
      const geom = getAnnotationGeometryTag(ann);
      const visEmoji = ann.visible !== false ? "👀" : "👁️";

      row.innerHTML = `
        <span class="item-color-swatch" style="background-color: ${hex};"></span>
        <div class="item-text-col">
          <div class="item-title" title="${utils.escapeHtml(ann.label)}">${geom.icon} #${idx + 1} ${utils.escapeHtml(ann.label)}</div>
          <div class="item-subtitle">${geom.tag}${ann.caption ? ` • 💬 ${utils.escapeHtml(ann.caption)}` : ""}</div>
        </div>
        <div class="item-actions">
          <button class="icon-btn btn-ann-cap" title="Edit label & caption (C)">💬</button>
          <button class="icon-btn btn-ann-bake" title="Layerify: Extract into Baker layer (L)">🖨</button>
          <button class="icon-btn btn-ann-vis btn-vis" title="Toggle visibility (H)">${visEmoji}</button>
          <button class="icon-btn btn-ann-del btn-del" title="Delete annotation (Del)">🗑️</button>
        </div>
      `;

      row.addEventListener("mouseenter", () => {
        lyrView.hoveredIdx = idx;
        lyrView.hoverAnnIdx = idx;
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
      });
      row.addEventListener("mouseleave", () => {
        if (lyrView.hoveredIdx === idx || lyrView.hoverAnnIdx === idx) {
          lyrView.hoveredIdx = null;
          lyrView.hoverAnnIdx = null;
          window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        }
      });

      row.addEventListener("click", e => {
        if (e.target.closest("button")) return;
        const multi = e.ctrlKey || e.metaKey || e.shiftKey;
        annotations.forEach((a, i) => {
          if (multi) {
            if (i === idx) a.selected = !a.selected;
          } else {
            a.selected = (i === idx);
          }
        });
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        window.ImageBaker.canvasLayerify.syncAnnotationsToServer(false, "Selected annotation");
      });

      row.addEventListener("dblclick", e => {
        if (e.target.closest("button")) return;
        openEditCaptionModal(idx);
      });

      const capBtn = row.querySelector(".btn-ann-cap");
      if (capBtn) {
        capBtn.addEventListener("click", e => {
          e.stopPropagation();
          openEditCaptionModal(idx);
        });
      }

      const bakeBtn = row.querySelector(".btn-ann-bake");
      if (bakeBtn) {
        bakeBtn.addEventListener("click", async e => {
          e.stopPropagation();
          try {
            showToast("layerify", `Layerifying #${idx + 1} (${ann.label || "Annotation"})...`);
            const res = await api.layerifyAll([ann.annotation_id], false);
            if (res && res.ok && res.state) {
              window.ImageBaker.applyServerState(res.state);
              showToast("layerify", res.message || `Layerified #${idx + 1} into Baker layers!`);
            } else {
              showToast("layerify", (res && res.message) || "Failed to layerify annotation");
            }
          } catch (err) {
            showToast("layerify", "Layerify error: " + err.message);
          }
        });
      }

      const visBtn = row.querySelector(".btn-ann-vis");
      if (visBtn) {
        visBtn.addEventListener("click", async e => {
          e.stopPropagation();
          ann.visible = ann.visible === false ? true : false;
          window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
          renderAnnotationList();
          await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(false, `Toggled visibility`);
        });
      }

      const delBtn = row.querySelector(".btn-ann-del");
      if (delBtn) {
        delBtn.addEventListener("click", async e => {
          e.stopPropagation();
          annotations.splice(idx, 1);
          window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
          renderAnnotationList();
          await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, `Deleted annotation`);
        });
      }

      container.appendChild(row);
    });
  }

  function renderLabelAndModelControls() {
    const labels = state.layerify.labels || [];
    const currentLabelName = (state.layerify.current_label || "Undefined").trim() || "Undefined";
    const labelSelect = document.getElementById("select-label");
    if (labelSelect) {
      labelSelect.innerHTML = "";
      labels.forEach((lbl, idx) => {
        const opt = document.createElement("option");
        opt.value = lbl.name;
        opt.textContent = idx < 10 ? `[${idx}] ${lbl.name}` : lbl.name;
        if (lbl.name === currentLabelName) opt.selected = true;
        labelSelect.appendChild(opt);
      });
    }

    const curLblObj = labels.find(l => l.name === currentLabelName) || labels[0];
    const colorPicker = document.getElementById("input-label-color-picker");
    const activeSwatch = document.getElementById("active-label-swatch");
    if (curLblObj && curLblObj.color) {
      const [r, g, b] = curLblObj.color;
      const hex = utils.rgbToHex(r, g, b);
      if (colorPicker) colorPicker.value = hex;
      if (activeSwatch) activeSwatch.style.backgroundColor = hex;
    }

    const modelSelect = document.getElementById("select-model");
    if (modelSelect) {
      const models = state.layerify.models || ["None"];
      modelSelect.innerHTML = "";
      models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (m === state.layerify.current_model) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    }

    // Restore text prompt value if available
    const promptInput = document.getElementById("input-predict-prompt");
    if (promptInput && state.layerify.current_predict_prompt && !promptInput.value) {
      promptInput.value = state.layerify.current_predict_prompt;
    }

    const canPredict = Boolean(state.layerify.current_model && state.layerify.current_model !== "None");
    const predictBtn = document.getElementById("btn-predict");
    if (predictBtn) predictBtn.disabled = !canPredict;

    const undoBtn = document.getElementById("strip-btn-undo");
    const redoBtn = document.getElementById("strip-btn-redo");
    if (undoBtn) undoBtn.disabled = !state.layerify.can_undo;
    if (redoBtn) redoBtn.disabled = !state.layerify.can_redo;
  }

  async function selectLabelAndMaybeAssign(labelName) {
    try {
      const res = await api.manageLabels({
        action: "select",
        label: labelName,
      });
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
      }
    } catch (err) {
      showToast("layerify", err.message);
    }
  }

  async function runModelPrediction() {
    const promptInput = document.getElementById("input-predict-prompt");
    const textPrompt = promptInput ? promptInput.value.trim() : "";
    try {
      showToast("layerify", textPrompt ? `Predicting with prompt "${textPrompt}"...` : "Running model prediction...");
      const res = await api.runModelPrediction(state.layerify.current_model, textPrompt);
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
        showToast("layerify", res.message || "Prediction complete");
      }
    } catch (err) {
      showToast("layerify", "Prediction error: " + err.message);
    }
  }

  async function runLayerifyAll() {
    try {
      showToast("layerify", "Layerifying all visible annotations...");
      const res = await api.layerifyAll(null, true);
      if (res && res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
        showToast("layerify", res.message || "Layerified all visible annotations into Baker layers!");
      } else {
        showToast("layerify", (res && res.message) || "Failed to layerify annotations");
      }
    } catch (err) {
      showToast("layerify", "Layerify error: " + err.message);
    }
  }

  async function runLayerifySelected(annotationIds = null) {
    try {
      const selected = (state.layerify.annotations || []).filter(a => a.selected && a.visible);
      const targetIds = annotationIds || selected.map(a => a.annotation_id);
      if (!targetIds || targetIds.length === 0) {
        return runLayerifyAll();
      }
      showToast("layerify", `Layerifying ${targetIds.length} selected annotation(s)...`);
      const res = await api.layerifyAll(targetIds, false);
      if (res && res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
        showToast("layerify", res.message || `Layerified ${targetIds.length} selected annotation(s) into Baker layers!`);
      } else {
        showToast("layerify", (res && res.message) || "Failed to layerify selected annotation(s)");
      }
    } catch (err) {
      showToast("layerify", "Layerify error: " + err.message);
    }
  }

  let editCaptionIdx = null;

  function openEditCaptionModal(idx) {
    const annotations = state.layerify.annotations || [];
    const ann = annotations[idx];
    if (!ann) return;
    editCaptionIdx = idx;

    const title = document.getElementById("modal-edit-caption-title");
    if (title) title.textContent = `Edit Region #${idx + 1}`;

    const labelSelect = document.getElementById("select-edit-region-label");
    const labelInput = document.getElementById("input-edit-region-label");
    const captionInput = document.getElementById("input-edit-region-caption");

    if (labelSelect) {
      labelSelect.innerHTML = "";
      (state.layerify?.labels || []).forEach(l => {
        const opt = document.createElement("option");
        opt.value = l.name;
        opt.textContent = l.name;
        if (l.name === ann.label) opt.selected = true;
        labelSelect.appendChild(opt);
      });
      labelSelect.onchange = () => {
        if (labelInput) labelInput.value = labelSelect.value;
      };
    }
    if (labelInput) labelInput.value = ann.label || "";
    if (captionInput) captionInput.value = ann.caption || "";

    openModal("modal-edit-caption");
    if (captionInput) setTimeout(() => captionInput.focus(), 60);
  }

  function openManageLabelsModal() {
    const list = document.getElementById("manage-labels-list");
    if (!list) return;
    list.innerHTML = "";
    const labels = state.layerify?.labels || [];
    labels.forEach(lbl => {
      let hex = lbl.color_hex;
      if (!hex && Array.isArray(lbl.color) && lbl.color.length >= 3) {
        hex = utils.rgbToHex(lbl.color[0], lbl.color[1], lbl.color[2]);
      } else if (!hex && typeof lbl.color === "string") {
        hex = lbl.color.startsWith("#") ? lbl.color : `#${lbl.color}`;
      }
      hex = hex || "#3b82f6";
      const isUndef = lbl.name === "Undefined";
      const item = document.createElement("div");
      item.className = "manage-label-item";
      item.innerHTML = `
        <span class="manage-label-color-swatch" style="background-color: ${hex};"></span>
        <span class="manage-label-name">${utils.escapeHtml(lbl.name)}</span>
        <div class="manage-label-actions">
          <input type="color" value="${hex}" class="inline-color-input" title="Recolor label" />
          ${!isUndef ? `<button class="btn btn-xs btn-rename-lbl" title="Rename label">✏️</button>` : ""}
          ${!isUndef ? `<button class="btn btn-xs btn-danger btn-del-lbl" title="Delete label">🗑️</button>` : ""}
        </div>
      `;

      item.querySelector(".inline-color-input").addEventListener("change", async e => {
        const rgb = utils.hexToRgb(e.target.value);
        const res = await api.manageLabels({ action: "color", label: lbl.name, color: rgb });
        if (res && res.state) {
          window.ImageBaker.applyServerState(res.state);
        } else {
          const fresh = await api.fetchState();
          if (fresh && fresh.state) window.ImageBaker.applyServerState(fresh.state);
        }
        openManageLabelsModal();
      });

      const renameBtn = item.querySelector(".btn-rename-lbl");
      if (renameBtn && !isUndef) {
        renameBtn.addEventListener("click", async () => {
          const newName = window.prompt(`Rename label "${lbl.name}" to:`, lbl.name);
          if (!newName || !newName.trim() || newName.trim() === lbl.name) return;
          const res = await api.manageLabels({
            action: "rename",
            old_name: lbl.name,
            new_name: newName.trim(),
          });
          if (res && res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            openManageLabelsModal();
          } else {
            showToast("layerify", (res && res.message) || "Failed to rename label");
          }
        });
      }

      const delBtn = item.querySelector(".btn-del-lbl");
      if (delBtn) {
        delBtn.addEventListener("click", async () => {
          if (!confirm(`Delete label "${lbl.name}"?`)) return;
          const res = await api.manageLabels({ action: "delete", label: lbl.name });
          if (res && res.state) {
            window.ImageBaker.applyServerState(res.state);
          } else {
            const fresh = await api.fetchState();
            if (fresh && fresh.state) window.ImageBaker.applyServerState(fresh.state);
          }
          openManageLabelsModal();
        });
      }

      list.appendChild(item);
    });
    openModal("modal-manage-labels");
  }

  function bindActionButtons() {
    const prevBtn = document.getElementById("img-prev-btn");
    const nextBtn = document.getElementById("img-next-btn");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (imagePage > 0) {
          imagePage--;
          renderImageList();
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        imagePage++;
        renderImageList();
      });
    }

    const predictBtn = document.getElementById("btn-predict");
    if (predictBtn) predictBtn.addEventListener("click", runModelPrediction);

    const promptInput = document.getElementById("input-predict-prompt");
    if (promptInput) {
      promptInput.addEventListener("keydown", e => {
        if (e.key === "Enter") {
          e.preventDefault();
          runModelPrediction();
        }
      });
    }

    const layerifyAllBtn = document.getElementById("btn-layerify-all");
    if (layerifyAllBtn) layerifyAllBtn.addEventListener("click", runLayerifyAll);

    const labelSelect = document.getElementById("select-label");
    if (labelSelect) {
      labelSelect.addEventListener("change", async e => {
        await selectLabelAndMaybeAssign(e.target.value);
      });
    }

    const modelSelect = document.getElementById("select-model");
    if (modelSelect) {
      modelSelect.addEventListener("change", async e => {
        const res = await api.selectModel(e.target.value);
        if (res.ok && res.state) window.ImageBaker.applyServerState(res.state);
      });
    }

    const quickColorBtn = document.getElementById("btn-quick-label-color");
    const colorPicker = document.getElementById("input-label-color-picker");
    if (quickColorBtn && colorPicker) {
      quickColorBtn.addEventListener("click", () => colorPicker.click());
      colorPicker.addEventListener("change", async e => {
        const rgb = utils.hexToRgb(e.target.value);
        const label = (state.layerify.current_label || "").trim() || "Undefined";
        const res = await api.manageLabels({ action: "color", label, color: rgb });
        if (res.ok && res.state) window.ImageBaker.applyServerState(res.state);
      });
    }

    const manageLabelsBtn = document.getElementById("btn-quick-manage-label");
    if (manageLabelsBtn) manageLabelsBtn.addEventListener("click", openManageLabelsModal);

    const clearBtn = document.getElementById("btn-clear-annotations");
    if (clearBtn) {
      clearBtn.addEventListener("click", async () => {
        if (!confirm("Clear all annotations on this image?")) return;
        state.layerify.annotations = [];
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, "Cleared annotations");
      });
    }

    const undoBtn = document.getElementById("strip-btn-undo");
    const redoBtn = document.getElementById("strip-btn-redo");
    if (undoBtn) undoBtn.addEventListener("click", window.ImageBaker.canvasLayerify.performLayerifyUndo);
    if (redoBtn) redoBtn.addEventListener("click", window.ImageBaker.canvasLayerify.performLayerifyRedo);

    // Header icons in Regions / Annotations dock: Select/Deselect All (☑) & Show/Hide All (👀)
    const selectAllAnnsBtn = document.getElementById("btn-select-all-anns");
    if (selectAllAnnsBtn) {
      selectAllAnnsBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        const annotations = state.layerify.annotations || [];
        if (!annotations.length) {
          showToast("layerify", "No annotations to select");
          return;
        }
        const allSelected = annotations.every(a => Boolean(a.selected));
        const nextSelected = !allSelected;
        annotations.forEach(a => {
          a.selected = nextSelected;
        });
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(
          false,
          nextSelected ? "Selected all annotations" : "Deselected all annotations"
        );
        showToast(
          "layerify",
          nextSelected ? `Selected all ${annotations.length} annotation(s)` : "Deselected all annotations"
        );
      });
    }

    const toggleAllAnnsVisBtn = document.getElementById("btn-toggle-all-anns-vis");
    if (toggleAllAnnsVisBtn) {
      toggleAllAnnsVisBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        const annotations = state.layerify.annotations || [];
        if (!annotations.length) {
          showToast("layerify", "No annotations to show or hide");
          return;
        }
        const anyVisible = annotations.some(a => a.visible !== false);
        const nextVisible = !anyVisible;
        annotations.forEach(a => {
          a.visible = nextVisible;
        });
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(
          false,
          nextVisible ? "Shown all annotations" : "Hidden all annotations"
        );
        showToast("layerify", nextVisible ? "Shown all annotations" : "Hidden all annotations");
      });
    }

    // Left tool strip action buttons: Caption (C), Hide (H), Delete (Del) & Inspector Caption button
    const stripCaptionBtn = document.getElementById("strip-btn-caption");
    const inspCaptionBtn = document.getElementById("btn-insp-caption");
    const handleEditSelectedCaption = e => {
      if (e && e.currentTarget) e.currentTarget.blur();
      const annotations = state.layerify.annotations || [];
      const selIdx = annotations.findIndex(a => a.selected);
      if (selIdx >= 0) {
        openEditCaptionModal(selIdx);
      } else {
        showToast("layerify", "Select a region first to edit its caption or label");
      }
    };
    if (stripCaptionBtn) stripCaptionBtn.addEventListener("click", handleEditSelectedCaption);
    if (inspCaptionBtn) inspCaptionBtn.addEventListener("click", handleEditSelectedCaption);

    const stripVisBtn = document.getElementById("strip-btn-vis");
    if (stripVisBtn) {
      stripVisBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        const annotations = state.layerify.annotations || [];
        if (!annotations.length) {
          showToast("layerify", "No annotations available");
          return;
        }
        const selected = annotations.filter(a => a.selected);
        const targets = selected.length > 0 ? selected : annotations;
        const anyVisible = targets.some(a => a.visible !== false);
        const nextVisible = !anyVisible;
        targets.forEach(a => {
          a.visible = nextVisible;
        });
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(
          false,
          nextVisible ? "Shown annotation(s)" : "Hidden annotation(s)"
        );
        showToast(
          "layerify",
          selected.length > 0
            ? `${nextVisible ? "Shown" : "Hidden"} ${selected.length} selected annotation(s)`
            : `${nextVisible ? "Shown" : "Hidden"} all annotations`
        );
      });
    }

    const stripDeleteBtn = document.getElementById("strip-btn-delete");
    if (stripDeleteBtn) {
      stripDeleteBtn.addEventListener("click", async e => {
        e.currentTarget.blur();
        const annotations = state.layerify.annotations || [];
        const selectedCount = annotations.filter(a => a.selected).length;
        if (selectedCount === 0) {
          showToast("layerify", "Select a region first to delete");
          return;
        }
        state.layerify.annotations = annotations.filter(a => !a.selected);
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(
          true,
          `Deleted ${selectedCount} annotation(s)`
        );
        showToast("layerify", `Deleted ${selectedCount} annotation(s)`);
      });
    }

    // Tool strip mode buttons
    document.querySelectorAll(".ls-tool-btn.mode-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        if (mode) window.ImageBaker.canvasLayerify.setLayerifyMode(mode);
      });
    });

    // Folder Selection & Upload
    const folderBtn = document.getElementById("btn-select-folder-left") || document.getElementById("btn-select-folder");
    if (folderBtn) {
      folderBtn.addEventListener("click", () => openSelectFolderDialog());
    }

    const uploadImagesBtn = document.getElementById("btn-upload-images-left") || document.getElementById("btn-upload-images");
    if (uploadImagesBtn) {
      uploadImagesBtn.addEventListener("click", () => {
        const inp = document.getElementById("hidden-image-upload-input");
        if (inp) inp.click();
      });
    }

    const hiddenUploadInp = document.getElementById("hidden-image-upload-input");
    if (hiddenUploadInp && !hiddenUploadInp._hasListener) {
      hiddenUploadInp._hasListener = true;
      hiddenUploadInp.addEventListener("change", async e => {
        const files = Array.from(e.target.files || []);
        if (!files.length) return;
        const payloadFiles = [];
        for (const f of files) {
          const b64 = await utils.readFileAsDataUrl(f);
          payloadFiles.push({ name: f.name, data_b64: b64 });
        }
        e.target.value = "";
        try {
          const res = await api.apiPost("/api/layerify/upload-images", { files: payloadFiles });
          if (res.ok && res.state) {
            imagePage = 0;
            window.ImageBaker.applyServerState(res.state);
            showToast("layerify", `Uploaded ${res.uploaded || files.length} image(s)`);
          }
        } catch (err) {
          showToast("layerify", err.message);
        }
      });
    }

    // Save / Load annotations modals
    const saveAnnBtn = document.getElementById("btn-save-annotations");
    if (saveAnnBtn) {
      saveAnnBtn.addEventListener("click", () => {
        annIoMode = "save";
        const title = document.getElementById("modal-ann-io-title");
        const desc = document.getElementById("modal-ann-io-desc");
        const uploadGrp = document.getElementById("group-ann-file-upload");
        const pathGrp = document.getElementById("group-ann-file-path");
        const pathInp = document.getElementById("input-ann-file-path");
        if (title) title.textContent = "Save Annotations";
        if (desc) desc.textContent = "Do you want to save annotations for all layers or just the current layer?";
        if (uploadGrp) uploadGrp.classList.add("hidden");
        if (pathGrp) pathGrp.classList.remove("hidden");
        const name = (state.layerify?.current_image_name || "annotations").replace(/\.[^/.]+$/, "");
        if (pathInp) pathInp.value = `${name}.json`;
        openModal("modal-annotations-io");
      });
    }

    const loadAnnBtn = document.getElementById("btn-load-annotations");
    if (loadAnnBtn) {
      loadAnnBtn.addEventListener("click", () => {
        annIoMode = "load";
        const title = document.getElementById("modal-ann-io-title");
        const desc = document.getElementById("modal-ann-io-desc");
        const uploadGrp = document.getElementById("group-ann-file-upload");
        const uploadInp = document.getElementById("input-ann-upload-json");
        if (title) title.textContent = "Load Annotations";
        if (desc) desc.textContent = "Do you want to load annotations for all layers or just the current layer?";
        if (uploadGrp) uploadGrp.classList.remove("hidden");
        if (uploadInp) uploadInp.value = "";
        openModal("modal-annotations-io");
      });
    }
  }

  let annIoMode = "save";

  async function openSelectFolderDialog() {
    openModal("modal-folder-browser");
    await browseFolder(state?.layerify?.current_folder || "");
  }

  async function selectServerFolderPath(folderPath) {
    if (!folderPath) return;
    try {
      const res = await api.apiPost("/api/layerify/select-folder", { folder_path: folderPath });
      closeAllModals();
      imagePage = 0;
      if (res.ok && res.state) window.ImageBaker.applyServerState(res.state);
    } catch (err) {
      showToast("layerify", err.message);
    }
  }

  async function browseFolder(pathStr) {
    try {
      const data = await api.apiGet(`/api/layerify/browse-folders?path=${encodeURIComponent(pathStr || "")}`);
      const input = document.getElementById("input-folder-path");
      if (input) input.value = data.current || "";
      const countInfo = document.getElementById("folder-image-count-info");
      if (countInfo) {
        countInfo.textContent = `Subfolders: ${(data.directories || []).length} • Supported images: ${data.image_count || 0}`;
      }

      const quickWrap = document.getElementById("folder-quick-paths");
      if (quickWrap) {
        quickWrap.innerHTML = "";
        (data.quick_paths || []).forEach(qp => {
          const pill = document.createElement("button");
          pill.className = "quick-path-pill";
          const qpName = qp.name || qp.label || qp.path || "";
          pill.textContent = `📌 ${qpName}`;
          pill.title = qp.path;
          pill.addEventListener("click", () => browseFolder(qp.path));
          quickWrap.appendChild(pill);
        });
      }

      const list = document.getElementById("folder-browser-list");
      if (!list) return;
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

        data.directories.forEach(dir => {
          const row = document.createElement("div");
          row.className = "folder-row";
          row.innerHTML = `
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">📁 ${utils.escapeHtml(dir.name)}</span>
            <button class="btn btn-xs" title="Load images from this subfolder directly">Load</button>
          `;
          row.addEventListener("click", e => {
            if (e.target.closest("button")) return;
            browseFolder(dir.path);
          });
          row.querySelector("button").addEventListener("click", e => {
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

        data.images.slice(0, 30).forEach(imgItem => {
          const fRow = document.createElement("div");
          fRow.className = "folder-file-item";
          fRow.innerHTML = `<span>🖼️</span><span>${utils.escapeHtml(imgItem.name)}</span>`;
          list.appendChild(fRow);
        });
        if (data.images.length > 30) {
          const moreRow = document.createElement("div");
          moreRow.className = "folder-file-item";
          moreRow.style.color = "var(--muted)";
          moreRow.textContent = `... and ${data.images.length - 30} more images`;
          list.appendChild(moreRow);
        }
      }
    } catch (err) {
      showToast("layerify", "Error browsing folders: " + err.message);
    }
  }

  async function handleAnnotationsIo(allLayers) {
    const filePath = document.getElementById("input-ann-file-path")?.value.trim() || "annotations.json";
    const fmt = document.getElementById("select-ann-io-format")?.value || "default";
    try {
      if (annIoMode === "save") {
        const res = await api.apiPost("/api/layerify/annotations/save", {
          all_layers: allLayers,
          file_path: filePath,
          format: fmt,
        });
        closeAllModals();
        if (res.ok && res.state) window.ImageBaker.applyServerState(res.state);
        if (res.json_content) {
          utils.downloadTextFile(filePath.split(/[\\/]/).pop() || "annotations.json", res.json_content);
        }
        showToast("layerify", res.message || "Annotations saved");
      } else {
        const uploadInp = document.getElementById("input-ann-upload-json");
        let jsonContent = null;
        if (uploadInp && uploadInp.files && uploadInp.files[0]) {
          jsonContent = await uploadInp.files[0].text();
        }
        const res = await api.apiPost("/api/layerify/annotations/load", {
          all_layers: allLayers,
          file_path: filePath,
          format: fmt,
          json_content: jsonContent,
        });
        closeAllModals();
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("layerify", res.message || "Annotations loaded");
        }
      }
    } catch (err) {
      showToast("layerify", err.message);
    }
  }

  function bindModals() {
    // Folder Browser Modal Controls
    const browseGoBtn = document.getElementById("btn-browse-go");
    const folderInput = document.getElementById("input-folder-path");
    if (browseGoBtn && folderInput) {
      browseGoBtn.addEventListener("click", () => browseFolder(folderInput.value.trim()));
      folderInput.addEventListener("keydown", e => {
        if (e.key === "Enter") {
          e.preventDefault();
          browseFolder(folderInput.value.trim());
        }
      });
    }

    const confirmSelectFolder = document.getElementById("btn-confirm-select-folder");
    if (confirmSelectFolder && folderInput) {
      confirmSelectFolder.addEventListener("click", () => selectServerFolderPath(folderInput.value.trim()));
    }

    // Local OS Folder Picker (webkitdirectory)
    const pickLocalFolderBtn = document.getElementById("btn-pick-local-folder");
    const hiddenFolderUpload = document.getElementById("hidden-folder-upload-input");
    if (pickLocalFolderBtn && hiddenFolderUpload) {
      pickLocalFolderBtn.addEventListener("click", () => hiddenFolderUpload.click());
      hiddenFolderUpload.addEventListener("change", async e => {
        const files = Array.from(e.target.files || []).filter(f =>
          /\.(png|jpe?g|bmp|tiff?|webp)$/i.test(f.name)
        );
        if (!files.length) {
          showToast("layerify", "No supported images found in selected folder");
          return;
        }
        showLayerifyLoading(`Reading ${files.length} images...`);
        const payloadFiles = [];
        for (const f of files) {
          const b64 = await utils.readFileAsDataUrl(f);
          payloadFiles.push({ name: f.name, data_b64: b64 });
        }
        e.target.value = "";
        try {
          const res = await api.apiPost("/api/layerify/upload-images", {
            files: payloadFiles,
            folder_name: files[0]?.webkitRelativePath?.split("/")[0] || "LocalFolder",
          });
          hideLayerifyLoading();
          closeAllModals();
          imagePage = 0;
          if (res.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            showToast("layerify", `Loaded ${files.length} image(s)`);
          }
        } catch (err) {
          hideLayerifyLoading();
          showToast("layerify", err.message);
        }
      });
    }

    // Save / Load Annotations Modal Controls
    const singleLayerBtn = document.getElementById("btn-ann-io-single");
    const allLayersBtn = document.getElementById("btn-ann-io-all");
    if (singleLayerBtn) singleLayerBtn.addEventListener("click", () => handleAnnotationsIo(false));
    if (allLayersBtn) allLayersBtn.addEventListener("click", () => handleAnnotationsIo(true));

    // Manage Labels Modal Controls
    const manageAddBtn = document.getElementById("btn-manage-add-label");
    const manageInput = document.getElementById("input-manage-new-label");
    const manageColor = document.getElementById("input-manage-new-color");
    async function handleManageAddLabel() {
      const val = manageInput ? manageInput.value.trim() : "";
      if (!val) return;
      const colorHex = manageColor ? manageColor.value : "#3b82f6";
      const rgb = utils.hexToRgb(colorHex);
      const res = await api.manageLabels({ action: "add", label: val, color: rgb });
      if (res && res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
        if (manageInput) manageInput.value = "";
        openManageLabelsModal();
      } else {
        showToast("layerify", (res && res.message) || "Failed to add label");
      }
    }
    if (manageAddBtn) manageAddBtn.addEventListener("click", handleManageAddLabel);
    if (manageInput) {
      manageInput.addEventListener("keydown", e => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleManageAddLabel();
        }
      });
    }

    const confirmAddLabel = document.getElementById("btn-confirm-add-label");
    const inputNewLabelName = document.getElementById("input-new-label-name");
    const inputNewLabelColor = document.getElementById("input-new-label-color");
    if (confirmAddLabel) {
      confirmAddLabel.addEventListener("click", async () => {
        const val = inputNewLabelName ? inputNewLabelName.value.trim() : "";
        if (!val) return;
        const colorHex = inputNewLabelColor ? inputNewLabelColor.value : "#3b82f6";
        const rgb = utils.hexToRgb(colorHex);
        closeAllModals();
        const res = await api.manageLabels({ action: "add", label: val, color: rgb });
        if (res && res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
        } else {
          showToast("layerify", (res && res.message) || "Failed to add label");
        }
      });
    }
    if (inputNewLabelName) {
      inputNewLabelName.addEventListener("keydown", e => {
        if (e.key === "Enter") {
          e.preventDefault();
          if (confirmAddLabel) confirmAddLabel.click();
        }
      });
    }

    // Edit Caption & Label Modal Controls
    const confirmEditCaption = document.getElementById("btn-confirm-edit-caption");
    if (confirmEditCaption) {
      confirmEditCaption.addEventListener("click", async () => {
        if (editCaptionIdx === null) return;
        const annotations = state.layerify.annotations || [];
        const ann = annotations[editCaptionIdx];
        if (!ann) return;
        const newLbl = document.getElementById("input-edit-region-label")?.value.trim() || ann.label;
        const newCap = document.getElementById("input-edit-region-caption")?.value.trim() || "";
        ann.label = newLbl;
        const known = (state.layerify?.labels || []).find(l => l.name === newLbl);
        if (known) {
          ann.color = known.color || utils.hexToRgb(known.color_hex);
        }
        ann.caption = newCap;
        closeAllModals();
        renderAnnotationList();
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, `Updated region #${editCaptionIdx + 1}`);
      });
    }
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.uiLayerify = {
    initLayerifyUI,
    renderImageList,
    renderAnnotationList,
    renderLabelAndModelControls,
    renderLabelChips: renderLabelAndModelControls,
    renderModelSelector: renderLabelAndModelControls,
    showLoading: (text) => window.ImageBaker.showLayerifyLoading && window.ImageBaker.showLayerifyLoading(text),
    hideLoading: () => window.ImageBaker.hideLayerifyLoading && window.ImageBaker.hideLayerifyLoading(),
    selectLabelAndMaybeAssign,
    runModelPrediction,
    runLayerifyAll,
    runLayerifySelected,
    openManageLabelsModal,
    openEditCaptionModal,
  };
})(window);

