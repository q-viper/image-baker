/**
 * ImageBaker Web - Train Tab UI Controller (Schema Inspector, Live Metrics & Runs)
 */
(function(window) {
  "use strict";

  const api = window.ImageBaker.api;
  const flow = window.ImageBaker.trainFlow;
  const { showToast } = window.ImageBaker;

  let catalog = { trainers: {}, augmentations: {}, device_info: "cpu", labels: [] };
  let statusPoller = null;
  let hoverPreviewTimer = null;
  let autoCacheTimer = null;

  function scheduleAutoCachePipeline(pipeline) {
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

  function handleNodeHover(node) {
    clearTimeout(hoverPreviewTimer);
    if (!node || node.type === "output") return;
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
        const devBadge = document.getElementById("train-device-badge");
        if (devBadge) devBadge.textContent = `Device: ${catalog.device_info || "cpu"}`;
      }
      if (pipeRes?.ok && pipeRes.pipeline) {
        flow.setPipeline(pipeRes.pipeline);
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
      ["btn-add-node-data", "data_source", "Layerify Local", { source: "layerify", num_synthetic_samples: 0, export_format: "yolo" }],
      ["btn-add-node-baker-data", "data_source", "Baker Synthetic", { source: "baker", num_synthetic_samples: 20, export_format: "yolo" }],
      ["btn-add-node-split", "split_filter", "Split & Filter", { train_ratio: 0.7, val_ratio: 0.2, test_ratio: 0.1, real_only_val: true, selected_labels: [], annotation_types: ["rectangle", "polygon", "brush", "point"] }],
      ["btn-add-node-aug", "augmentation", "HorizontalFlip", { augmentation_name: "HorizontalFlip", enabled: true, probability: 0.5 }],
      ["btn-add-node-trainer", "trainer", "Model Trainer", { trainer_name: Object.keys(catalog.trainers || {})[0] || "", training_mode: "finetune", epochs: 5, batch_size: 4 }],
      ["btn-add-node-output", "output", "Checkpoint & Layerify", { auto_load_layerify: true }],
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

    const startBtn = document.getElementById("btn-train-start");
    if (startBtn) {
      startBtn.addEventListener("click", async () => {
        try {
          const res = await api.startTraining(flow.getPipeline());
          showToast("train", res?.message || "Training started");
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
      addSelect(container, "Data Source", "source", cfg.source || "hybrid", [
        ["hybrid", "Hybrid (Layerify Real + Baker Synthetic)"],
        ["layerify", "Layerify (Real Annotated Images)"],
        ["baker", "Baker (Synthetic Cache Only)"],
      ]);
      addNumber(container, "Synthetic Samples", "num_synthetic_samples", cfg.num_synthetic_samples ?? 20, 2, 10000, 1);
      addSelect(container, "Export Format", "export_format", cfg.export_format || "yolo", [
        ["yolo", "YOLO (data.yaml)"],
        ["coco", "COCO (.json)"],
        ["default", "ImageBaker Default JSON"],
      ]);
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

  function renderTrainingStatus(training) {
    const statusEl = document.getElementById("train-status-text");
    const fillEl = document.getElementById("train-progress-fill");
    const logEl = document.getElementById("train-log-box");
    const startBtn = document.getElementById("btn-train-start");
    const stopBtn = document.getElementById("btn-train-stop");

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

    if (logEl) {
      const histLines = (training.metrics_history || [])
        .map(m => m.message || JSON.stringify(m.metrics || {}))
        .filter(Boolean);
      logEl.textContent = histLines.length ? histLines.join("\n") : (training.logs || "No training logs yet.");
      logEl.scrollTop = logEl.scrollHeight;
    }

    drawMetricsChart(training.metrics_history || []);
    renderRunHistory(training.runs || []);
  }

  function drawMetricsChart(history) {
    const canvas = document.getElementById("train-chart-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const pts = history.filter(ev => ev.metrics && typeof ev.metrics.loss === "number");
    if (pts.length < 1) {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "11px sans-serif";
      ctx.fillText("Metrics chart (loss / mAP50)", 10, 22);
      return;
    }
    const losses = pts.map(p => p.metrics.loss);
    const maxL = Math.max(...losses, 1e-4);
    const minL = Math.min(...losses, 0);
    const pad = 12;

    ctx.strokeStyle = "#f59e0b";
    ctx.lineWidth = 2;
    ctx.beginPath();
    pts.forEach((p, idx) => {
      const x = pad + (idx / Math.max(1, pts.length - 1)) * (w - pad * 2);
      const y = h - pad - ((p.metrics.loss - minL) / Math.max(1e-4, maxL - minL)) * (h - pad * 2);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const maps = pts.filter(p => typeof p.metrics.map50 === "number");
    if (maps.length >= 1) {
      ctx.strokeStyle = "#10b981";
      ctx.lineWidth = 2;
      ctx.beginPath();
      maps.forEach((p, idx) => {
        const x = pad + (idx / Math.max(1, maps.length - 1)) * (w - pad * 2);
        const y = h - pad - Math.max(0, Math.min(1, p.metrics.map50)) * (h - pad * 2);
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
    runs.forEach(run => {
      const row = document.createElement("div");
      row.className = "run-item";
      row.innerHTML = `
        <div class="run-item-row">
          <strong>${run.run_id}</strong>
          <span class="dock-badge">${run.status}</span>
        </div>
        <div class="item-subtitle">${run.trainer_name} (${run.training_mode || "default"})</div>
      `;
      if (run.checkpoint_path) {
        const btn = document.createElement("button");
        btn.className = "btn btn-xs btn-primary";
        btn.textContent = "🔮 Load in Layerify";
        btn.addEventListener("click", async () => {
          const res = await api.loadTrainedModel(run.run_id);
          if (res?.ok && res.state) {
            window.ImageBaker.applyServerState(res.state);
            showToast("train", res.message || "Loaded into Layerify");
          } else {
            showToast("train", res?.message || "Could not load model");
          }
        });
        row.appendChild(btn);
      }
      container.appendChild(row);
    });
  }

  function startStatusPolling() {
    if (statusPoller) clearInterval(statusPoller);
    statusPoller = setInterval(async () => {
      if (window.ImageBaker?.state?.active_tab !== "Train") return;
      try {
        const res = await api.getTrainStatus();
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
