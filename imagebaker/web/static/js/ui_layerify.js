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
    if (ann.has_mask || ann.mask_png_b64) return { icon: "🖌️", tag: "Brush" };
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

      row.innerHTML = `
        <span class="item-color-swatch" style="background-color: ${hex};"></span>
        <div class="item-text-col">
          <div class="item-title">${geom.icon} #${idx + 1} ${utils.escapeHtml(ann.label)}</div>
          <div class="item-subtitle">${geom.tag}${ann.caption ? ` • 💬 ${utils.escapeHtml(ann.caption)}` : ""}</div>
        </div>
        <div class="item-actions">
          <button class="icon-btn-xs btn-vis" title="Toggle visibility">${ann.visible ? "👀" : "🚫"}</button>
          <button class="icon-btn-xs btn-del" title="Delete annotation">🗑️</button>
        </div>
      `;

      row.addEventListener("click", e => {
        if (e.target.closest(".btn-vis") || e.target.closest(".btn-del")) return;
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
      });

      row.querySelector(".btn-vis").addEventListener("click", async e => {
        e.stopPropagation();
        ann.visible = !ann.visible;
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(false, `Toggled visibility`);
      });

      row.querySelector(".btn-del").addEventListener("click", async e => {
        e.stopPropagation();
        annotations.splice(idx, 1);
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        renderAnnotationList();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, `Deleted annotation`);
      });

      container.appendChild(row);
    });
  }

  function renderLabelAndModelControls() {
    const labels = state.layerify.labels || [];
    const chipsWrap = document.getElementById("ls-label-chips");
    if (chipsWrap) {
      chipsWrap.innerHTML = "";
      labels.forEach((lbl, idx) => {
        const [r, g, b] = lbl.color || [255, 255, 255];
        const hex = utils.rgbToHex(r, g, b);
        const isCurrent = lbl.name === (state.layerify.current_label || "Undefined");
        const chip = document.createElement("button");
        chip.className = `ls-label-chip ${isCurrent ? "active" : ""}`;
        if (isCurrent) chip.style.borderColor = hex;
        chip.title = lbl.name === "Undefined"
          ? `Default label "Undefined" (active when no other label is selected)`
          : `Select label "${lbl.name}" ${idx < 10 ? `(Hotkey: ${idx})` : ""}`;
        chip.innerHTML = `
          <span class="ls-chip-swatch" style="background-color: ${hex};"></span>
          <span>${utils.escapeHtml(lbl.name)}</span>
          ${idx < 10 ? `<kbd class="ls-chip-key">${idx}</kbd>` : ""}
        `;
        chip.addEventListener("click", async () => {
          chip.blur();
          const nextLabel = isCurrent && lbl.name !== "Undefined" ? "Undefined" : lbl.name;
          await selectLabelAndMaybeAssign(nextLabel);
        });
        chip.addEventListener("dblclick", e => {
          e.stopPropagation();
          openManageLabelsModal();
        });
        chipsWrap.appendChild(chip);
      });
    }

    const curLblObj = labels.find(l => l.name === state.layerify.current_label);
    const colorPicker = document.getElementById("input-label-color-picker");
    if (curLblObj && curLblObj.color && colorPicker) {
      const [r, g, b] = curLblObj.color;
      colorPicker.value = utils.rgbToHex(r, g, b);
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
      const res = await api.layerifyAll(null);
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
        showToast("layerify", res.message || "Layerified into Baker layers!");
      }
    } catch (err) {
      showToast("layerify", "Layerify error: " + err.message);
    }
  }

  function openManageLabelsModal() {
    const list = document.getElementById("manage-labels-list");
    if (!list) return;
    list.innerHTML = "";
    const labels = state.layerify.labels || [];
    labels.forEach(lbl => {
      const [r, g, b] = lbl.color || [255, 255, 255];
      const hex = utils.rgbToHex(r, g, b);
      const isUndef = lbl.name === "Undefined";
      const item = document.createElement("div");
      item.className = "manage-label-item";
      item.innerHTML = `
        <span class="manage-label-color-swatch" style="background-color: ${hex};"></span>
        <span class="manage-label-name">${utils.escapeHtml(lbl.name)}</span>
        <div class="manage-label-actions">
          <input type="color" value="${hex}" class="inline-color-input" title="Recolor label" />
          ${!isUndef ? `<button class="btn btn-xs btn-danger btn-del-lbl" title="Delete label">🗑️</button>` : ""}
        </div>
      `;

      item.querySelector(".inline-color-input").addEventListener("change", async e => {
        const rgb = utils.hexToRgb(e.target.value);
        await api.manageLabels({ action: "color", label: lbl.name, color: rgb });
        const fresh = await api.fetchState();
        window.ImageBaker.applyServerState(fresh.state);
        openManageLabelsModal();
      });

      const delBtn = item.querySelector(".btn-del-lbl");
      if (delBtn) {
        delBtn.addEventListener("click", async () => {
          if (!confirm(`Delete label "${lbl.name}"?`)) return;
          await api.manageLabels({ action: "delete", label: lbl.name });
          const fresh = await api.fetchState();
          window.ImageBaker.applyServerState(fresh.state);
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

    const modelSelect = document.getElementById("select-model");
    if (modelSelect) {
      modelSelect.addEventListener("change", async e => {
        const res = await api.selectModel(e.target.value);
        if (res.ok && res.state) window.ImageBaker.applyServerState(res.state);
      });
    }

    const quickAddBtn = document.getElementById("btn-quick-add-label");
    if (quickAddBtn) {
      quickAddBtn.addEventListener("click", () => {
        const nameInput = document.getElementById("input-new-label-name");
        if (nameInput) nameInput.value = "";
        openModal("modal-add-label");
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

    // Tool strip mode buttons
    document.querySelectorAll(".ls-tool-btn.mode-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        if (mode) window.ImageBaker.canvasLayerify.setLayerifyMode(mode);
      });
    });

    // Save / Load annotations modals
    const saveAnnBtn = document.getElementById("btn-save-annotations");
    if (saveAnnBtn) {
      saveAnnBtn.addEventListener("click", () => {
        const name = (state.layerify.current_image_name || "annotations").replace(/\.[^/.]+$/, "");
        const input = document.getElementById("input-save-ann-filename");
        if (input) input.value = `${name}.json`;
        openModal("modal-save-annotations");
      });
    }

    const loadAnnBtn = document.getElementById("btn-load-annotations");
    if (loadAnnBtn) {
      loadAnnBtn.addEventListener("click", () => openModal("modal-load-annotations"));
    }
  }

  function bindModals() {
    const confirmAddLabel = document.getElementById("btn-confirm-add-label");
    if (confirmAddLabel) {
      confirmAddLabel.addEventListener("click", async () => {
        const input = document.getElementById("input-new-label-name");
        const val = input ? input.value.trim() : "";
        if (!val) return;
        closeAllModals();
        const res = await api.manageLabels({ action: "create", label: val });
        if (res.ok && res.state) window.ImageBaker.applyServerState(res.state);
      });
    }

    const confirmSaveAnn = document.getElementById("btn-confirm-save-ann");
    if (confirmSaveAnn) {
      confirmSaveAnn.addEventListener("click", async () => {
        const filename = document.getElementById("input-save-ann-filename")?.value || "annotations.json";
        const fmt = document.getElementById("select-save-ann-format")?.value || "default";
        closeAllModals();
        showToast("layerify", `Saving annotations as ${fmt.toUpperCase()}...`);
        const res = await api.saveAnnotations(filename, fmt);
        if (res.ok) showToast("layerify", res.message || "Annotations saved");
      });
    }

    const fileInput = document.getElementById("input-load-ann-file");
    const confirmLoadAnn = document.getElementById("btn-confirm-load-ann");
    if (confirmLoadAnn && fileInput) {
      confirmLoadAnn.addEventListener("click", async () => {
        if (!fileInput.files || fileInput.files.length === 0) return;
        const file = fileInput.files[0];
        const fmt = document.getElementById("select-load-ann-format")?.value || "auto";
        const content = await file.text();
        closeAllModals();
        showToast("layerify", "Loading annotations...");
        const res = await api.loadAnnotations(content, fmt);
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
          showToast("layerify", "Annotations loaded successfully");
        }
      });
    }
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.uiLayerify = {
    initLayerifyUI,
    renderImageList,
    renderAnnotationList,
    renderLabelAndModelControls,
    selectLabelAndMaybeAssign,
    runModelPrediction,
    runLayerifyAll,
    openManageLabelsModal,
  };
})(window);

