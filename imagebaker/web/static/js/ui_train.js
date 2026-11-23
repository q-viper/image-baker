/**
 * ImageBaker Web - Train Tab UI Controller (Schema Inspector, Live Metrics & Runs)
 */
(function(window) {
  "use strict";

  const api = window.ImageBaker.api;
  const flow = window.ImageBaker.trainFlow;
  const { showToast } = window.ImageBaker;

  let catalog = {
    trainers: {},
    augmentations: {},
    device_info: "cpu",
    labels: [],
    data_counts: { baker_states: 0, layerify_images: 0, layerify_annotated: 0 },
  };
  let lastActiveRunId = null;
  let selectedRunId = null;
  let runNameManuallyEdited = false;
  let clearedLogOffset = 0;
  let lastLogRunId = null;
  let lastFullRawLog = "";
  let currentEvalImages = [];
  let lightboxIndex = 0;
  let statusPoller = null;
  let hoverPreviewTimer = null;
  let autoCacheTimer = null;

  function slugifyPart(str) {
    return String(str || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 24);
  }

  function buildAutoRunName(pipeline) {
    const nodes = pipeline?.nodes || [];
    const dataNodes = nodes.filter(n => n.type === "data_source");
    const trainerNode = nodes.find(n => n.type === "trainer");
    const splitNode = nodes.find(n => n.type === "split_filter");

    const sources = Array.from(new Set(dataNodes.map(n => n.config?.source || "layerify")));
    const srcPart = sources.length > 1 ? "hybrid" : (sources[0] || "data");

    const tc = trainerNode?.config || {};
    const modelPart = slugifyPart(tc.variant || tc.trainer_name || "model");
    const modePart = slugifyPart(tc.training_mode || "train");
    const epPart = tc.epochs ? `ep${tc.epochs}` : "";

    const labels = splitNode?.config?.selected_labels || [];
    const lblPart = labels.length === 1 ? slugifyPart(labels[0]) : (labels.length > 1 ? `${labels.length}cls` : "");

    return [srcPart, modelPart, modePart, epPart, lblPart].filter(Boolean).join("_");
  }

  function syncAutoRunName(pipeline, force = false) {
    const inp = document.getElementById("input-train-run-name");
    if (!inp) return;
    if (force) runNameManuallyEdited = false;
    if (!runNameManuallyEdited || !inp.value.trim()) {
      inp.value = buildAutoRunName(pipeline || flow.getPipeline());
    }
  }

  function scheduleAutoCachePipeline(pipeline) {
    syncAutoRunName(pipeline, false);
    clearTimeout(autoCacheTimer);
    autoCacheTimer = setTimeout(async () => {
      try {
        await api.saveTrainPipeline(pipeline || flow.getPipeline());
      } catch (_) {}
    }, 450);
  }

  async function initTrainUI() {
    flow.initFlow({
      onSelectChange: renderNodeInspector,
      onGraphChange: scheduleAutoCachePipeline,
      onNodeHover: handleNodeHover,
      onNodeLeave: handleNodeLeave,
    });

    bindTrainButtons();
    await loadCatalogAndPipeline();
    startStatusPolling();
  }

  const IMAGE_PREVIEW_NODE_TYPES = new Set(["data_source", "augmentation", "eval_vis"]);

  function handleNodeHover(node) {
    clearTimeout(hoverPreviewTimer);
    if (!node || !IMAGE_PREVIEW_NODE_TYPES.has(node.type)) return;
    hoverPreviewTimer = setTimeout(async () => {
      try {
        const res = await api.previewTrainNode(flow.getPipeline(), node.id);
        if (!res?.ok || !res.image_b64) return;
        const pop = document.getElementById("flow-hover-preview");
        const title = document.getElementById("flow-preview-title");
        const meta = document.getElementById("flow-preview-meta");
        const img = document.getElementById("flow-preview-img");
        const augs = document.getElementById("flow-preview-augs");
        if (title) title.textContent = `${res.node_label} — ${res.source}`;
        if (meta) meta.textContent = `${res.num_annotations} ann(s)`;
        if (img) img.src = res.image_b64;
        if (augs) {
          augs.textContent = (res.applied_augmentations || []).length
            ? `Augmentations: ${res.applied_augmentations.join(" → ")}`
            : "No upstream augmentations applied";
        }
        if (pop) pop.classList.remove("hidden");
      } catch (_) {}
    }, 220);
  }

  function handleNodeLeave() {
    clearTimeout(hoverPreviewTimer);
    const pop = document.getElementById("flow-hover-preview");
    if (pop) pop.classList.add("hidden");
  }

  async function loadCatalogAndPipeline() {
    try {
      const [catRes, pipeRes, stRes] = await Promise.all([
        api.getTrainCatalog(),
        api.getTrainPipeline(),
        api.getTrainStatus(),
      ]);
      if (catRes?.ok && catRes.catalog) {
        catalog = catRes.catalog;
        flow.setDataCounts(catalog.data_counts || {});
        const devBadge = document.getElementById("train-device-badge");
        if (devBadge) devBadge.textContent = `Device: ${catalog.device_info || "cpu"}`;
      }
      if (pipeRes?.ok && pipeRes.pipeline) {
        flow.setPipeline(pipeRes.pipeline);
        syncAutoRunName(pipeRes.pipeline, true);
      }
      if (stRes?.ok && stRes.training) {
        renderTrainingStatus(stRes.training);
      }
    } catch (err) {
      console.error("Failed to initialize Train tab:", err);
    }
  }

  function bindTrainButtons() {
    const addMap = [
      ["btn-add-node-data", "data_source", "Layerify Data", { source: "layerify", export_format: "coco" }],
      ["btn-add-node-baker-data", "data_source", "Baker States", { source: "baker", export_format: "coco" }],
      ["btn-add-node-split", "split_filter", "Split & Filter", { train_ratio: 0.7, val_ratio: 0.2, test_ratio: 0.1, real_only_val: true, selected_labels: [], annotation_types: ["rectangle", "polygon", "brush", "point"] }],
      ["btn-add-node-aug", "augmentation", "HorizontalFlip", { augmentation_name: "HorizontalFlip", enabled: true, probability: 0.5 }],
      ["btn-add-node-trainer", "trainer", "Model Trainer", { trainer_name: Object.keys(catalog.trainers || {})[0] || "", training_mode: "finetune", epochs: 5, batch_size: 4 }],
      ["btn-add-node-output", "output", "Checkpoint & Layerify", { auto_load_layerify: true }],
      ["btn-add-node-eval", "eval_vis", "Eval & Visualize", { split: "val", max_samples: 6, conf_threshold: 0.35, draw_ground_truth: true }],
    ];
    addMap.forEach(([id, type, label, cfg]) => {
      const btn = document.getElementById(id);
      if (btn) {
        btn.addEventListener("click", () => {
          const finalCfg = { ...cfg };
          if (type === "trainer" && !finalCfg.trainer_name) {
            finalCfg.trainer_name = Object.keys(catalog.trainers || {})[0] || "";
          }
          flow.addNode(type, label, finalCfg);
        });
      }
    });

    const layoutBtn = document.getElementById("btn-train-autolayout");
    if (layoutBtn) layoutBtn.addEventListener("click", () => flow.autoLayout());

    const delBtn = document.getElementById("btn-train-delete-node");
    if (delBtn) delBtn.addEventListener("click", () => flow.deleteSelection());

    const saveBtn = document.getElementById("btn-train-save-pipeline");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const res = await api.saveTrainPipeline(flow.getPipeline());
        showToast("train", res?.message || "Pipeline cached");
      });
    }

    const exportBtn = document.getElementById("btn-train-export-config");
    if (exportBtn) {
      exportBtn.addEventListener("click", () => {
        const blob = new Blob([JSON.stringify(flow.getPipeline(), null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "imagebaker_train_pipeline.json";
        a.click();
        URL.revokeObjectURL(url);
        showToast("train", "Exported training pipeline JSON");
      });
    }

    const importBtn = document.getElementById("btn-train-import-config");
    const importInput = document.getElementById("input-train-import-json");
    if (importBtn && importInput) {
      importBtn.addEventListener("click", () => importInput.click());
      importInput.addEventListener("change", async e => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        try {
          const text = await file.text();
          const parsed = JSON.parse(text);
          const pipe = parsed.pipeline && Array.isArray(parsed.pipeline.nodes) ? parsed.pipeline : parsed;
          if (!Array.isArray(pipe.nodes)) {
            showToast("train", "Invalid training pipeline JSON");
            return;
          }
          flow.setPipeline(pipe);
          await api.saveTrainPipeline(pipe);
          showToast("train", `Loaded training config from ${file.name}`);
        } catch (err) {
          showToast("train", "Failed to load JSON: " + err.message);
        }
      });
    }

    const resetBtn = document.getElementById("btn-train-reset-pipeline");
    if (resetBtn) {
      resetBtn.addEventListener("click", async () => {
        const res = await api.resetTrainPipeline();
        if (res?.ok && res.pipeline) {
          flow.setPipeline(res.pipeline);
          showToast("train", res.message || "Pipeline reset");
        }
      });
    }

    const valBtn = document.getElementById("btn-train-validate");
    if (valBtn) {
      valBtn.addEventListener("click", async () => {
        const res = await api.validateTrainPipeline(flow.getPipeline());
        showToast("train", res?.message || (res?.ok ? "Pipeline valid" : "Invalid pipeline"));
      });
    }

    const runNameInput = document.getElementById("input-train-run-name");
    if (runNameInput) {
      runNameInput.addEventListener("input", () => {
        runNameManuallyEdited = Boolean(runNameInput.value.trim());
      });
    }
    const runNameAutoBtn = document.getElementById("btn-train-run-name-auto");
    if (runNameAutoBtn) {
      runNameAutoBtn.addEventListener("click", () => {
        syncAutoRunName(flow.getPipeline(), true);
      });
    }

    const startBtn = document.getElementById("btn-train-start");
    if (startBtn) {
      startBtn.addEventListener("click", async () => {
        try {
          const customName = (document.getElementById("input-train-run-name")?.value || "").trim();
          const res = await api.startTraining(flow.getPipeline(), customName);
          showToast("train", res?.message || "Training started");
          if (res?.run_id) selectedRunId = res.run_id;
          if (res?.training) renderTrainingStatus(res.training);
        } catch (err) {
          showToast("train", "Start failed: " + err.message);
        }
      });
    }

    const stopBtn = document.getElementById("btn-train-stop");
    if (stopBtn) {
      stopBtn.addEventListener("click", async () => {
        try {
          const res = await api.stopTraining();
          showToast("train", res?.message || "Training stopped");
          if (res?.training) renderTrainingStatus(res.training);
        } catch (err) {
          showToast("train", "Stop failed: " + err.message);
        }
      });
    }

    const evalBtn = document.getElementById("btn-train-run-eval");
    if (evalBtn) {
      evalBtn.addEventListener("click", async () => {
        try {
          const evalNode = (flow.getPipeline()?.nodes || []).find(n => n.type === "eval_vis");
          const ec = evalNode?.config || {};
          showToast("train", "Running post-training evaluation...");
          const res = await api.runEvalVisualization({
            run_id: lastActiveRunId,
            split: ec.split || "val",
            max_samples: ec.max_samples ?? 6,
            conf_threshold: ec.conf_threshold ?? 0.35,
            draw_ground_truth: ec.draw_ground_truth !== false,
          });
          if (res?.ok) {
            renderEvalGallery(res.eval_images || []);
            showToast("train", res.message || "Evaluation complete");
          } else {
            showToast("train", res?.message || "Evaluation failed");
          }
        } catch (err) {
          showToast("train", "Eval failed: " + err.message);
        }
      });
    }

    const trainTabBtn = document.getElementById("tab-btn-train");
    if (trainTabBtn) {
      trainTabBtn.addEventListener("click", async () => {
        setTimeout(() => flow.refreshEdges?.(), 50);
        try {
          const catRes = await api.getTrainCatalog();
          if (catRes?.ok && catRes.catalog) {
            catalog = catRes.catalog;
            flow.setDataCounts(catalog.data_counts || {});
            renderNodeInspector(flow.getSelectedNode());
          }
        } catch (_) {}
      });
    }

    const clearLogsBtn = document.getElementById("btn-train-clear-logs");
    if (clearLogsBtn) {
      clearLogsBtn.addEventListener("click", () => {
        clearedLogOffset = lastFullRawLog.length;
        const logEl = document.getElementById("train-log-box");
        if (logEl) logEl.textContent = "Logs cleared. New output will appear here...";
      });
    }

    const maxLinesSel = document.getElementById("select-train-log-lines");
    if (maxLinesSel) {
      maxLinesSel.addEventListener("change", () => {
        updateLogBoxContent(lastFullRawLog, []);
      });
    }

    // Eval Lightbox bindings (closes on backdrop click, X button, or Escape)
    const lb = document.getElementById("eval-lightbox-modal");
    if (lb) {
      lb.addEventListener("click", e => {
        if (e.target === lb) closeEvalLightbox();
      });
    }
    const lbClose = document.getElementById("btn-eval-lightbox-close");
    if (lbClose) lbClose.addEventListener("click", closeEvalLightbox);
    const lbPrev = document.getElementById("btn-eval-lightbox-prev");
    if (lbPrev) lbPrev.addEventListener("click", () => stepEvalLightbox(-1));
    const lbNext = document.getElementById("btn-eval-lightbox-next");
    if (lbNext) lbNext.addEventListener("click", () => stepEvalLightbox(1));
    const lbCmp = document.getElementById("btn-eval-lightbox-compare");
    if (lbCmp) {
      lbCmp.addEventListener("click", () => {
        const cur = currentEvalImages[lightboxIndex];
        closeEvalLightbox();
        if (window.ImageBaker?.uiCompare?.openRunInCompare && lastActiveRunId) {
          window.ImageBaker.uiCompare.openRunInCompare(lastActiveRunId, cur?.source_image || "");
        }
      });
    }
    window.addEventListener("keydown", e => {
      const modal = document.getElementById("eval-lightbox-modal");
      if (!modal || modal.classList.contains("hidden")) return;
      if (e.key === "Escape") {
        e.preventDefault();
        closeEvalLightbox();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        stepEvalLightbox(-1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        stepEvalLightbox(1);
      }
    });
  }

  function renderNodeInspector(node) {
    const container = document.getElementById("train-node-inspector");
    if (!container) return;
    container.innerHTML = "";
    if (!node) {
      container.innerHTML = `<div class="item-subtitle">Click a node on the canvas to configure its parameters.</div>`;
      return;
    }

    const cfg = node.config || {};
    const title = document.createElement("div");
    title.style.fontWeight = "700";
    title.style.marginBottom = "4px";
    title.textContent = `${node.label} (${node.type})`;
    container.appendChild(title);

    if (node.type === "data_source") {
      const dc = catalog.data_counts || { baker_states: 0, layerify_images: 0, layerify_annotated: 0 };
      const infoBox = document.createElement("div");
      infoBox.className = "inspector-info-box";
      infoBox.innerHTML = `
        <div><strong>Saved Baker States:</strong> ${dc.baker_states}</div>
        <div><strong>Layerify Images:</strong> ${dc.layerify_images} (${dc.layerify_annotated} annotated)</div>
      `;
      container.appendChild(infoBox);

      addSelect(container, "Data Source", "source", cfg.source || "layerify", [
        ["layerify", `Layerify (${dc.layerify_images} images, ${dc.layerify_annotated} annotated)`],
        ["baker", `Baker (${dc.baker_states} saved timeline states)`],
        ["hybrid", `Hybrid (Layerify ${dc.layerify_images} + Baker ${dc.baker_states})`],
      ]);
      addSelect(container, "Export Format", "export_format", cfg.export_format || "coco", [
        ["coco", "COCO (_annotations.coco.json)"],
        ["yolo", "YOLO (data.yaml)"],
        ["default", "ImageBaker Default JSON"],
      ]);
      addMultiChipSelect(
        container,
        "ROI Crop Labels (optional, empty = full image)",
        "roi_labels",
        cfg.roi_labels || [],
        catalog.labels || []
      );
      addNumber(
        container,
        "ROI Crop Padding (px)",
        "roi_padding",
        cfg.roi_padding ?? 0,
        0,
        256,
        4,
        "Extra pixel margin around each ROI crop when ROI labels are selected."
      );
    } else if (node.type === "split_filter") {
      addNumber(container, "Train Ratio", "train_ratio", cfg.train_ratio ?? 0.7, 0.1, 0.95, 0.05);
      addNumber(container, "Val Ratio", "val_ratio", cfg.val_ratio ?? 0.2, 0.05, 0.8, 0.05);
      addNumber(container, "Test Ratio", "test_ratio", cfg.test_ratio ?? 0.1, 0.0, 0.5, 0.05);
      addCheckbox(container, "Keep Validation Real-Only", "real_only_val", cfg.real_only_val !== false);
      addMultiChipSelect(
        container,
        "Selected Labels (empty = all)",
        "selected_labels",
        cfg.selected_labels || [],
        catalog.labels || []
      );
      addMultiChipSelect(
        container,
        "Annotation Types",
        "annotation_types",
        cfg.annotation_types || ["rectangle", "polygon", "brush", "point"],
        ["rectangle", "polygon", "brush", "point"]
      );
    } else if (node.type === "augmentation") {
      const augNames = Object.keys(catalog.augmentations || {});
      const curName = cfg.augmentation_name || augNames[0] || "HorizontalFlip";
      addSelect(
        container,
        "Augmentation Type",
        "augmentation_name",
        curName,
        augNames.map(n => [n, n]),
        newName => {
          const defaults = catalog.augmentations?.[newName]?.defaults || {};
          flow.updateSelectedNodeConfig({ ...defaults, augmentation_name: newName });
          renderNodeInspector(flow.getSelectedNode());
        }
      );
      const schemaProps = catalog.augmentations?.[curName]?.schema?.properties || {};
      renderSchemaFields(container, schemaProps, cfg);
    } else if (node.type === "trainer") {
      const trainerNames = Object.keys(catalog.trainers || {});
      const curTrainer = cfg.trainer_name || trainerNames[0] || "";
      addSelect(
        container,
        "Backend Trainer (--trainers-file)",
        "trainer_name",
        curTrainer,
        trainerNames.length ? trainerNames.map(n => [n, n]) : [["", "No trainers loaded"]],
        newName => {
          const defaults = catalog.trainers?.[newName]?.defaults || {};
          flow.updateSelectedNodeConfig({ ...defaults, trainer_name: newName });
          renderNodeInspector(flow.getSelectedNode());
        }
      );
      const tMeta = catalog.trainers?.[curTrainer];
      const regimes = tMeta?.supported_regimes || ["finetune", "full", "few_shot"];
      addSelect(
        container,
        "Training Regime",
        "training_mode",
        cfg.training_mode || regimes[0],
        regimes.map(r => [r, r.toUpperCase()])
      );
      const schemaProps = tMeta?.schema?.properties || {};
      renderSchemaFields(container, schemaProps, cfg, new Set(["training_mode"]));
    } else if (node.type === "output") {
      addCheckbox(container, "Auto-load trained model into Layerify", "auto_load_layerify", cfg.auto_load_layerify !== false);
    } else if (node.type === "eval_vis") {
      addSelect(container, "Evaluation Split", "split", cfg.split || "val", [
        ["val", "Validation (val / valid)"],
        ["test", "Test (test)"],
        ["train", "Train (train)"],
      ]);
      addNumber(container, "Max Visualized Samples", "max_samples", cfg.max_samples ?? 6, 1, 24, 1);
      addNumber(container, "Confidence Threshold", "conf_threshold", cfg.conf_threshold ?? 0.35, 0.05, 0.95, 0.05);
      addCheckbox(container, "Overlay Ground-Truth Boxes (Green)", "draw_ground_truth", cfg.draw_ground_truth !== false);
    }
  }

  function renderSchemaFields(container, properties, cfg, skipKeys = new Set()) {
    Object.entries(properties).forEach(([key, prop]) => {
      if (skipKeys.has(key)) return;
      const val = cfg[key] !== undefined ? cfg[key] : prop.default;
      const label = prop.title || key;
      if (prop.type === "boolean") {
        addCheckbox(container, label, key, Boolean(val), prop.description);
      } else if (prop.type === "integer" || prop.type === "number") {
        const step = prop.type === "integer" ? 1 : 0.001;
        addNumber(container, label, key, val ?? 0, prop.minimum, prop.maximum, step, prop.description);
      } else {
        addText(container, label, key, val ?? "", prop.description);
      }
    });
  }

  function addSelect(container, label, key, value, options, onCustomChange = null) {
    const wrap = document.createElement("div");
    wrap.className = "inspector-field";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    const sel = document.createElement("select");
    sel.className = "combo-box w-full";
    options.forEach(([v, text]) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = text;
      if (v === value) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", () => {
      if (onCustomChange) {
        onCustomChange(sel.value);
      } else {
        flow.updateSelectedNodeConfig({ [key]: sel.value });
      }
    });
    wrap.appendChild(lbl);
    wrap.appendChild(sel);
    container.appendChild(wrap);
  }

  function addNumber(container, label, key, value, min, max, step, desc = "") {
    const wrap = document.createElement("div");
    wrap.className = "inspector-field";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    const inp = document.createElement("input");
    inp.type = "number";
    inp.className = "text-input w-full";
    inp.value = String(value);
    if (min !== undefined) inp.min = String(min);
    if (max !== undefined) inp.max = String(max);
    if (step !== undefined) inp.step = String(step);
    inp.addEventListener("change", () => {
      const parsed = step === 1 ? parseInt(inp.value, 10) : parseFloat(inp.value);
      if (!Number.isNaN(parsed)) flow.updateSelectedNodeConfig({ [key]: parsed });
    });
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    if (desc) {
      const sm = document.createElement("small");
      sm.textContent = desc;
      wrap.appendChild(sm);
    }
    container.appendChild(wrap);
  }

  function addText(container, label, key, value, desc = "") {
    const wrap = document.createElement("div");
    wrap.className = "inspector-field";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    const inp = document.createElement("input");
    inp.type = "text";
    inp.className = "text-input w-full";
    inp.value = String(value);
    inp.addEventListener("change", () => flow.updateSelectedNodeConfig({ [key]: inp.value }));
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    if (desc) {
      const sm = document.createElement("small");
      sm.textContent = desc;
      wrap.appendChild(sm);
    }
    container.appendChild(wrap);
  }

  function addCheckbox(container, label, key, checked, desc = "") {
    const wrap = document.createElement("div");
    wrap.className = "inspector-field";
    const row = document.createElement("label");
    row.className = "inspector-checkbox-row";
    const inp = document.createElement("input");
    inp.type = "checkbox";
    inp.checked = Boolean(checked);
    inp.addEventListener("change", () => flow.updateSelectedNodeConfig({ [key]: inp.checked }));
    const span = document.createElement("span");
    span.textContent = label;
    row.appendChild(inp);
    row.appendChild(span);
    wrap.appendChild(row);
    if (desc) {
      const sm = document.createElement("small");
      sm.textContent = desc;
      wrap.appendChild(sm);
    }
    container.appendChild(wrap);
  }

  function addMultiChipSelect(container, label, key, selectedList, allOptions) {
    const wrap = document.createElement("div");
    wrap.className = "inspector-field";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    const grp = document.createElement("div");
    grp.className = "inspector-chip-group";
    const current = new Set(selectedList || []);
    (allOptions || []).forEach(opt => {
      const chip = document.createElement("label");
      chip.className = "inspector-chip";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = current.has(opt);
      cb.addEventListener("change", () => {
        if (cb.checked) current.add(opt);
        else current.delete(opt);
        flow.updateSelectedNodeConfig({ [key]: Array.from(current) });
      });
      const txt = document.createElement("span");
      txt.textContent = opt;
      chip.appendChild(cb);
      chip.appendChild(txt);
      grp.appendChild(chip);
    });
    wrap.appendChild(lbl);
    wrap.appendChild(grp);
    container.appendChild(wrap);
  }

  function updateLogBoxContent(rawLogs, metricsHistory) {
    const logEl = document.getElementById("train-log-box");
    if (!logEl) return;
    const histLines = (metricsHistory || [])
      .map(m => m.message || JSON.stringify(m.metrics || {}))
      .filter(Boolean);
    const fullText = (rawLogs || "").trim() || (histLines.length ? histLines.join("\n") : "");
    lastFullRawLog = fullText;

    const sliced = clearedLogOffset > 0 ? fullText.slice(clearedLogOffset).trimStart() : fullText;
    const maxLines = Math.max(50, parseInt(document.getElementById("select-train-log-lines")?.value || "300", 10));
    let nextText = sliced;
    if (!nextText) {
      nextText = clearedLogOffset > 0 ? "Logs cleared. Waiting for new output..." : "No training logs yet.";
    } else {
      const lines = nextText.split(/\r?\n/);
      if (lines.length > maxLines) {
        const trimmed = lines.slice(-maxLines);
        nextText = `... (auto-trimmed: showing last ${maxLines} of ${lines.length} lines)\n` + trimmed.join("\n");
      }
    }

    if (logEl.textContent !== nextText) {
      const wasAtBottom =
        !logEl.dataset.initialized ||
        (logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight) < 28;
      const prevScrollTop = logEl.scrollTop;
      logEl.textContent = nextText;
      logEl.dataset.initialized = "1";
      if (wasAtBottom) {
        logEl.scrollTop = logEl.scrollHeight;
      } else {
        logEl.scrollTop = prevScrollTop;
      }
    }
  }

  function renderTrainingStatus(training) {
    const statusEl = document.getElementById("train-status-text");
    const fillEl = document.getElementById("train-progress-fill");
    const startBtn = document.getElementById("btn-train-start");
    const stopBtn = document.getElementById("btn-train-stop");

    if (training.active_run_id && training.active_run_id !== lastLogRunId) {
      lastLogRunId = training.active_run_id;
      clearedLogOffset = 0;
    }

    const latest = training.latest || {};
    const ep = latest.epoch || 0;
    const tot = latest.total_epochs || 0;
    const pct = tot > 0 ? Math.min(100, Math.round((ep / tot) * 100)) : (training.status === "completed" ? 100 : 0);

    if (statusEl) {
      statusEl.textContent = `${(training.status || "idle").toUpperCase()}${tot ? ` — Epoch ${ep}/${tot}` : ""}${latest.message ? ` • ${latest.message}` : ""}`;
    }
    if (fillEl) fillEl.style.width = `${pct}%`;
    if (startBtn) startBtn.disabled = Boolean(training.is_running);
    if (stopBtn) stopBtn.disabled = !training.is_running;

    updateLogBoxContent(training.logs || "", training.metrics_history || []);

    lastActiveRunId = training.active_run_id || lastActiveRunId;
    drawMetricsChart(training.metrics_history || [], training.logs || "");
    renderRunHistory(training.runs || []);
    renderEvalGallery(training.eval_images || []);
  }

  function openEvalLightbox(index) {
    if (!currentEvalImages.length) return;
    lightboxIndex = Math.max(0, Math.min(currentEvalImages.length - 1, index));
    const item = currentEvalImages[lightboxIndex];
    const modal = document.getElementById("eval-lightbox-modal");
    const img = document.getElementById("eval-lightbox-img");
    const title = document.getElementById("eval-lightbox-title");
    const meta = document.getElementById("eval-lightbox-meta");
    if (img) img.src = item.url;
    if (title) title.textContent = `${item.source_image} (${lightboxIndex + 1}/${currentEvalImages.length})`;
    if (meta) meta.textContent = `${String(item.split || "val").toUpperCase()} • GT: ${item.num_gt ?? 0} • Pred: ${item.num_preds ?? 0}`;
    if (modal) modal.classList.remove("hidden");
  }

  function closeEvalLightbox() {
    const modal = document.getElementById("eval-lightbox-modal");
    if (modal) modal.classList.add("hidden");
  }

  function stepEvalLightbox(delta) {
    if (!currentEvalImages.length) return;
    openEvalLightbox((lightboxIndex + delta + currentEvalImages.length) % currentEvalImages.length);
  }

  function renderEvalGallery(evalImages) {
    const gallery = document.getElementById("train-eval-gallery");
    if (!gallery) return;
    const list = Array.isArray(evalImages) ? evalImages : [];
    currentEvalImages = list;
    if (!list.length) {
      gallery.classList.add("hidden");
      gallery.innerHTML = "";
      return;
    }
    gallery.classList.remove("hidden");
    gallery.innerHTML = "";
    list.forEach((item, idx) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "eval-thumb-card";
      card.title = `${item.source_image} (${item.split}) — GT: ${item.num_gt}, Preds: ${item.num_preds} (Click to inspect)`;
      card.innerHTML = `
        <img class="eval-thumb-img" src="${item.url}" alt="${item.source_image}" loading="lazy" />
        <div class="eval-thumb-meta">${item.source_image}</div>
        <div class="eval-thumb-meta">${String(item.split || "val").toUpperCase()} • GT:${item.num_gt ?? 0} Pred:${item.num_preds ?? 0}</div>
      `;
      card.addEventListener("click", () => openEvalLightbox(idx));
      gallery.appendChild(card);
    });
  }

  function drawMetricsChart(history, rawLogs = "") {
    const canvas = document.getElementById("train-chart-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Subtle horizontal gridlines
    ctx.strokeStyle = "rgba(148, 163, 184, 0.16)";
    ctx.lineWidth = 1;
    [0.25, 0.5, 0.75].forEach(frac => {
      const y = Math.round(18 + frac * (h - 28));
      ctx.beginPath();
      ctx.moveTo(8, y);
      ctx.lineTo(w - 8, y);
      ctx.stroke();
    });

    const lossVals = [];
    const mapVals = [];
    (history || []).forEach(ev => {
      const m = ev?.metrics || {};
      if (typeof m.loss === "number" && Number.isFinite(m.loss)) lossVals.push(m.loss);
      else if (typeof m.train_loss === "number" && Number.isFinite(m.train_loss)) lossVals.push(m.train_loss);
      if (typeof m.map50 === "number" && Number.isFinite(m.map50)) mapVals.push(m.map50);
    });

    // Fallback: parse loss= / mAP@50 from raw stdout logs if trainer didn't emit structured metrics
    if (lossVals.length === 0 && rawLogs) {
      const lossMatches = rawLogs.matchAll(/\bloss=([0-9]+(?:\.[0-9]+)?)/g);
      for (const m of lossMatches) {
        const v = parseFloat(m[1]);
        if (Number.isFinite(v)) lossVals.push(v);
      }
    }
    if (mapVals.length === 0 && rawLogs) {
      const mapMatches = rawLogs.matchAll(/mAP@50\b[^0-9]*([0-9]+(?:\.[0-9]+)?)/g);
      for (const m of mapMatches) {
        const v = parseFloat(m[1]);
        if (Number.isFinite(v)) mapVals.push(v > 1 ? v / 100 : v);
      }
    }

    if (lossVals.length < 1 && mapVals.length < 1) {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "11px sans-serif";
      ctx.fillText("Metrics chart (loss / mAP50)", 10, 22);
      return;
    }

    const padX = 10;
    const padTop = 20;
    const padBot = 10;
    const plotH = Math.max(10, h - padTop - padBot);

    // Legend header
    const legendParts = [];
    if (lossVals.length) legendParts.push(`Loss: ${lossVals[lossVals.length - 1].toFixed(3)}`);
    if (mapVals.length) legendParts.push(`mAP50: ${mapVals[mapVals.length - 1].toFixed(3)}`);
    ctx.font = "bold 10px monospace";
    ctx.fillStyle = "#f59e0b";
    ctx.fillText(legendParts[0] || "", padX, 12);
    if (legendParts[1]) {
      ctx.fillStyle = "#10b981";
      ctx.fillText(legendParts[1], padX + 108, 12);
    }

    if (lossVals.length >= 1) {
      const maxL = Math.max(...lossVals);
      const minL = Math.min(...lossVals);
      const span = Math.max(1e-4, maxL - minL);
      ctx.strokeStyle = "#f59e0b";
      ctx.lineWidth = 2;
      ctx.beginPath();
      lossVals.forEach((v, idx) => {
        const x = padX + (idx / Math.max(1, lossVals.length - 1)) * (w - padX * 2);
        const y = h - padBot - ((v - minL) / span) * plotH;
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    if (mapVals.length >= 1) {
      ctx.strokeStyle = "#10b981";
      ctx.lineWidth = 2;
      ctx.beginPath();
      mapVals.forEach((v, idx) => {
        const x = padX + (idx / Math.max(1, mapVals.length - 1)) * (w - padX * 2);
        const y = h - padBot - Math.max(0, Math.min(1, v)) * plotH;
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
  }

  function renderRunHistory(runs) {
    const container = document.getElementById("train-runs-list");
    if (!container) return;
    container.innerHTML = "";
    if (!runs.length) {
      container.innerHTML = `<div class="item-subtitle">No training runs yet.</div>`;
      return;
    }
    const activeId = selectedRunId || lastActiveRunId;
    runs.forEach(run => {
      const row = document.createElement("div");
      row.className = "run-item" + (run.run_id === activeId ? " selected" : "");
      row.title = "Click to view this run's metrics, logs, and eval results";
      row.innerHTML = `
        <div class="run-item-row">
          <strong class="run-item-name" title="${run.run_id}">${run.run_name || run.run_id}</strong>
          <span class="dock-badge">${run.status}</span>
        </div>
        <div class="item-subtitle">${run.trainer_name} (${run.training_mode || "default"})</div>
      `;

      row.addEventListener("click", async e => {
        if (e.target.closest("button")) return;
        selectedRunId = run.run_id;
        clearedLogOffset = 0;
        try {
          const res = await api.getTrainStatus(run.run_id);
          if (res?.ok && res.training) {
            renderTrainingStatus(res.training);
            showToast("train", `Viewing run: ${run.run_id}`);
          }
        } catch (err) {
          showToast("train", "Failed to load run: " + err.message);
        }
      });

      const actions = document.createElement("div");
      actions.className = "run-item-actions";

      if (run.has_pipeline) {
        const pipeBtn = document.createElement("button");
        pipeBtn.type = "button";
        pipeBtn.className = "btn btn-xs";
        pipeBtn.textContent = "📥 Pipeline";
        pipeBtn.title = "Restore this run's pipeline graph onto the canvas";
        pipeBtn.addEventListener("click", async e => {
          e.stopPropagation();
          try {
            const res = await api.getTrainRunPipeline(run.run_id);
            if (res?.ok && res.pipeline) {
              flow.setPipeline(res.pipeline);
              syncAutoRunName(res.pipeline, true);
              showToast("train", `Loaded pipeline from ${run.run_id}`);
            }
          } catch (err) {
            showToast("train", "Could not load pipeline: " + err.message);
          }
        });
        actions.appendChild(pipeBtn);
      }

      if (run.has_eval) {
        const cmpBtn = document.createElement("button");
        cmpBtn.type = "button";
        cmpBtn.className = "btn btn-xs";
        cmpBtn.textContent = "⚖️ Compare";
        cmpBtn.title = "Open this run's eval images in the Compare tab";
        cmpBtn.addEventListener("click", e => {
          e.stopPropagation();
          window.ImageBaker?.uiCompare?.openRunInCompare?.(run.run_id);
        });
        actions.appendChild(cmpBtn);
      }

      if (run.checkpoint_path) {
        const loadBtn = document.createElement("button");
        loadBtn.type = "button";
        loadBtn.className = "btn btn-xs btn-primary";
        loadBtn.textContent = "🔮 Load";
        loadBtn.title = "Load trained checkpoint into Layerify";
        loadBtn.addEventListener("click", async e => {
          e.stopPropagation();
          const res = await api.loadTrainedModel(run.run_id);
          if (res?.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            showToast("train", res.message || "Loaded into Layerify");
          } else {
            showToast("train", res?.message || "Could not load model");
          }
        });
        actions.appendChild(loadBtn);
      }

      if (run.status !== "running") {
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "btn btn-xs";
        delBtn.textContent = "🗑️";
        delBtn.title = `Delete run ${run.run_id}`;
        delBtn.addEventListener("click", async e => {
          e.stopPropagation();
          if (!window.confirm(`Delete training run "${run.run_id}" from disk?`)) return;
          try {
            const res = await api.deleteTrainRun(run.run_id);
            if (res?.ok) {
              if (selectedRunId === run.run_id) selectedRunId = null;
              if (res.training) renderTrainingStatus(res.training);
              showToast("train", res.message || `Deleted ${run.run_id}`);
            } else {
              showToast("train", res?.message || "Delete failed");
            }
          } catch (err) {
            showToast("train", "Delete failed: " + err.message);
          }
        });
        actions.appendChild(delBtn);
      }

      row.appendChild(actions);
      container.appendChild(row);
    });
  }

  function startStatusPolling() {
    if (statusPoller) clearInterval(statusPoller);
    statusPoller = setInterval(async () => {
      if (window.ImageBaker?.state?.active_tab !== "Train") return;
      try {
        const res = await api.getTrainStatus(selectedRunId);
        if (res?.ok && res.training) {
          renderTrainingStatus(res.training);
        }
      } catch (_) {}
    }, 1500);
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.uiTrain = {
    initTrainUI,
    loadCatalogAndPipeline,
    renderTrainingStatus,
  };
})(window);
