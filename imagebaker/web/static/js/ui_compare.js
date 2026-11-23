/**
 * ImageBaker Web - Compare Tab (Lumina-Inspired Relative-Zoom & Annotation Comparator)
 *
 * Supports comparing model evaluation predictions across runs, Layerify images, or local uploads:
 * - Relative normalized zoom/pan (z, cx, cy) so different-resolution images stay aligned
 * - 1–4 independent panes, per-pane source selectors, drag-and-drop per pane, name-matching
 * - Modes: Side by side, Swipe 1|2, Blend 1+2, Blink 1/2, Difference, Difference map (% diff)
 * - Lumina annotation tools: Pan, Box, Ellipse, Arrow, Freehand, Text, Marker, Erase + Mirror + Undo + Export
 * - Synchronized crosshair with RGB & delta-RGB pixel readout
 */
(function(window) {
  "use strict";

  const api = window.ImageBaker.api;
  const { showToast } = window.ImageBaker;

  const PANE_COLORS = ["#2563eb", "#e11d48", "#059669", "#d97706"];
  const INK_COLORS = ["#ff2d55", "#ffcc00", "#34c759", "#00c7ff", "#ffffff", "#000000"];

  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const stem = name => {
    const s = String(name || "");
    const i = s.lastIndexOf(".");
    return (i > 0 ? s.slice(0, i) : s).toLowerCase();
  };

  const S = {
    sources: new Map(), // sourceId -> { id, label, items: [{ id, key, stem, name, url, meta, sourceId, annos: [] }] }
    itemsById: new Map(),
    listSource: "__all__",
    nPanes: 2,
    stack: false,
    mode: "grid", // grid | swipe | blend | blink | diff | map
    mix: 0.5,
    sync: true,
    stepMode: "match", // match | one | all
    activePane: 0,
    sharedView: { z: 1, cx: 0.5, cy: 0.5 }, // Relative normalized view!
    crosshair: false,
    pixelated: false,
    search: "",
    tool: "pan", // pan | rect | ell | arrow | pen | text | mark | erase
    color: INK_COLORS[0],
    lw: 3,
    mirror: true,
    undoStack: [],
    draft: null,
    hoverNorm: null,
    localUploads: [],
    blinkTimer: null,
    blinkShowB: false,
    mapTimer: null,
  };

  const panes = [];
  let nextItemId = 1;
  let initialized = false;
  let rafPlace = 0;
  let rafHover = 0;

  // Offscreen 1x1 sampler canvas for RGB pixel readout
  const sampleCv = document.createElement("canvas");
  sampleCv.width = 1;
  sampleCv.height = 1;
  const sampleCtx = sampleCv.getContext("2d", { willReadFrequently: true });

  function el(id) {
    return document.getElementById(id);
  }

  function logicalPanes() {
    return panes.slice(0, S.nPanes);
  }

  function visiblePanes() {
    return panes.filter(P => !P.el.classList.contains("hidden"));
  }

  function initCompareUI() {
    if (initialized) return;
    const host = el("cmp-panes");
    if (!host) return;
    initialized = true;

    // Create 4 reusable pane DOM elements
    host.innerHTML = "";
    for (let i = 0; i < 4; i++) {
      host.appendChild(createPane(i));
    }
    panes[0].el.classList.add("active");

    buildSwatches();
    bindCompareControls();
    new ResizeObserver(requestPlace).observe(host);
    applyMode();
    refreshCompareSources(false);
  }

  function buildSwatches() {
    const wrap = el("cmp-swatches");
    if (!wrap) return;
    wrap.innerHTML = INK_COLORS.map(
      (c, i) => `<button type="button" class="cmp-swatch${i === 0 ? " active" : ""}" data-cmp-color="${c}" style="background:${c};" title="Annotation color"></button>`
    ).join("");
  }

  function bindCompareControls() {
    const sideBtn = el("btn-cmp-side");
    if (sideBtn) {
      sideBtn.addEventListener("click", () => {
        const sb = el("cmp-sidebar");
        if (!sb) return;
        const hidden = sb.classList.toggle("hidden");
        sideBtn.classList.toggle("active", !hidden);
        requestPlace();
      });
    }

    const nPanesSel = el("cmp-npanes");
    if (nPanesSel) {
      nPanesSel.addEventListener("change", () => {
        const prev = S.nPanes;
        S.nPanes = Math.max(1, Math.min(4, parseInt(nPanesSel.value, 10) || 2));
        if (S.mode !== "grid") {
          S.mode = "grid";
          const mSel = el("cmp-mode");
          if (mSel) mSel.value = "grid";
        }
        // Populate newly revealed panes with next available source/image
        const srcIds = Array.from(S.sources.keys());
        for (let i = prev; i < S.nPanes; i++) {
          if (!panes[i].itemId && srcIds.length) {
            const sid = srcIds[i % srcIds.length];
            setPaneSource(panes[i], sid, 0);
          }
        }
        applyMode();
      });
    }

    const stackBtn = el("btn-cmp-stack");
    if (stackBtn) {
      stackBtn.addEventListener("click", () => {
        S.stack = !S.stack;
        stackBtn.classList.toggle("active", S.stack);
        applyMode();
      });
    }

    const modeSel = el("cmp-mode");
    if (modeSel) {
      modeSel.addEventListener("change", () => {
        S.mode = modeSel.value;
        S.mix = { swipe: 0.5, blend: 0.5, blink: 0.35, diff: 0.1, map: 0.12 }[S.mode] ?? 0.5;
        const mSlider = el("cmp-mix");
        if (mSlider) mSlider.value = String(S.mix);
        applyMode();
      });
    }

    const mixSlider = el("cmp-mix");
    if (mixSlider) {
      mixSlider.addEventListener("input", () => {
        S.mix = parseFloat(mixSlider.value);
        applyMode();
      });
    }

    const syncBtn = el("btn-cmp-sync");
    if (syncBtn) {
      syncBtn.addEventListener("click", () => {
        const activeP = panes[S.activePane];
        if (!S.sync && activeP) {
          S.sharedView = { ...activeP.view };
        } else {
          panes.forEach(P => { P.view = { ...S.sharedView }; });
        }
        S.sync = !S.sync;
        syncBtn.classList.toggle("active", S.sync);
        syncBtn.textContent = S.sync ? "Sync: On" : "Sync: Off";
        requestPlace();
      });
    }

    const stepSel = el("cmp-step-mode");
    if (stepSel) {
      stepSel.addEventListener("change", () => {
        S.stepMode = stepSel.value;
      });
    }

    const fitBtn = el("btn-cmp-fit");
    if (fitBtn) fitBtn.addEventListener("click", fitAll);

    const oneBtn = el("btn-cmp-one");
    if (oneBtn) oneBtn.addEventListener("click", oneToOne);

    const crossBtn = el("btn-cmp-cross");
    if (crossBtn) {
      crossBtn.addEventListener("click", () => {
        S.crosshair = !S.crosshair;
        crossBtn.classList.toggle("active", S.crosshair);
        drawHover();
      });
    }

    const pxBtn = el("btn-cmp-px");
    if (pxBtn) {
      pxBtn.addEventListener("click", () => {
        S.pixelated = !S.pixelated;
        pxBtn.classList.toggle("active", S.pixelated);
        panes.forEach(P => P.vp.classList.toggle("pixelated", S.pixelated));
      });
    }

    const uploadBtn = el("btn-cmp-upload");
    const uploadInput = el("input-cmp-upload");
    if (uploadBtn && uploadInput) {
      uploadBtn.addEventListener("click", () => uploadInput.click());
      uploadInput.addEventListener("change", e => {
        const files = Array.from(e.target.files || []);
        e.target.value = "";
        if (!files.length) return;
        const added = addLocalFiles(files);
        if (added.length) {
          setPaneItem(panes[S.activePane], added[0].id);
          showToast("compare", `Added ${added.length} local image(s)`);
        }
      });
    }

    const refreshBtn = el("btn-cmp-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => refreshCompareSources(true));

    const expViewBtn = el("btn-cmp-export-view");
    if (expViewBtn) expViewBtn.addEventListener("click", exportCompareViewPng);

    const listSrcSel = el("cmp-list-source");
    if (listSrcSel) {
      listSrcSel.addEventListener("change", () => {
        S.listSource = listSrcSel.value;
        renderSidebarList();
      });
    }

    const searchInp = el("cmp-search");
    if (searchInp) {
      searchInp.addEventListener("input", () => {
        S.search = searchInp.value.trim().toLowerCase();
        renderSidebarList();
      });
    }

    // Annotation toolbar
    const toolsBar = el("cmp-tools-bar");
    if (toolsBar) {
      toolsBar.addEventListener("click", e => {
        const toolBtn = e.target.closest("[data-cmp-tool]");
        if (toolBtn) {
          setTool(toolBtn.dataset.cmpTool);
          return;
        }
        const swBtn = e.target.closest("[data-cmp-color]");
        if (swBtn) {
          S.color = swBtn.dataset.cmpColor;
          toolsBar.querySelectorAll(".cmp-swatch").forEach(b => b.classList.toggle("active", b === swBtn));
        }
      });
    }

    const lwInp = el("cmp-lw");
    if (lwInp) lwInp.addEventListener("input", () => { S.lw = parseInt(lwInp.value, 10) || 3; });

    const mirrorCb = el("cmp-mirror");
    if (mirrorCb) mirrorCb.addEventListener("change", () => { S.mirror = mirrorCb.checked; });

    const undoBtn = el("btn-cmp-undo");
    if (undoBtn) undoBtn.addEventListener("click", undoAnno);

    const clrBtn = el("btn-cmp-clear-ann");
    if (clrBtn) {
      clrBtn.addEventListener("click", () => {
        const P = panes[S.activePane];
        const o = P ? S.itemsById.get(P.itemId) : null;
        if (!o || !o.annos.length) return;
        const old = o.annos.map((a, k) => [o.id, a, k]);
        o.annos = [];
        S.undoStack.push({ del: old });
        visiblePanes().forEach(drawOv);
        showToast("compare", "Cleared annotations on active pane");
      });
    }

    const saveAnnBtn = el("btn-cmp-save-ann");
    if (saveAnnBtn) saveAnnBtn.addEventListener("click", saveActiveAnnotatedPng);

    // Refresh when Compare tab is clicked
    const tabBtn = el("tab-btn-compare");
    if (tabBtn) {
      tabBtn.addEventListener("click", () => {
        refreshCompareSources(false);
        setTimeout(requestPlace, 60);
      });
    }

    // Keyboard shortcuts when Compare tab is active
    window.addEventListener("keydown", e => {
      if (window.ImageBaker?.state?.active_tab !== "Compare") return;
      if (window.ImageBaker?.isTypingInTextField?.(e.target)) return;
      if (window.ImageBaker?.isModalOpen?.()) return;

      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if ((e.ctrlKey || e.metaKey) && k === "z") {
        e.preventDefault();
        undoAnno();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (k === "ArrowRight") { e.preventDefault(); stepNavigation(1); }
      else if (k === "ArrowLeft") { e.preventDefault(); stepNavigation(-1); }
      else if (k === "f") { e.preventDefault(); fitAll(); }
      else if (k === "z") { e.preventDefault(); oneToOne(); }
      else if (k === "s") { e.preventDefault(); el("btn-cmp-sync")?.click(); }
      else if (k === "h") { e.preventDefault(); el("btn-cmp-cross")?.click(); }
      else if (k === "Escape") { setTool("pan"); }
      else {
        const toolMap = { v: "pan", r: "rect", o: "ell", a: "arrow", d: "pen", t: "text", m: "mark", e: "erase" };
        if (toolMap[k]) {
          e.preventDefault();
          setTool(toolMap[k]);
        }
      }
    });
  }

  function setTool(t) {
    S.tool = t;
    document.querySelectorAll("[data-cmp-tool]").forEach(b => {
      b.classList.toggle("active", b.dataset.cmpTool === t);
    });
    panes.forEach(P => P.vp.classList.toggle("draw-mode", t !== "pan"));
  }

  function createPane(i) {
    const paneEl = document.createElement("div");
    paneEl.className = "cmp-pane";
    paneEl.dataset.pane = String(i);
    paneEl.innerHTML = `
      <div class="cmp-pane-head">
        <span class="cmp-tag" style="background:${PANE_COLORS[i]}">${i + 1}</span>
        <select class="combo-box cmp-pane-src" title="Select image source for Pane ${i + 1}"></select>
        <button type="button" class="btn btn-xs" data-pane-step="-1" title="Previous image">◀</button>
        <span class="cmp-pane-name">Empty</span>
        <button type="button" class="btn btn-xs" data-pane-step="1" title="Next image">▶</button>
      </div>
      <div class="cmp-viewport">
        <div class="cmp-stage hidden">
          <img class="cmp-img-a" alt="" draggable="false" />
          <img class="cmp-img-b hidden" alt="" draggable="false" />
          <canvas class="cmp-diff-canvas hidden"></canvas>
        </div>
        <canvas class="cmp-ov-canvas"></canvas>
        <div class="cmp-swipe-line hidden"></div>
        <div class="cmp-cross-x hidden"></div>
        <div class="cmp-cross-y hidden"></div>
        <div class="cmp-empty">Click an image in the list,<br>pick a source above, or drop images here</div>
      </div>
      <div class="cmp-pane-foot">
        <span class="cmp-foot-meta">—</span>
        <span class="cmp-foot-rd"></span>
      </div>
    `;

    const P = {
      i,
      el: paneEl,
      sourceId: "",
      itemId: null,
      w: 0,
      h: 0,
      g: null,
      view: { z: 1, cx: 0.5, cy: 0.5 },
      tag: paneEl.querySelector(".cmp-tag"),
      srcSel: paneEl.querySelector(".cmp-pane-src"),
      nameEl: paneEl.querySelector(".cmp-pane-name"),
      vp: paneEl.querySelector(".cmp-viewport"),
      stage: paneEl.querySelector(".cmp-stage"),
      ia: paneEl.querySelector(".cmp-img-a"),
      ib: paneEl.querySelector(".cmp-img-b"),
      dcv: paneEl.querySelector(".cmp-diff-canvas"),
      ov: paneEl.querySelector(".cmp-ov-canvas"),
      swl: paneEl.querySelector(".cmp-swipe-line"),
      cx: paneEl.querySelector(".cmp-cross-x"),
      cy: paneEl.querySelector(".cmp-cross-y"),
      empty: paneEl.querySelector(".cmp-empty"),
      footMeta: paneEl.querySelector(".cmp-foot-meta"),
      footRd: paneEl.querySelector(".cmp-foot-rd"),
    };
    panes.push(P);

    paneEl.addEventListener("pointerdown", () => setActivePane(i), true);

    P.srcSel.addEventListener("change", () => {
      setPaneSource(P, P.srcSel.value, 0);
    });

    paneEl.querySelectorAll("[data-pane-step]").forEach(btn => {
      btn.addEventListener("click", () => {
        const delta = parseInt(btn.dataset.paneStep, 10) || 0;
        stepSinglePane(P, delta);
      });
    });

    // Relative zoom at cursor (EXACT Lumina formula)
    P.vp.addEventListener("wheel", e => {
      e.preventDefault();
      setActivePane(i);
      if (!P.w) return;
      const r = P.vp.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0015));
      zoomAt(P, factor, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    P.vp.addEventListener("mousedown", e => {
      if (e.button === 1) e.preventDefault();
    });

    const getMouseCoords = e => {
      const r = P.vp.getBoundingClientRect();
      const g = P.g || geom(P);
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      return {
        mx,
        my,
        fx: (mx - g.x) / Math.max(1e-6, P.w * g.s),
        fy: (my - g.y) / Math.max(1e-6, P.h * g.s),
      };
    };

    let drag = null;
    P.vp.addEventListener("pointerdown", e => {
      if (!P.w || e.button === 2) return;
      if (e.target === P.swl && !(e.ctrlKey || e.metaKey)) return;
      const o = S.itemsById.get(P.itemId);
      if (!o) return;
      const m = getMouseCoords(e);
      e.preventDefault();

      if (S.tool === "pan" || e.button === 1 || e.ctrlKey || e.metaKey) {
        drag = { kind: "pan", x: e.clientX, y: e.clientY };
        P.vp.setPointerCapture(e.pointerId);
        P.vp.classList.add("dragging");
        return;
      }

      const base = { t: S.tool, c: S.color, w: S.lw, x1: clamp(m.fx, 0, 1), y1: clamp(m.fy, 0, 1) };
      if (S.tool === "erase") {
        for (let k = o.annos.length - 1; k >= 0; k--) {
          if (hitAnno(P, o.annos[k], m.mx, m.my)) {
            const removed = o.annos.splice(k, 1)[0];
            S.undoStack.push({ del: [[o.id, removed, k]] });
            visiblePanes().forEach(drawOv);
            break;
          }
        }
        return;
      }
      if (S.tool === "mark") {
        commitAnno(P, base);
        return;
      }
      if (S.tool === "text") {
        setTimeout(() => {
          const txt = window.prompt("Annotation text:");
          if (txt && txt.trim()) commitAnno(P, { ...base, s: txt.trim() });
        }, 0);
        return;
      }
      base.x2 = base.x1;
      base.y2 = base.y1;
      if (S.tool === "pen") base.p = [base.x1, base.y1];
      drag = { kind: "draw", a: base, sx: m.mx, sy: m.my, lx: m.mx, ly: m.my };
      S.draft = { P, a: base };
      P.vp.setPointerCapture(e.pointerId);
    });

    P.vp.addEventListener("pointermove", e => {
      if (!P.w) return;
      const m = getMouseCoords(e);
      S.hoverNorm = { fx: m.fx, fy: m.fy };
      if (drag && drag.kind === "pan") {
        const v = S.sync ? S.sharedView : P.view;
        const g = P.g || geom(P);
        // Normalized relative pan!
        v.cx -= (e.clientX - drag.x) / Math.max(1e-6, P.w * g.s);
        v.cy -= (e.clientY - drag.y) / Math.max(1e-6, P.h * g.s);
        drag.x = e.clientX;
        drag.y = e.clientY;
        requestPlace();
      } else if (drag && drag.kind === "draw") {
        const a = drag.a;
        a.x2 = clamp(m.fx, 0, 1);
        a.y2 = clamp(m.fy, 0, 1);
        if (a.t === "pen" && Math.hypot(m.mx - drag.lx, m.my - drag.ly) > 1.5) {
          a.p.push(a.x2, a.y2);
          drag.lx = m.mx;
          drag.ly = m.my;
        }
        if (S.mirror && S.mode === "grid") visiblePanes().forEach(drawOv);
        else drawOv(P);
      }
      if (S.crosshair) requestHover();
    });

    const endPointer = e => {
      P.vp.classList.remove("dragging");
      if (!drag) return;
      const d = drag;
      drag = null;
      if (d.kind === "draw") {
        S.draft = null;
        const m = getMouseCoords(e);
        const valid = d.a.t === "pen" ? d.a.p.length >= 6 : Math.hypot(m.mx - d.sx, m.my - d.sy) > 4;
        if (valid) commitAnno(P, d.a);
        else visiblePanes().forEach(drawOv);
      }
    };
    P.vp.addEventListener("pointerup", endPointer);
    P.vp.addEventListener("pointercancel", endPointer);
    P.vp.addEventListener("pointerleave", () => {
      S.hoverNorm = null;
      if (S.crosshair) requestHover();
    });

    P.vp.addEventListener("dblclick", () => {
      if (S.tool === "pan") fitAll();
    });

    // Drag & drop local image files directly onto any pane!
    P.vp.addEventListener("dragover", e => {
      e.preventDefault();
      P.vp.classList.add("drop-over");
    });
    P.vp.addEventListener("dragleave", () => P.vp.classList.remove("drop-over"));
    P.vp.addEventListener("drop", e => {
      e.preventDefault();
      e.stopPropagation();
      P.vp.classList.remove("drop-over");
      const files = Array.from(e.dataTransfer?.files || []).filter(f => /^image\//.test(f.type) || /\.(png|jpe?g|webp|bmp|gif)$/i.test(f.name));
      if (!files.length) return;
      const added = addLocalFiles(files);
      if (added.length) {
        setPaneItem(P, added[0].id);
        showToast("compare", `Loaded ${added[0].name} into Pane ${P.i + 1}`);
      }
    });

    // Swipe divider drag (normalized to image coordinates; Ctrl+drag pans viewport instead)
    let swDrag = false;
    P.swl.addEventListener("pointerdown", e => {
      if (e.ctrlKey || e.metaKey) return;
      swDrag = true;
      P.swl.setPointerCapture(e.pointerId);
      e.preventDefault();
      e.stopPropagation();
    });
    P.swl.addEventListener("pointermove", e => {
      if (!swDrag || !P.g) return;
      const r = P.vp.getBoundingClientRect();
      S.mix = clamp((e.clientX - r.left - P.g.x) / Math.max(1e-6, P.w * P.g.s), 0, 1);
      const slider = el("cmp-mix");
      if (slider) slider.value = String(S.mix);
      applyMode();
    });
    P.swl.addEventListener("pointerup", () => { swDrag = false; });

    return paneEl;
  }

  function setActivePane(i) {
    if (S.activePane === i) return;
    S.activePane = i;
    panes.forEach(P => P.el.classList.toggle("active", P.i === i));
    updateZoomLabel();
  }

  /* ==================== RELATIVE GEOMETRY & ZOOM ==================== */
  function geom(P) {
    const pw = P.vp.clientWidth;
    const ph = P.vp.clientHeight;
    const v = S.sync ? S.sharedView : P.view;
    const fit = Math.min(pw / Math.max(1, P.w), ph / Math.max(1, P.h)) || 1;
    const s = fit * v.z;
    return {
      pw,
      ph,
      fit,
      s,
      x: pw / 2 - v.cx * P.w * s,
      y: ph / 2 - v.cy * P.h * s,
    };
  }

  function placePane(P) {
    if (!P.w) {
      P.g = null;
      return;
    }
    const g = (P.g = geom(P));
    P.stage.style.transform = `translate(${g.x}px, ${g.y}px) scale(${g.s})`;
    if (!P.swl.classList.contains("hidden")) {
      P.swl.style.left = `${g.x + S.mix * P.w * g.s}px`;
    }
    drawOv(P);
    if (P.i === S.activePane) updateZoomLabel();
  }

  function requestPlace() {
    if (rafPlace) return;
    rafPlace = requestAnimationFrame(() => {
      rafPlace = 0;
      visiblePanes().forEach(placePane);
      if (S.crosshair) drawHover();
    });
  }

  function updateZoomLabel() {
    const P = panes[S.activePane];
    const lbl = el("cmp-zoom-readout");
    if (lbl) lbl.textContent = P && P.g ? `${Math.round(P.g.s * 100)}%` : "100%";
  }

  function zoomAt(P, factor, mx, my) {
    const v = S.sync ? S.sharedView : P.view;
    const g = geom(P);
    const fx = (mx - g.x) / Math.max(1e-6, P.w * g.s);
    const fy = (my - g.y) / Math.max(1e-6, P.h * g.s);
    v.z = clamp(v.z * factor, 0.05, Math.max(1, 64 / g.fit));
    const s = g.fit * v.z;
    v.cx = fx - (mx - g.pw / 2) / Math.max(1e-6, P.w * s);
    v.cy = fy - (my - g.ph / 2) / Math.max(1e-6, P.h * s);
    requestPlace();
  }

  function fitAll() {
    S.sharedView = { z: 1, cx: 0.5, cy: 0.5 };
    panes.forEach(P => { P.view = { z: 1, cx: 0.5, cy: 0.5 }; });
    requestPlace();
  }

  function oneToOne() {
    const P = panes[S.activePane];
    if (!P || !P.w) return;
    const z = 1 / geom(P).fit;
    if (S.sync) S.sharedView.z = z;
    else P.view.z = z;
    requestPlace();
  }

  /* ==================== SOURCES & PER-PANE LOADING ==================== */
  function addLocalFiles(files) {
    const added = [];
    files.forEach(f => {
      const url = URL.createObjectURL(f);
      const item = {
        id: nextItemId++,
        sourceId: "local_uploads",
        key: f.name.toLowerCase(),
        stem: stem(f.name),
        name: f.name,
        url,
        meta: `${(f.size / 1024).toFixed(1)} KB`,
        annos: [],
      };
      S.localUploads.push(item);
      S.itemsById.set(item.id, item);
      added.push(item);
    });
    rebuildLocalSource();
    populateAllSourceSelects();
    renderSidebarList();
    return added;
  }

  function rebuildLocalSource() {
    if (S.localUploads.length) {
      S.sources.set("local_uploads", {
        id: "local_uploads",
        label: `Local Uploads (${S.localUploads.length})`,
        items: S.localUploads,
      });
    }
  }

  async function refreshCompareSources(notify = false) {
    try {
      const prevAnnosByUrl = new Map();
      S.itemsById.forEach(it => {
        if (it.annos?.length) prevAnnosByUrl.set(it.url, it.annos);
      });

      const stRes = await api.getTrainStatus();
      const runs = stRes?.training?.runs || [];
      S.sources.clear();
      S.itemsById.clear();

      const recentRuns = runs.slice(0, 12);
      const runStatuses = await Promise.all(
        recentRuns.map(r => api.getTrainStatus(r.run_id).catch(() => null))
      );

      runStatuses.forEach((res, idx) => {
        const run = recentRuns[idx];
        const imgs = res?.training?.eval_images || [];
        if (imgs.length) {
          const sid = `run:${run.run_id}`;
          const items = imgs.map(im => {
            const name = im.source_image || im.name;
            const item = {
              id: nextItemId++,
              sourceId: sid,
              key: name.toLowerCase(),
              stem: stem(name),
              name,
              url: im.url,
              meta: `${String(im.split || "val").toUpperCase()} • GT:${im.num_gt ?? 0} Pred:${im.num_preds ?? 0}`,
              annos: prevAnnosByUrl.get(im.url) || [],
            };
            S.itemsById.set(item.id, item);
            return item;
          });
          S.sources.set(sid, {
            id: sid,
            label: `${run.run_id} (${run.trainer_name || "Eval"}, ${items.length})`,
            items,
          });
        }
      });

      const lyrImgs = window.ImageBaker?.state?.layerify?.images || [];
      if (lyrImgs.length) {
        const items = lyrImgs.map((im, i) => {
          const name = im.name || `Image ${i + 1}`;
          const url = im.image_url || `/api/layerify/image?index=${i}`;
          const item = {
            id: nextItemId++,
            sourceId: "layerify",
            key: name.toLowerCase(),
            stem: stem(name),
            name,
            url,
            meta: `${im.annotation_count ?? 0} ann(s)`,
            annos: prevAnnosByUrl.get(url) || [],
          };
          S.itemsById.set(item.id, item);
          return item;
        });
        S.sources.set("layerify", {
          id: "layerify",
          label: `Layerify Images (${items.length})`,
          items,
        });
      }

      S.localUploads.forEach(it => S.itemsById.set(it.id, it));
      rebuildLocalSource();
      populateAllSourceSelects();

      // Auto-populate panes if empty
      const srcIds = Array.from(S.sources.keys());
      logicalPanes().forEach((P, idx) => {
        if (!P.sourceId || !S.sources.has(P.sourceId)) {
          const defaultSid = srcIds[idx % Math.max(1, srcIds.length)] || "";
          if (defaultSid) setPaneSource(P, defaultSid, 0);
        } else {
          // Re-bind item by url/name after refresh
          const items = S.sources.get(P.sourceId)?.items || [];
          if (items.length && !S.itemsById.has(P.itemId)) {
            setPaneItem(P, items[0].id);
          }
        }
      });

      renderSidebarList();
      if (notify) showToast("compare", `Loaded ${S.sources.size} compare source(s)`);
    } catch (err) {
      console.error("Failed to refresh Compare sources:", err);
    }
  }

  function populateAllSourceSelects() {
    const srcIds = Array.from(S.sources.keys());
    const listSel = el("cmp-list-source");
    if (listSel) {
      listSel.innerHTML = `<option value="__all__">All Sources (${S.itemsById.size})</option>`;
      srcIds.forEach(sid => {
        const src = S.sources.get(sid);
        const opt = document.createElement("option");
        opt.value = sid;
        opt.textContent = src.label;
        if (sid === S.listSource) opt.selected = true;
        listSel.appendChild(opt);
      });
    }

    panes.forEach(P => {
      P.srcSel.innerHTML = "";
      if (!srcIds.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No sources";
        P.srcSel.appendChild(opt);
        return;
      }
      srcIds.forEach(sid => {
        const src = S.sources.get(sid);
        const opt = document.createElement("option");
        opt.value = sid;
        opt.textContent = src.label;
        if (sid === P.sourceId) opt.selected = true;
        P.srcSel.appendChild(opt);
      });
    });
  }

  function setPaneSource(P, sourceId, index = 0) {
    P.sourceId = sourceId;
    if (P.srcSel) P.srcSel.value = sourceId;
    const items = S.sources.get(sourceId)?.items || [];
    if (!items.length) {
      setPaneItem(P, null);
      return;
    }
    const target = items[clamp(index, 0, items.length - 1)];
    setPaneItem(P, target.id);
  }

  function setPaneItem(P, itemId) {
    const o = itemId != null ? S.itemsById.get(itemId) : null;
    P.itemId = o ? o.id : null;
    P.w = 0;
    P.h = 0;
    P.g = null;
    if (o && o.sourceId) {
      P.sourceId = o.sourceId;
      if (P.srcSel) P.srcSel.value = o.sourceId;
    }
    if (!o) {
      P.ia.removeAttribute("src");
      P.stage.classList.add("hidden");
      P.empty.classList.remove("hidden");
      drawOv(P);
      updatePaneHeader(P);
      renderSidebarList();
      if (S.mode !== "grid") applyMode();
      return;
    }

    const url = o.url;
    P.ia.onload = () => {
      if (P.itemId !== o.id) return;
      P.w = P.ia.naturalWidth || 300;
      P.h = P.ia.naturalHeight || 300;
      P.stage.style.width = `${P.w}px`;
      P.stage.style.height = `${P.h}px`;
      P.stage.classList.remove("hidden");
      P.empty.classList.add("hidden");
      if (!S.sync) P.view = { z: 1, cx: 0.5, cy: 0.5 };
      updatePaneHeader(P);
      if (S.mode !== "grid" && P.i < 2) applyMode();
      else placePane(P);
    };
    P.ia.src = url;
    updatePaneHeader(P);
    renderSidebarList();
  }

  function updatePaneHeader(P) {
    const o = S.itemsById.get(P.itemId);
    const isOvl = S.mode !== "grid" && P.i === 0;
    const bItem = S.itemsById.get(panes[1]?.itemId);
    P.nameEl.textContent = o ? (isOvl && bItem ? `${o.name} ⇄ ${bItem.name}` : o.name) : "Empty";
    P.nameEl.title = o ? `${o.name} (${o.meta || ""})` : "";
    const dim = P.w ? `${P.w}×${P.h}px` : "";
    P.footMeta.textContent = o ? [o.meta, dim].filter(Boolean).join(" • ") : "—";
  }

  function stepSinglePane(P, delta) {
    const items = S.sources.get(P.sourceId)?.items || [];
    if (!items.length) return;
    const curIdx = items.findIndex(it => it.id === P.itemId);
    const nextIdx = curIdx < 0 ? 0 : (curIdx + delta + items.length) % items.length;
    setPaneItem(P, items[nextIdx].id);
    if (S.stepMode === "match") matchOtherPanesTo(P);
  }

  function stepNavigation(delta) {
    const activeP = panes[Math.min(S.activePane, S.nPanes - 1)];
    if (!activeP) return;
    if (S.stepMode === "one") {
      stepSinglePane(activeP, delta);
    } else if (S.stepMode === "all") {
      logicalPanes().forEach(P => {
        const items = S.sources.get(P.sourceId)?.items || [];
        if (!items.length) return;
        const curIdx = items.findIndex(it => it.id === P.itemId);
        const nextIdx = curIdx < 0 ? 0 : (curIdx + delta + items.length) % items.length;
        setPaneItem(P, items[nextIdx].id);
      });
    } else {
      stepSinglePane(activeP, delta);
    }
  }

  function matchOtherPanesTo(refPane) {
    const refItem = S.itemsById.get(refPane.itemId);
    if (!refItem) return;
    logicalPanes().forEach(P => {
      if (P === refPane || !P.sourceId) return;
      const items = S.sources.get(P.sourceId)?.items || [];
      const exact = items.find(it => it.key === refItem.key) || items.find(it => it.stem === refItem.stem);
      if (exact) setPaneItem(P, exact.id);
    });
  }

  function renderSidebarList() {
    const listEl = el("cmp-image-list");
    if (!listEl) return;
    listEl.innerHTML = "";

    let items = [];
    if (S.listSource === "__all__") {
      S.sources.forEach(src => { items = items.concat(src.items); });
    } else {
      items = S.sources.get(S.listSource)?.items || [];
    }

    const filtered = items.filter(it => !S.search || it.name.toLowerCase().includes(S.search) || (it.meta || "").toLowerCase().includes(S.search));
    if (!filtered.length) {
      listEl.innerHTML = `<div class="item-subtitle" style="padding:8px;">Run Eval &amp; Visualize in Train tab or add images to compare.</div>`;
      return;
    }

    filtered.forEach(item => {
      const inPanes = logicalPanes().filter(P => P.itemId === item.id).map(P => P.i + 1);
      const row = document.createElement("div");
      row.className = "cmp-list-row" + (inPanes.length ? " in-pane" : "");
      row.innerHTML = `
        <img class="cmp-list-thumb" src="${item.url}" alt="${escapeHtml(item.name)}" loading="lazy" />
        <div class="cmp-list-meta">
          <div class="cmp-list-name">${escapeHtml(item.name)}</div>
          <div class="cmp-list-sub">${escapeHtml(item.meta || item.sourceId)}</div>
        </div>
        <div class="cmp-list-pane-tags">${inPanes.join(" ")}</div>
      `;
      row.addEventListener("click", () => {
        const targetPane = panes[Math.min(S.activePane, S.mode === "grid" ? S.nPanes - 1 : 1)];
        setPaneItem(targetPane, item.id);
        if (S.stepMode === "match") matchOtherPanesTo(targetPane);
      });
      listEl.appendChild(row);
    });
  }

  /* ==================== COMPARE MODES & DIFFERENCE MAP ==================== */
  function mixLabelText() {
    const m = S.mix;
    return {
      swipe: `Split ${Math.round(m * 100)}%`,
      blend: `Image 2: ${Math.round(m * 100)}%`,
      blink: `${Math.round(120 + m * 1380)} ms`,
      diff: `Amplify ×${(1 + m * 15).toFixed(1)}`,
      map: `Threshold ${Math.round(m * 64)}`,
    }[S.mode] || "";
  }

  function applyMode() {
    const ovl = S.mode !== "grid";
    const host = el("cmp-panes");
    if (!host) return;
    if (ovl && S.nPanes < 2) {
      S.nPanes = 2;
      const sel = el("cmp-npanes");
      if (sel) sel.value = "2";
    }

    const cols = ovl ? 1 : (S.stack ? 1 : (S.nPanes <= 3 ? S.nPanes : 2));
    host.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;

    panes.forEach(P => {
      const shouldHide = ovl ? P.i > 0 : P.i >= S.nPanes;
      P.el.classList.toggle("hidden", shouldHide);
      P.ib.classList.add("hidden");
      P.dcv.classList.add("hidden");
      P.swl.classList.add("hidden");
      P.ib.style.cssText = "";
      P.stage.style.filter = S.mode === "diff" ? `brightness(${(1 + S.mix * 15).toFixed(2)})` : "none";
      P.tag.textContent = String(P.i + 1);
      P.tag.style.background = PANE_COLORS[P.i];
    });

    clearInterval(S.blinkTimer);
    S.blinkTimer = null;
    const mixWrap = el("cmp-mix-wrap");
    const mixLbl = el("cmp-mix-lbl");
    const diffStat = el("cmp-diff-stat");
    if (mixWrap) mixWrap.classList.toggle("hidden", !ovl);
    if (mixLbl) mixLbl.textContent = mixLabelText();
    if (diffStat && S.mode !== "map") diffStat.textContent = "";

    if (ovl && S.activePane > 0) setActivePane(0);
    if (!ovl && S.activePane >= S.nPanes) setActivePane(0);

    const A = panes[0];
    const B = panes[1];
    const bItem = B ? S.itemsById.get(B.itemId) : null;
    if (ovl && A.w && bItem) {
      if (A.ib.dataset.u !== bItem.url) {
        A.ib.onload = () => { if (S.mode === "map") computeDiffMap(); };
        A.ib.src = bItem.url;
        A.ib.dataset.u = bItem.url;
      }
      if (S.mode === "map") {
        A.dcv.classList.remove("hidden");
        clearTimeout(S.mapTimer);
        S.mapTimer = setTimeout(computeDiffMap, 40);
      } else {
        A.ib.classList.remove("hidden");
        if (S.mode === "swipe") {
          A.ib.style.clipPath = `inset(0 0 0 ${S.mix * 100}%)`;
          A.swl.classList.remove("hidden");
        } else if (S.mode === "blend") {
          A.ib.style.opacity = String(S.mix);
        } else if (S.mode === "diff") {
          A.ib.style.mixBlendMode = "difference";
        } else if (S.mode === "blink") {
          S.blinkTimer = setInterval(() => {
            const hideB = A.ib.classList.toggle("hidden");
            const k = hideB ? 0 : 1;
            A.tag.textContent = String(k + 1);
            A.tag.style.background = PANE_COLORS[k];
          }, Math.round(120 + S.mix * 1380));
        }
      }
    }

    logicalPanes().forEach(updatePaneHeader);
    requestPlace();
  }

  function computeDiffMap() {
    const A = panes[0];
    const B = panes[1];
    if (S.mode !== "map" || !A.w || !A.ib.complete || !A.ib.naturalWidth) return;
    const k = Math.min(1, Math.sqrt(4e6 / Math.max(1, A.w * A.h)));
    const w = Math.max(1, Math.round(A.w * k));
    const h = Math.max(1, Math.round(A.h * k));
    A.dcv.width = w;
    A.dcv.height = h;
    const ctx = A.dcv.getContext("2d", { willReadFrequently: true });
    let dA, dB;
    try {
      ctx.drawImage(A.ia, 0, 0, w, h);
      dA = ctx.getImageData(0, 0, w, h);
      ctx.clearRect(0, 0, w, h);
      ctx.drawImage(A.ib, 0, 0, w, h);
      dB = ctx.getImageData(0, 0, w, h);
    } catch (_) {
      const stat = el("cmp-diff-stat");
      if (stat) stat.textContent = "Difference map unavailable";
      return;
    }
    const p = dA.data;
    const q = dB.data;
    const thr = Math.round(S.mix * 64);
    let diffCount = 0;
    for (let i = 0; i < p.length; i += 4) {
      const d = Math.max(Math.abs(p[i] - q[i]), Math.abs(p[i + 1] - q[i + 1]), Math.abs(p[i + 2] - q[i + 2]));
      if (d > thr) {
        diffCount++;
        const v = 120 + Math.min(135, d);
        p[i] = v;
        p[i + 1] = 0;
        p[i + 2] = v;
      } else {
        const lum = (p[i] * 0.3 + p[i + 1] * 0.59 + p[i + 2] * 0.11) * 0.55 + 50;
        p[i] = p[i + 1] = p[i + 2] = lum;
      }
      p[i + 3] = 255;
    }
    ctx.putImageData(dA, 0, 0);
    const stat = el("cmp-diff-stat");
    if (stat) {
      const pct = ((diffCount / Math.max(1, w * h)) * 100).toFixed(2);
      const resized = B && B.w && (A.w !== B.w || A.h !== B.h) ? " (Image 2 scaled to Image 1)" : "";
      stat.textContent = `${pct}% pixels differ (> ${thr})${resized}`;
    }
  }

  /* ==================== LUMINA ANNOTATIONS ==================== */
  function drawAnnos(ctx, list, X, Y, u) {
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const a of list) {
      ctx.strokeStyle = a.c;
      ctx.fillStyle = a.c;
      ctx.lineWidth = a.w * u;
      const x1 = X(a.x1), y1 = Y(a.y1), x2 = X(a.x2 ?? a.x1), y2 = Y(a.y2 ?? a.y1);
      if (a.t === "rect") {
        ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      } else if (a.t === "ell") {
        ctx.beginPath();
        ctx.ellipse((x1 + x2) / 2, (y1 + y2) / 2, Math.abs(x2 - x1) / 2, Math.abs(y2 - y1) / 2, 0, 0, Math.PI * 2);
        ctx.stroke();
      } else if (a.t === "arrow") {
        const ang = Math.atan2(y2 - y1, x2 - x1);
        const hd = (8 + a.w * 2.5) * u;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - hd * Math.cos(ang - 0.45), y2 - hd * Math.sin(ang - 0.45));
        ctx.lineTo(x2 - hd * Math.cos(ang + 0.45), y2 - hd * Math.sin(ang + 0.45));
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      } else if (a.t === "pen" && a.p && a.p.length >= 2) {
        ctx.beginPath();
        ctx.moveTo(X(a.p[0]), Y(a.p[1]));
        for (let i = 2; i < a.p.length; i += 2) ctx.lineTo(X(a.p[i]), Y(a.p[i + 1]));
        ctx.stroke();
      } else if (a.t === "text") {
        ctx.font = `600 ${(11 + a.w * 3) * u}px system-ui, sans-serif`;
        ctx.textBaseline = "alphabetic";
        ctx.textAlign = "left";
        ctx.lineWidth = 3 * u;
        ctx.strokeStyle = a.c === "#000000" ? "#ffffff" : "#000000";
        ctx.strokeText(a.s || "", x1, y1);
        ctx.fillText(a.s || "", x1, y1);
      } else if (a.t === "mark") {
        const r = (9 + a.w) * u;
        ctx.beginPath();
        ctx.arc(x1, y1, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.lineWidth = 1.5 * u;
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
        ctx.fillStyle = a.c === "#ffffff" || a.c === "#ffcc00" ? "#000000" : "#ffffff";
        ctx.font = `700 ${r * 1.1}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(a.n || 1), x1, y1 + r * 0.05);
        ctx.textAlign = "left";
      }
    }
  }

  function drawOv(P) {
    const c = P.ov;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const pw = P.vp.clientWidth;
    const ph = P.vp.clientHeight;
    const W = Math.round(pw * dpr);
    const H = Math.round(ph * dpr);
    if (c.width !== W || c.height !== H) {
      c.width = W;
      c.height = H;
    }
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, pw, ph);
    const o = S.itemsById.get(P.itemId);
    const g = P.g;
    if (!o || !g) return;
    const showDraft = Boolean(S.draft && (S.draft.P === P || (S.mirror && S.mode === "grid")));
    const list = showDraft ? o.annos.concat(S.draft.a) : o.annos;
    if (!list.length) return;
    const sw = P.w * g.s;
    const sh = P.h * g.s;
    drawAnnos(ctx, list, f => g.x + f * sw, f => g.y + f * sh, 1);
  }

  function hitAnno(P, a, mx, my) {
    const g = P.g;
    if (!g) return false;
    const X = f => g.x + f * P.w * g.s;
    const Y = f => g.y + f * P.h * g.s;
    const pad = 8;
    if (a.t === "mark") return Math.hypot(mx - X(a.x1), my - Y(a.y1)) <= 14 + a.w;
    let x0, y0, x1, y1;
    if (a.t === "text") {
      const fs = 11 + a.w * 3;
      x0 = X(a.x1);
      y1 = Y(a.y1);
      x1 = x0 + (a.s || "").length * fs * 0.6;
      y0 = y1 - fs;
    } else if (a.t === "pen" && a.p) {
      x0 = y0 = 1e9;
      x1 = y1 = -1e9;
      for (let i = 0; i < a.p.length; i += 2) {
        x0 = Math.min(x0, X(a.p[i]));
        x1 = Math.max(x1, X(a.p[i]));
        y0 = Math.min(y0, Y(a.p[i + 1]));
        y1 = Math.max(y1, Y(a.p[i + 1]));
      }
    } else {
      x0 = Math.min(X(a.x1), X(a.x2 ?? a.x1));
      x1 = Math.max(X(a.x1), X(a.x2 ?? a.x1));
      y0 = Math.min(Y(a.y1), Y(a.y2 ?? a.y1));
      y1 = Math.max(Y(a.y1), Y(a.y2 ?? a.y1));
    }
    return mx >= x0 - pad && mx <= x1 + pad && my >= y0 - pad && my <= y1 + pad;
  }

  function commitAnno(P, a) {
    const targetIds =
      S.mirror && S.mode === "grid"
        ? Array.from(new Set(logicalPanes().filter(Q => Q.w && Q.itemId != null).map(Q => Q.itemId)))
        : [P.itemId];
    const added = [];
    for (const id of targetIds) {
      const o = S.itemsById.get(id);
      if (!o) continue;
      const copy = JSON.parse(JSON.stringify(a));
      if (copy.t === "mark") copy.n = o.annos.filter(k => k.t === "mark").length + 1;
      o.annos.push(copy);
      added.push([id, copy]);
    }
    S.undoStack.push({ add: added });
    visiblePanes().forEach(drawOv);
  }

  function undoAnno() {
    const u = S.undoStack.pop();
    if (!u) return;
    for (const [id, a] of u.add || []) {
      const o = S.itemsById.get(id);
      if (!o) continue;
      const idx = o.annos.indexOf(a);
      if (idx >= 0) o.annos.splice(idx, 1);
    }
    for (const [id, a, k] of u.del || []) {
      const o = S.itemsById.get(id);
      if (!o) continue;
      o.annos.splice(Math.min(k, o.annos.length), 0, a);
    }
    visiblePanes().forEach(drawOv);
  }

  /* ==================== CROSSHAIR & RGB DELTA READOUT ==================== */
  function samplePixel(P, fx, fy) {
    if (!P.w || !(fx >= 0 && fy >= 0 && fx < 1 && fy < 1)) return null;
    const x = Math.floor(fx * P.w);
    const y = Math.floor(fy * P.h);
    try {
      sampleCtx.clearRect(0, 0, 1, 1);
      sampleCtx.drawImage(P.ia, x, y, 1, 1, 0, 0, 1, 1);
      const d = sampleCtx.getImageData(0, 0, 1, 1).data;
      return { x, y, r: d[0], g: d[1], b: d[2] };
    } catch (_) {
      return null;
    }
  }

  function requestHover() {
    if (rafHover) return;
    rafHover = requestAnimationFrame(() => {
      rafHover = 0;
      drawHover();
    });
  }

  function drawHover() {
    const h = S.crosshair ? S.hoverNorm : null;
    const ovl = S.mode !== "grid";
    let ref = null;
    for (const P of visiblePanes()) {
      const g = P.g;
      const on = Boolean(h && g);
      P.cx.classList.toggle("hidden", !on);
      P.cy.classList.toggle("hidden", !on);
      if (!on) {
        P.footRd.textContent = "";
        continue;
      }
      P.cx.style.left = `${g.x + h.fx * P.w * g.s}px`;
      P.cy.style.top = `${g.y + h.fy * P.h * g.s}px`;
      const v = samplePixel(P, h.fx, h.fy);
      if (!v) {
        P.footRd.textContent = "";
        continue;
      }
      let txt = `${v.x},${v.y}  RGB(${v.r},${v.g},${v.b})`;
      const other = ovl ? samplePixel(panes[1], h.fx, h.fy) : ref;
      if (other) {
        const dr = ovl ? other.r - v.r : v.r - other.r;
        const dg = ovl ? other.g - v.g : v.g - other.g;
        const db = ovl ? other.b - v.b : v.b - other.b;
        txt += `  Δ(${dr},${dg},${db})`;
      }
      if (!ref) ref = v;
      P.footRd.textContent = txt;
    }
  }

  /* ==================== EXPORT PNG ==================== */
  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  function saveActiveAnnotatedPng() {
    const P = panes[S.activePane];
    const o = P ? S.itemsById.get(P.itemId) : null;
    if (!o || !P.w) {
      showToast("compare", "No image in the active pane");
      return;
    }
    const c = document.createElement("canvas");
    c.width = P.w;
    c.height = P.h;
    const ctx = c.getContext("2d");
    ctx.drawImage(P.ia, 0, 0);
    drawAnnos(ctx, o.annos, f => f * P.w, f => f * P.h, Math.max(1, P.w / 900));
    c.toBlob(b => b && downloadBlob(b, `${stem(o.name)}_annotated.png`), "image/png");
  }

  function exportCompareViewPng() {
    const host = el("cmp-panes");
    if (!host) return;
    const hr = host.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const c = document.createElement("canvas");
    c.width = Math.round(hr.width * dpr);
    c.height = Math.round(hr.height * dpr);
    const ctx = c.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--bg").trim() || "#0f172a";
    ctx.fillRect(0, 0, hr.width, hr.height);

    const B = panes[1];
    for (const P of visiblePanes()) {
      const o = S.itemsById.get(P.itemId);
      if (!o || !P.w) continue;
      const r = P.vp.getBoundingClientRect();
      const ox = r.left - hr.left;
      const oy = r.top - hr.top;
      const g = geom(P);
      const dx = ox + g.x;
      const dy = oy + g.y;
      const dw = P.w * g.s;
      const dh = P.h * g.s;

      ctx.save();
      ctx.beginPath();
      ctx.rect(ox, oy, r.width, r.height);
      ctx.clip();
      ctx.fillStyle = "#0b1120";
      ctx.fillRect(ox, oy, r.width, r.height);
      ctx.imageSmoothingEnabled = !S.pixelated;
      if (S.mode === "map" && !P.dcv.classList.contains("hidden")) {
        ctx.drawImage(P.dcv, dx, dy, dw, dh);
      } else {
        ctx.drawImage(P.ia, dx, dy, dw, dh);
        if (S.mode !== "grid" && B && B.w && !(S.mode === "blink" && P.ib.classList.contains("hidden"))) {
          ctx.save();
          if (S.mode === "blend") ctx.globalAlpha = S.mix;
          if (S.mode === "diff") ctx.globalCompositeOperation = "difference";
          if (S.mode === "swipe") {
            ctx.beginPath();
            ctx.rect(dx + S.mix * dw, oy, r.width, r.height);
            ctx.clip();
          }
          ctx.drawImage(B.ia, dx, dy, dw, dh);
          ctx.restore();
        }
      }
      drawAnnos(ctx, o.annos, v => dx + v * dw, v => dy + v * dh, 1);
      const lbl = `${P.i + 1}  ${P.nameEl.textContent}`;
      ctx.font = "600 12px system-ui, sans-serif";
      const tw = ctx.measureText(lbl).width;
      ctx.fillStyle = PANE_COLORS[P.i];
      ctx.fillRect(ox, oy, tw + 14, 20);
      ctx.fillStyle = "#ffffff";
      ctx.textBaseline = "middle";
      ctx.fillText(lbl, ox + 7, oy + 10);
      ctx.restore();
    }
    c.toBlob(b => b && downloadBlob(b, `imagebaker_compare_${Date.now()}.png`), "image/png");
  }

  async function openRunInCompare(runId, imageName = "") {
    const res = await api.updateSettings({ active_tab: "Compare" });
    if (res?.ok && res.state) window.ImageBaker.applyServerState(res.state);
    await refreshCompareSources(false);
    const sid = `run:${runId}`;
    if (S.sources.has(sid)) {
      const items = S.sources.get(sid).items || [];
      const idx = imageName ? items.findIndex(it => it.name === imageName) : 0;
      setPaneSource(panes[0], sid, idx >= 0 ? idx : 0);
      if (S.stepMode === "match") matchOtherPanesTo(panes[0]);
      applyMode();
    }
  }

  function escapeHtml(str) {
    return String(str || "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.uiCompare = {
    initCompareUI,
    refreshCompareSources,
    openRunInCompare,
  };
})(window);
