/**
 * ImageBaker Web - Baker Compositing Canvas Engine
 */
(function(window) {
  "use strict";

  const { state, bkrView, CURSORS, sceneToLayerLocal, showToast } = window.ImageBaker;
  const api = window.ImageBaker.api;
  const grid = window.ImageBaker.grid;

  let bkrCanvas, bkrCanvasWrap;

  function initBakerCanvas() {
    bkrCanvas = document.getElementById("baker-canvas");
    bkrCanvasWrap = document.getElementById("baker-canvas-wrap");
    if (!bkrCanvas || !bkrCanvasWrap) return;

    bkrView.canvas = bkrCanvas;
    bkrView.ctx = bkrCanvas.getContext("2d");
    bkrView.wrap = bkrCanvasWrap;

    bindCanvasEvents();
  }

  function resizeBakerCanvas() {
    if (!bkrCanvas || !bkrCanvasWrap) return;
    const rect = bkrCanvasWrap.getBoundingClientRect();
    const w = Math.max(10, Math.floor(rect.width));
    const h = Math.max(10, Math.floor(rect.height));
    if (bkrCanvas.width !== w || bkrCanvas.height !== h) {
      bkrCanvas.width = w;
      bkrCanvas.height = h;
      drawBakerCanvas();
    }
  }

  function getLayerImageElement(lyr) {
    if (!lyr.thumb_url && !lyr.image_url) return null;
    const url = lyr.image_url || lyr.thumb_url;
    if (bkrView.layerImageCache.has(url)) {
      return bkrView.layerImageCache.get(url);
    }
    const img = new Image();
    img.onload = () => drawBakerCanvas();
    img.src = url;
    bkrView.layerImageCache.set(url, img);
    return img;
  }

  function getBakerLayerLocalHandles(lw, lh) {
    return [
      { id: "nw", x: 0, y: 0 },
      { id: "n", x: lw / 2, y: 0 },
      { id: "ne", x: lw, y: 0 },
      { id: "e", x: lw, y: lh / 2 },
      { id: "se", x: lw, y: lh },
      { id: "s", x: lw / 2, y: lh },
      { id: "sw", x: 0, y: lh },
      { id: "w", x: 0, y: lh / 2 },
    ];
  }

  function hitTestBakerLayer(scenePt) {
    const layers = state.baker.layers || [];
    // Check in reverse z-order (topmost first)
    for (let i = layers.length - 1; i >= 0; i--) {
      const lyr = layers[i];
      if (lyr.visible === false) continue;
      const img = getLayerImageElement(lyr);
      const lw = lyr.width || (img && img.complete ? img.width : 100);
      const lh = lyr.height || (img && img.complete ? img.height : 100);
      const localPt = sceneToLayerLocal(scenePt, lyr);

      // Check center rotation handle if selected
      if (lyr.selected) {
        if (Math.hypot(localPt.x - lw / 2, localPt.y - lh / 2) <= 12 / bkrView.zoom) {
          return { layerId: lyr.layer_id, part: "rotate", handleId: "center" };
        }
        // Check 8 scale handles
        const handles = getBakerLayerLocalHandles(lw, lh);
        for (const h of handles) {
          if (Math.hypot(localPt.x - h.x, localPt.y - h.y) <= 10 / bkrView.zoom) {
            return { layerId: lyr.layer_id, part: "scale", handleId: h.id };
          }
        }
      }

      // Check body
      if (localPt.x >= 0 && localPt.x <= lw && localPt.y >= 0 && localPt.y <= lh) {
        return { layerId: lyr.layer_id, part: "body" };
      }
    }
    return null;
  }

  function drawBakerCanvas() {
    if (!bkrCanvas || !bkrView.ctx) return;
    const ctx = bkrView.ctx;
    const w = bkrCanvas.width;
    const h = bkrCanvas.height;

    ctx.clearRect(0, 0, w, h);

    const isDark = state.theme_mode === "dark";
    ctx.fillStyle = isDark ? "#0d131d" : "#e2e8f0";
    ctx.fillRect(0, 0, w, h);

    const layers = state.baker.layers || [];

    // Draw Multi-Depth Dimension-Adaptive Gridlines
    if (state.show_gridlines) {
      const hoverPt = bkrView.isMouseOver
        ? { x: bkrView.sceneMouseX * bkrView.zoom + bkrView.offsetX, y: bkrView.sceneMouseY * bkrView.zoom + bkrView.offsetY }
        : null;
      grid.drawGridlines(
        ctx, w, h, bkrView.offsetX, bkrView.offsetY, bkrView.zoom,
        hoverPt,
        state.baker.current_canvas ? state.baker.current_canvas.width || 1280 : 1280,
        state.baker.current_canvas ? state.baker.current_canvas.height || 720 : 720
      );
    }

    if (layers.length === 0) {
      ctx.save();
      ctx.fillStyle = isDark ? "#475569" : "#94a3b8";
      ctx.font = "14px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Layerify annotations or click 'Add Blank Layer' to composite here.", w / 2, h / 2);
      ctx.restore();
      return;
    }

    ctx.save();
    ctx.translate(bkrView.offsetX, bkrView.offsetY);
    ctx.scale(bkrView.zoom, bkrView.zoom);

    // Draw layers in order
    layers.forEach(lyr => {
      if (lyr.visible === false) return;
      const img = getLayerImageElement(lyr);
      const lw = lyr.width || (img && img.complete ? img.width : 100);
      const lh = lyr.height || (img && img.complete ? img.height : 100);
      const posX = lyr.position ? lyr.position[0] : 0;
      const posY = lyr.position ? lyr.position[1] : 0;
      const sx = lyr.scale_x ?? 1.0;
      const sy = lyr.scale_y ?? 1.0;
      const rotRad = ((lyr.rotation ?? 0) * Math.PI) / 180.0;
      const alpha = Math.max(0, Math.min(1, (lyr.opacity ?? 255) / 255));

      ctx.save();
      ctx.globalAlpha = alpha;
      const cx = (lw * sx) / 2;
      const cy = (lh * sy) / 2;
      ctx.translate(posX, posY);
      ctx.translate(cx, cy);
      ctx.rotate(rotRad);
      ctx.translate(-cx, -cy);
      ctx.scale(sx, sy);

      if (img && img.complete && img.naturalWidth > 0) {
        ctx.drawImage(img, 0, 0);
      }

      // Drawing strokes on layer
      if (lyr.drawing_states && lyr.drawing_states.length > 0) {
        lyr.drawing_states.forEach(st => {
          const pts = st.points || [];
          const [sr, sg, sb, sa] = st.color || [255, 0, 0, 255];
          const sz = st.size || 5;
          ctx.fillStyle = `rgba(${sr}, ${sg}, ${sb}, ${(sa ?? 255) / 255})`;
          pts.forEach(p => {
            ctx.beginPath();
            ctx.arc(p[0], p[1], sz / 2, 0, Math.PI * 2);
            ctx.fill();
          });
        });
      }

      // Selection bounding box, 8 scale handles, and center rotation handle
      if (lyr.selected) {
        ctx.globalAlpha = 1.0;
        ctx.save();
        ctx.setLineDash([5 / (bkrView.zoom * sx), 4 / (bkrView.zoom * sx)]);
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.5 / (bkrView.zoom * Math.max(0.2, sx));
        ctx.strokeRect(0, 0, lw, lh);
        ctx.restore();

        const hSize = 8 / (bkrView.zoom * Math.max(0.2, sx));
        const handles = getBakerLayerLocalHandles(lw, lh);
        ctx.fillStyle = "#2f80ed";
        handles.forEach(hp => {
          ctx.fillRect(hp.x - hSize / 2, hp.y - hSize / 2, hSize, hSize);
        });

        // Center rotation handle
        ctx.beginPath();
        ctx.arc(lw / 2, lh / 2, hSize * 0.75, 0, Math.PI * 2);
        ctx.fillStyle = "#10b981";
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1 / (bkrView.zoom * Math.max(0.2, sx));
        ctx.stroke();
      }

      ctx.restore();
    });

    ctx.restore();
  }

  function bindCanvasEvents() {
    if (!bkrCanvas) return;

    bkrCanvas.addEventListener("pointerdown", e => {
      bkrCanvas.setPointerCapture(e.pointerId);
      const rect = bkrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const sceneX = (sx - bkrView.offsetX) / bkrView.zoom;
      const sceneY = (sy - bkrView.offsetY) / bkrView.zoom;
      const scenePt = { x: sceneX, y: sceneY };

      if (e.button === 1 || (e.button === 0 && e.spaceKey)) {
        bkrView.isPanning = true;
        bkrView.panStartX = sx;
        bkrView.panStartY = sy;
        bkrView.panStartOffX = bkrView.offsetX;
        bkrView.panStartOffY = bkrView.offsetY;
        bkrCanvas.style.cursor = CURSORS.PAN_ACTIVE;
        return;
      }

      if (e.button !== 0) return;

      const hit = hitTestBakerLayer(scenePt);
      if (hit) {
        const layers = state.baker.layers || [];
        layers.forEach(l => {
          l.selected = (l.layer_id === hit.layerId);
        });
        bkrView.draggingLayerId = hit.layerId;
        bkrView.activeHandle = hit.part === "scale" || hit.part === "rotate" ? hit.handleId : null;
        bkrView.dragStartScene = { ...scenePt };
        drawBakerCanvas();
        window.ImageBaker.uiBaker.renderLayerSettings();
        window.ImageBaker.uiBaker.renderLayerLists();
      } else {
        // Deselect all
        (state.baker.layers || []).forEach(l => l.selected = false);
        bkrView.draggingLayerId = null;
        drawBakerCanvas();
        window.ImageBaker.uiBaker.renderLayerSettings();
        window.ImageBaker.uiBaker.renderLayerLists();
      }
    });

    bkrCanvas.addEventListener("pointermove", e => {
      const rect = bkrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const sceneX = (sx - bkrView.offsetX) / bkrView.zoom;
      const sceneY = (sy - bkrView.offsetY) / bkrView.zoom;
      bkrView.sceneMouseX = sceneX;
      bkrView.sceneMouseY = sceneY;
      bkrView.isMouseOver = true;

      const coordsEl = document.getElementById("baker-coords-pill");
      if (coordsEl) {
        coordsEl.textContent = `X: ${Math.round(sceneX)}, Y: ${Math.round(sceneY)}`;
      }

      if (bkrView.isPanning) {
        bkrView.offsetX = bkrView.panStartOffX + (sx - bkrView.panStartX);
        bkrView.offsetY = bkrView.panStartOffY + (sy - bkrView.panStartY);
        drawBakerCanvas();
        return;
      }

      if (bkrView.draggingLayerId && bkrView.dragStartScene) {
        const dx = sceneX - bkrView.dragStartScene.x;
        const dy = sceneY - bkrView.dragStartScene.y;
        const layers = state.baker.layers || [];
        const lyr = layers.find(l => l.layer_id === bkrView.draggingLayerId);
        if (lyr) {
          if (!bkrView.activeHandle) {
            lyr.position = [
              (lyr.position ? lyr.position[0] : 0) + dx,
              (lyr.position ? lyr.position[1] : 0) + dy
            ];
          }
          bkrView.dragStartScene = { x: sceneX, y: sceneY };
          drawBakerCanvas();
          window.ImageBaker.uiBaker.renderLayerSettings();
        }
      }
    });

    const stopDrag = async e => {
      try {
        bkrCanvas.releasePointerCapture(e.pointerId);
      } catch (_) {}

      if (bkrView.isPanning) {
        bkrView.isPanning = false;
        bkrCanvas.style.cursor = CURSORS.IDLE;
        return;
      }

      if (bkrView.draggingLayerId) {
        bkrView.draggingLayerId = null;
        bkrView.dragStartScene = null;
        bkrView.activeHandle = null;
        await syncLayersToServer(true, "Updated layer transform");
      }
    };

    bkrCanvas.addEventListener("pointerup", stopDrag);
    bkrCanvas.addEventListener("pointercancel", stopDrag);

    bkrCanvas.addEventListener("wheel", e => {
      e.preventDefault();
      const rect = bkrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.15 : 0.87;

      const newZoom = Math.max(0.05, Math.min(40.0, bkrView.zoom * factor));
      bkrView.offsetX = sx - (sx - bkrView.offsetX) * (newZoom / bkrView.zoom);
      bkrView.offsetY = sy - (sy - bkrView.offsetY) * (newZoom / bkrView.zoom);
      bkrView.zoom = newZoom;
      drawBakerCanvas();
    });
  }

  async function syncLayersToServer(pushUndo = true, message = "") {
    try {
      const res = await api.updateBakerLayers(state.baker.layers, pushUndo, message);
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
      }
    } catch (err) {
      console.error("Failed to sync baker layers:", err);
      showToast("baker", "Sync failed: " + err.message);
    }
  }

  function startPlayingStates() {
    const numStates = state.baker.states ? state.baker.states.length : 0;
    if (numStates <= 0) return;
    const fps = Math.max(1, state.configs?.bake_config?.fps || 12);
    const playBtn = document.getElementById("btn-play-states");
    if (playBtn) {
      playBtn.textContent = "⏸ Pause";
      playBtn.classList.add("active");
    }

    state.baker.is_playing = true;
    bkrView.playTimerId = setInterval(async () => {
      const total = state.baker.states ? state.baker.states.length : 0;
      if (total <= 0) {
        stopPlayingStates();
        return;
      }
      const nextStep = ((state.baker.current_step || 0) + 1) % total;
      try {
        const res = await api.manageStates({ action: "seek", step: nextStep });
        if (res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
        }
      } catch (_) {
        stopPlayingStates();
      }
    }, Math.round(1000 / fps));
  }

  function stopPlayingStates() {
    if (bkrView.playTimerId) {
      clearInterval(bkrView.playTimerId);
      bkrView.playTimerId = null;
    }
    state.baker.is_playing = false;
    const playBtn = document.getElementById("btn-play-states");
    if (playBtn) {
      playBtn.textContent = "▶ Play States";
      playBtn.classList.remove("active");
    }
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.canvasBaker = {
    initBakerCanvas,
    resizeBakerCanvas,
    drawBakerCanvas,
    syncLayersToServer,
    startPlayingStates,
    stopPlayingStates,
  };
})(window);
