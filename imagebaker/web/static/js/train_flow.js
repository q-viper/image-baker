/**
 * ImageBaker Web - Lightweight ReactFlow-Style Visual Pipeline Editor
 */
(function(window) {
  "use strict";

  let viewportEl = null;
  let stageEl = null;
  let svgEl = null;
  let nodesEl = null;

  const flowState = {
    nodes: [],
    edges: [],
    selectedNodeId: null,
    selectedEdgeId: null,
    panX: 20,
    panY: 20,
    zoom: 1.0,
    isPanning: false,
    panStart: null,
    draggingNode: null,
    connectingFrom: null,
    draftMouse: null,
    onSelectChange: null,
    onGraphChange: null,
    onNodeHover: null,
    onNodeLeave: null,
    dataCounts: { baker_states: 0, layerify_images: 0, layerify_annotated: 0 },
  };

  function initFlow(options = {}) {
    viewportEl = document.getElementById("train-flow-viewport");
    stageEl = document.getElementById("train-flow-stage");
    svgEl = document.getElementById("train-flow-edges");
    nodesEl = document.getElementById("train-flow-nodes");
    if (!viewportEl || !stageEl || !svgEl || !nodesEl) return;

    flowState.onSelectChange = options.onSelectChange || null;
    flowState.onGraphChange = options.onGraphChange || null;
    flowState.onNodeHover = options.onNodeHover || null;
    flowState.onNodeLeave = options.onNodeLeave || null;

    bindViewportEvents();
    applyTransform();

    if (window.ResizeObserver && viewportEl) {
      new ResizeObserver(() => renderEdges()).observe(viewportEl);
    }
  }

  function setPipeline(pipeline) {
    flowState.nodes = structuredClone(pipeline?.nodes || []);
    flowState.edges = structuredClone(pipeline?.edges || []);
    if (flowState.selectedNodeId && !flowState.nodes.some(n => n.id === flowState.selectedNodeId)) {
      flowState.selectedNodeId = null;
    }
    render();
    notifySelect();
  }

  function getPipeline() {
    return {
      nodes: structuredClone(flowState.nodes),
      edges: structuredClone(flowState.edges),
    };
  }

  function getSelectedNode() {
    return flowState.nodes.find(n => n.id === flowState.selectedNodeId) || null;
  }

  function addNode(type, label, config = {}) {
    const id = `node_${Date.now().toString(36)}_${Math.floor(Math.random() * 999)}`;
    const maxX = flowState.nodes.reduce((m, n) => Math.max(m, n.x || 0), 40);
    const node = {
      id,
      type,
      label,
      x: Math.min(maxX + 60, 1100),
      y: 120 + (flowState.nodes.length % 4) * 55,
      config: structuredClone(config),
    };
    flowState.nodes.push(node);
    flowState.selectedNodeId = id;
    flowState.selectedEdgeId = null;
    render();
    notifySelect();
    notifyChange();
    return node;
  }

  function deleteSelection() {
    if (flowState.selectedNodeId) {
      const nid = flowState.selectedNodeId;
      flowState.nodes = flowState.nodes.filter(n => n.id !== nid);
      flowState.edges = flowState.edges.filter(e => e.source !== nid && e.target !== nid);
      flowState.selectedNodeId = null;
      render();
      notifySelect();
      notifyChange();
    } else if (flowState.selectedEdgeId) {
      const eid = flowState.selectedEdgeId;
      flowState.edges = flowState.edges.filter(e => e.id !== eid);
      flowState.selectedEdgeId = null;
      render();
      notifyChange();
    }
  }

  function setDataCounts(counts) {
    flowState.dataCounts = {
      baker_states: Number(counts?.baker_states || 0),
      layerify_images: Number(counts?.layerify_images || 0),
      layerify_annotated: Number(counts?.layerify_annotated || 0),
    };
    render();
  }

  function autoLayout() {
    const order = ["data_source", "split_filter", "augmentation", "trainer", "sink"];
    const groups = new Map();
    order.forEach(t => groups.set(t, []));
    flowState.nodes.forEach(n => {
      const key = (n.type === "output" || n.type === "eval_vis")
        ? "sink"
        : (groups.has(n.type) ? n.type : "augmentation");
      groups.get(key).push(n);
    });
    let col = 0;
    order.forEach(t => {
      const list = groups.get(t);
      if (!list.length) return;
      list.forEach((n, rowIdx) => {
        n.x = 50 + col * 255;
        n.y = 80 + rowIdx * 135;
      });
      col++;
    });
    flowState.panX = 16;
    flowState.panY = 16;
    flowState.zoom = 1.0;
    applyTransform();
    render();
    notifyChange();
  }

  function updateSelectedNodeConfig(patch) {
    const node = getSelectedNode();
    if (!node) return;
    node.config = { ...(node.config || {}), ...patch };
    if (patch.augmentation_name && node.type === "augmentation") {
      node.label = patch.augmentation_name;
    }
    if (patch.trainer_name && node.type === "trainer") {
      node.label = patch.trainer_name;
    }
    render();
    notifyChange();
  }

  function applyTransform() {
    if (!stageEl) return;
    stageEl.style.transform = `translate(${flowState.panX}px, ${flowState.panY}px) scale(${flowState.zoom})`;
  }

  function screenToStage(clientX, clientY) {
    const rect = viewportEl.getBoundingClientRect();
    return {
      x: (clientX - rect.left - flowState.panX) / flowState.zoom,
      y: (clientY - rect.top - flowState.panY) / flowState.zoom,
    };
  }

  function nodeSummaryLines(node) {
    const c = node.config || {};
    const dc = flowState.dataCounts || { baker_states: 0, layerify_images: 0, layerify_annotated: 0 };
    if (node.type === "data_source") {
      const src = c.source || "layerify";
      let countLine = `Layerify: ${dc.layerify_images} imgs (${dc.layerify_annotated} ann)`;
      if (src === "baker") {
        countLine = `Baker States: ${dc.baker_states} available`;
      } else if (src === "hybrid") {
        countLine = `Baker: ${dc.baker_states} • Layerify: ${dc.layerify_images}`;
      }
      const lines = [
        countLine,
        `Format: ${(c.export_format || "coco").toUpperCase()}`,
      ];
      if (Array.isArray(c.roi_labels) && c.roi_labels.length) {
        lines.push(`ROI Crop: ${c.roi_labels.join(", ")}`);
      }
      return lines;
    }
    if (node.type === "split_filter") {
      return [
        `Train/Val/Test: ${c.train_ratio ?? 0.7}/${c.val_ratio ?? 0.2}/${c.test_ratio ?? 0.1}`,
        c.real_only_val ? "Real-only Val: On" : "Real-only Val: Off",
      ];
    }
    if (node.type === "augmentation") {
      return [
        `Prob: ${c.probability ?? 0.5}`,
        c.enabled === false ? "Disabled" : "Enabled",
      ];
    }
    if (node.type === "trainer") {
      return [
        `Mode: ${c.training_mode || "finetune"}`,
        `Epochs: ${c.epochs ?? 10} • BS: ${c.batch_size ?? 8}`,
      ];
    }
    if (node.type === "eval_vis") {
      return [
        `Split: ${(c.split || "val").toUpperCase()} • Max: ${c.max_samples ?? 6}`,
        `Conf ≥ ${c.conf_threshold ?? 0.35}${c.draw_ground_truth !== false ? " • +GT" : ""}`,
      ];
    }
    return [c.auto_load_layerify ? "Auto-load in Layerify" : "Save checkpoint"];
  }

  function render() {
    if (!nodesEl || !svgEl) return;
    nodesEl.innerHTML = "";

    flowState.nodes.forEach(node => {
      const el = document.createElement("div");
      el.className = "flow-node" + (node.id === flowState.selectedNodeId ? " selected" : "");
      el.dataset.nodeId = node.id;
      el.dataset.type = node.type;
      el.style.left = `${node.x || 0}px`;
      el.style.top = `${node.y || 0}px`;

      const header = document.createElement("div");
      header.className = "flow-node-header";
      header.innerHTML = `<span>${escapeHtml(node.label || node.type)}</span><span style="opacity:0.8;font-size:10px;">${escapeHtml(node.type.replace("_", " "))}</span>`;

      const body = document.createElement("div");
      body.className = "flow-node-body";
      nodeSummaryLines(node).forEach(line => {
        const span = document.createElement("span");
        span.className = "flow-node-badge";
        span.textContent = line;
        body.appendChild(span);
      });

      el.appendChild(header);
      el.appendChild(body);

      function finishConnectionTo(targetNode) {
        if (!flowState.connectingFrom || flowState.connectingFrom.nodeId === targetNode.id) return;
        const from = flowState.connectingFrom;
        let srcId = from.side === "out" ? from.nodeId : targetNode.id;
        let tgtId = from.side === "out" ? targetNode.id : from.nodeId;
        const srcNode = flowState.nodes.find(n => n.id === srcId);
        const tgtNode = flowState.nodes.find(n => n.id === tgtId);
        if (!srcNode || !tgtNode || tgtNode.type === "data_source" || srcNode.type === "output" || srcNode.type === "eval_vis") {
          return;
        }
        const exists = flowState.edges.some(ed => ed.source === srcId && ed.target === tgtId);
        if (!exists) {
          flowState.edges.push({
            id: `edge_${Date.now().toString(36)}_${Math.floor(Math.random() * 999)}`,
            source: srcId,
            target: tgtId,
          });
          notifyChange();
        }
      }

      if (node.type !== "data_source") {
        const portIn = document.createElement("div");
        portIn.className = "flow-port flow-port-in";
        portIn.title = "Input port (drop connection here or drag to an output port)";
        portIn.addEventListener("pointerdown", e => {
          e.stopPropagation();
          flowState.connectingFrom = { nodeId: node.id, side: "in" };
          flowState.draftMouse = screenToStage(e.clientX, e.clientY);
          renderEdges();
        });
        portIn.addEventListener("pointerup", e => {
          e.stopPropagation();
          finishConnectionTo(node);
          flowState.connectingFrom = null;
          flowState.draftMouse = null;
          renderEdges();
        });
        el.appendChild(portIn);
      }

      if (node.type !== "output" && node.type !== "eval_vis") {
        const portOut = document.createElement("div");
        portOut.className = "flow-port flow-port-out";
        portOut.title = "Output port (drag to connect to next node)";
        portOut.addEventListener("pointerdown", e => {
          e.stopPropagation();
          flowState.connectingFrom = { nodeId: node.id, side: "out" };
          flowState.draftMouse = screenToStage(e.clientX, e.clientY);
          renderEdges();
        });
        portOut.addEventListener("pointerup", e => {
          e.stopPropagation();
          finishConnectionTo(node);
          flowState.connectingFrom = null;
          flowState.draftMouse = null;
          renderEdges();
        });
        el.appendChild(portOut);
      }

      // Also allow dropping a wire anywhere on the target node body for effortless connecting
      el.addEventListener("pointerup", e => {
        if (!flowState.connectingFrom) return;
        e.stopPropagation();
        finishConnectionTo(node);
        flowState.connectingFrom = null;
        flowState.draftMouse = null;
        renderEdges();
      });

      el.addEventListener("pointerdown", e => {
        if (e.target.classList.contains("flow-port")) return;
        e.stopPropagation();
        flowState.selectedNodeId = node.id;
        flowState.selectedEdgeId = null;
        const pt = screenToStage(e.clientX, e.clientY);
        flowState.draggingNode = {
          node,
          offsetX: pt.x - (node.x || 0),
          offsetY: pt.y - (node.y || 0),
        };
        render();
        notifySelect();
      });

      header.addEventListener("mouseenter", () => {
        if (!flowState.draggingNode && !flowState.connectingFrom && flowState.onNodeHover) {
          flowState.onNodeHover(node);
        }
      });
      header.addEventListener("mouseleave", () => {
        if (flowState.onNodeLeave) {
          flowState.onNodeLeave(node);
        }
      });

      nodesEl.appendChild(el);
    });

    renderEdges();
  }

  function getPortPos(nodeId, side) {
    const node = flowState.nodes.find(n => n.id === nodeId);
    if (!node) return null;
    const nodeEl = nodesEl?.querySelector(`.flow-node[data-node-id="${CSS.escape(String(nodeId))}"]`);
    const w = nodeEl && nodeEl.offsetWidth > 0 ? nodeEl.offsetWidth : 205;
    const h = nodeEl && nodeEl.offsetHeight > 0 ? nodeEl.offsetHeight : 84;
    return {
      x: (node.x || 0) + (side === "out" ? w : 0),
      y: (node.y || 0) + h / 2,
    };
  }

  function bezierPath(p1, p2) {
    const dx = Math.max(45, Math.abs(p2.x - p1.x) * 0.5);
    return `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;
  }

  function renderEdges() {
    if (!svgEl) return;
    svgEl.innerHTML = "";
    const ns = "http://www.w3.org/2000/svg";

    // Arrowhead marker so pipeline flow direction is always clear
    const defs = document.createElementNS(ns, "defs");
    const marker = document.createElementNS(ns, "marker");
    marker.setAttribute("id", "flow-arrow");
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "8");
    marker.setAttribute("refY", "5");
    marker.setAttribute("markerWidth", "6");
    marker.setAttribute("markerHeight", "6");
    marker.setAttribute("orient", "auto");
    const arrowPath = document.createElementNS(ns, "path");
    arrowPath.setAttribute("d", "M 0 1.5 L 10 5 L 0 8.5 z");
    arrowPath.setAttribute("fill", "#60a5fa");
    marker.appendChild(arrowPath);
    defs.appendChild(marker);
    svgEl.appendChild(defs);

    flowState.edges.forEach(edge => {
      const p1 = getPortPos(edge.source, "out");
      const p2 = getPortPos(edge.target, "in");
      if (!p1 || !p2) return;
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", bezierPath(p1, p2));
      path.setAttribute("marker-end", "url(#flow-arrow)");
      path.setAttribute(
        "class",
        "flow-edge-path" + (edge.id === flowState.selectedEdgeId ? " selected" : "")
      );
      path.addEventListener("pointerdown", e => {
        e.stopPropagation();
        flowState.selectedEdgeId = edge.id;
        flowState.selectedNodeId = null;
        render();
        notifySelect();
      });
      svgEl.appendChild(path);
    });

    if (flowState.connectingFrom && flowState.draftMouse) {
      const p1 = getPortPos(flowState.connectingFrom.nodeId, flowState.connectingFrom.side);
      if (p1) {
        const draft = document.createElementNS(ns, "path");
        const dStr = flowState.connectingFrom.side === "out"
          ? bezierPath(p1, flowState.draftMouse)
          : bezierPath(flowState.draftMouse, p1);
        draft.setAttribute("d", dStr);
        draft.setAttribute("class", "flow-edge-draft");
        svgEl.appendChild(draft);
      }
    }
  }

  function bindViewportEvents() {
    viewportEl.addEventListener("pointerdown", e => {
      if (e.target.closest(".flow-node") || e.target.classList.contains("flow-edge-path")) return;
      flowState.selectedNodeId = null;
      flowState.selectedEdgeId = null;
      flowState.isPanning = true;
      flowState.panStart = { x: e.clientX - flowState.panX, y: e.clientY - flowState.panY };
      viewportEl.classList.add("panning");
      render();
      notifySelect();
    });

    window.addEventListener("pointermove", e => {
      if (flowState.draggingNode) {
        const pt = screenToStage(e.clientX, e.clientY);
        flowState.draggingNode.node.x = Math.round(pt.x - flowState.draggingNode.offsetX);
        flowState.draggingNode.node.y = Math.round(pt.y - flowState.draggingNode.offsetY);
        render();
        return;
      }
      if (flowState.connectingFrom) {
        flowState.draftMouse = screenToStage(e.clientX, e.clientY);
        renderEdges();
        return;
      }
      if (flowState.isPanning && flowState.panStart) {
        flowState.panX = e.clientX - flowState.panStart.x;
        flowState.panY = e.clientY - flowState.panStart.y;
        applyTransform();
      }
    });

    window.addEventListener("pointerup", () => {
      if (flowState.draggingNode) {
        flowState.draggingNode = null;
        notifyChange();
      }
      if (flowState.connectingFrom) {
        flowState.connectingFrom = null;
        flowState.draftMouse = null;
        renderEdges();
      }
      if (flowState.isPanning) {
        flowState.isPanning = false;
        flowState.panStart = null;
        viewportEl.classList.remove("panning");
      }
    });

    viewportEl.addEventListener("wheel", e => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
      flowState.zoom = Math.max(0.35, Math.min(2.0, flowState.zoom * factor));
      applyTransform();
    }, { passive: false });

    window.addEventListener("keydown", e => {
      if (window.ImageBaker?.state?.active_tab !== "Train") return;
      if (window.ImageBaker?.isTypingInTextField?.(e.target)) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        if (flowState.selectedNodeId || flowState.selectedEdgeId) {
          e.preventDefault();
          deleteSelection();
        }
      }
    });
  }

  function notifySelect() {
    if (flowState.onSelectChange) flowState.onSelectChange(getSelectedNode());
  }

  function notifyChange() {
    if (flowState.onGraphChange) flowState.onGraphChange(getPipeline());
  }

  function escapeHtml(str) {
    return String(str || "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.trainFlow = {
    initFlow,
    setPipeline,
    getPipeline,
    getSelectedNode,
    setDataCounts,
    addNode,
    deleteSelection,
    autoLayout,
    updateSelectedNodeConfig,
    refreshEdges: renderEdges,
  };
})(window);
