/**
 * ImageBaker Web - Layerify Modal Dialogs & File/Folder IO
 */
(function(window) {
  "use strict";

  const { state, showToast, showLayerifyLoading, hideLayerifyLoading, openModal, closeAllModals } = window.ImageBaker;
  const utils = window.ImageBaker.utils;
  const api = window.ImageBaker.api;

  let editCaptionIdx = null;
  let annIoMode = "save";

  function setIoMode(mode) {
    annIoMode = mode === "load" ? "load" : "save";
  }

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

  async function openSelectFolderDialog() {
    openModal("modal-folder-browser");
    await browseFolder(state?.layerify?.current_folder || "");
  }

  async function selectServerFolderPath(folderPath) {
    if (!folderPath) return;
    try {
      const res = await api.apiPost("/api/layerify/select-folder", { folder_path: folderPath });
      closeAllModals();
      window.ImageBaker.uiLayerify?.resetImagePage?.();
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
          window.ImageBaker.uiLayerify?.resetImagePage?.();
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
        window.ImageBaker.uiLayerify?.renderAnnotationList?.();
        window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
        await window.ImageBaker.canvasLayerify.syncAnnotationsToServer(true, `Updated region #${editCaptionIdx + 1}`);
      });
    }
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.uiLayerifyModals = {
    setIoMode,
    openEditCaptionModal,
    openManageLabelsModal,
    openSelectFolderDialog,
    selectServerFolderPath,
    browseFolder,
    handleAnnotationsIo,
    bindModals,
  };
})(window);
