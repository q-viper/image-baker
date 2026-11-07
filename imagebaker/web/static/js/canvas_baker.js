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

    resizeBakerCanvas();
    bindCanvasEvents();

    if (window.ResizeObserver && bkrCanvasWrap) {
      const ro = new ResizeObserver(() => {
        resizeBakerCanvas();
      });
      ro.observe(bkrCanvasWrap);
    }
  }

  function resizeBakerCanvas() {
    if (!bkrCanvas || !bkrCanvasWrap) return;
    const rect = bkrCanvasWrap.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const cssW = Math.max(10, Math.floor(rect.width));
    const cssH = Math.max(10, Math.floor(rect.height));
    const targetW = Math.round(cssW * dpr);
    const targetH = Math.round(cssH * dpr);
    if (bkrCanvas.width !== targetW || bkrCanvas.height !== targetH) {
      bkrCanvas.width = targetW;
      bkrCanvas.height = targetH;
      bkrCanvas.style.width = `${cssW}px`;
      bkrCanvas.style.height = `${cssH}px`;
      drawBakerCanvas();
    }
  }

  function getLayerImageElement(lyr) {
    const url = lyr.image_url || lyr.thumb_url || lyr.thumbnail;
    if (!url) return null;
    if (bkrView.layerImageCache.has(url)) {
      return bkrView.layerImageCache.get(url);
    }
    const img = new Image();
    img.onload = () => drawBakerCanvas();
    img.onerror = () => {
      console.warn("Failed to load layer image:", url);
    };
    img.src = url;
    bkrView.layerImageCache.set(url, img);
    return img;
  }

  function getBakerLayerLocalHandles(lw, lh, zoom = 1, sx = 1, sy = 1) {
    const rotDist = 24 / (zoom * Math.max(0.2, sy));
    return [
      { id: "nw", x: 0, y: 0, cursor: "nwse-resize", u: 1, v: 1 },
      { id: "n", x: lw / 2, y: 0, cursor: "ns-resize", u: 0.5, v: 1 },
      { id: "ne", x: lw, y: 0, cursor: "nesw-resize", u: 0, v: 1 },
      { id: "e", x: lw, y: lh / 2, cursor: "ew-resize", u: 0, v: 0.5 },
      { id: "se", x: lw, y: lh, cursor: "nwse-resize", u: 0, v: 0 },
      { id: "s", x: lw / 2, y: lh, cursor: "ns-resize", u: 0.5, v: 0 },
      { id: "sw", x: 0, y: lh, cursor: "nesw-resize", u: 1, v: 0 },
      { id: "w", x: 0, y: lh / 2, cursor: "ew-resize", u: 1, v: 0.5 },
      { id: "rot", x: lw / 2, y: -rotDist, cursor: "grab", isRotate: true },
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
      const sx = lyr.scale_x ?? 1.0;
      const sy = lyr.scale_y ?? 1.0;
      const localPt = sceneToLayerLocal(scenePt, lyr, lw, lh);

      if (lyr.selected) {
        const rotDist = 24 / (bkrView.zoom * Math.max(0.2, sy));
        const handleRadius = 14 / (bkrView.zoom * Math.min(Math.max(0.2, sx), Math.max(0.2, sy)));

        // Top rotation handle
        if (Math.hypot(localPt.x - lw / 2, localPt.y - (-rotDist)) <= handleRadius) {
          return { layerId: lyr.layer_id, part: "rotate", handleId: "rot", cursor: "grab" };
        }
        // Center rotation handle
        if (Math.hypot(localPt.x - lw / 2, localPt.y - lh / 2) <= handleRadius * 0.75) {
          return { layerId: lyr.layer_id, part: "rotate", handleId: "center", cursor: "grab" };
        }

        // 8 scale handles
        const handles = getBakerLayerLocalHandles(lw, lh, bkrView.zoom, sx, sy);
        for (const h of handles) {
          if (h.isRotate) continue;
          if (Math.hypot(localPt.x - h.x, localPt.y - h.y) <= handleRadius) {
            return {
              layerId: lyr.layer_id,
              part: "scale",
              handleId: h.id,
              cursor: h.cursor,
              u: h.u,
              v: h.v,
            };
          }
        }
      }

      // Check body
      if (localPt.x >= 0 && localPt.x <= lw && localPt.y >= 0 && localPt.y <= lh) {
        return { layerId: lyr.layer_id, part: "body", cursor: CURSORS.MOVE || "move" };
      }
    }
    return null;
  }

  let drawBakerPending = false;
  function requestDrawBaker() {
    if (drawBakerPending) return;
    drawBakerPending = true;
    requestAnimationFrame(() => {
      drawBakerPending = false;
      drawBakerCanvas();
    });
  }

  function drawBakerCanvas() {
    if (!bkrCanvas || !bkrView.ctx) return;
    const ctx = bkrView.ctx;
    const dpr = window.devicePixelRatio || 1;

    if (bkrCanvasWrap) {
      const rect = bkrCanvasWrap.getBoundingClientRect();
      const wrapW = Math.floor(rect.width);
      const wrapH = Math.floor(rect.height);
      const curCssW = bkrCanvas.width / dpr;
      const curCssH = bkrCanvas.height / dpr;
      if (wrapW > 10 && wrapH > 10 && (Math.abs(wrapW - curCssW) > 2 || Math.abs(wrapH - curCssH) > 2)) {
        resizeBakerCanvas();
        return;
      }
    }

    const cssW = bkrCanvas.width / dpr;
    const cssH = bkrCanvas.height / dpr;

    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, cssW, cssH);

    const isDark = state.theme_mode === "dark";
    ctx.fillStyle = isDark ? "#0d131d" : "#e2e8f0";
    ctx.fillRect(0, 0, cssW, cssH);

    const layers = state.baker.layers || [];

    // Draw Multi-Depth Dimension-Adaptive Gridlines
    if (state.show_gridlines) {
      const hoverPt = bkrView.isMouseOver
        ? { x: bkrView.sceneMouseX * bkrView.zoom + bkrView.offsetX, y: bkrView.sceneMouseY * bkrView.zoom + bkrView.offsetY }
        : null;
      grid.drawGridlines(
        ctx, cssW, cssH, bkrView.offsetX, bkrView.offsetY, bkrView.zoom,
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
      ctx.fillText("Layerify annotations or click 'Add Blank Layer' to composite here.", cssW / 2, cssH / 2);
      ctx.restore();
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
        const isExact1to1 = Math.abs(bkrView.zoom * sx - 1.0) < 0.001 && Math.abs(bkrView.zoom * sy - 1.0) < 0.001 && rotRad === 0;
        const isPixelInspection = (bkrView.zoom * sx) >= 2.0;
        if (isExact1to1 || isPixelInspection) {
          ctx.imageSmoothingEnabled = false;
        } else {
          ctx.imageSmoothingEnabled = true;
          ctx.imageSmoothingQuality = "high";
        }
        ctx.drawImage(img, 0, 0);
      } else {
        ctx.save();
        ctx.strokeStyle = "rgba(79, 140, 255, 0.65)";
        ctx.lineWidth = 2 / Math.max(0.1, bkrView.zoom);
        ctx.setLineDash([6, 4]);
        ctx.fillStyle = "rgba(79, 140, 255, 0.12)";
        ctx.fillRect(0, 0, lw, lh);
        ctx.strokeRect(0, 0, lw, lh);
        ctx.fillStyle = isDark ? "#ffffff" : "#1e293b";
        ctx.font = `bold ${Math.max(12, Math.min(18, lw / 6))}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(lyr.layer_name || lyr.label || "Layer", lw / 2, lh / 2);
        ctx.restore();
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

      // Selection bounding box, 8 scale handles, and rotation handles
      if (lyr.selected) {
        ctx.globalAlpha = 1.0;
        ctx.save();
        ctx.setLineDash([5 / (bkrView.zoom * sx), 4 / (bkrView.zoom * sx)]);
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 1.5 / (bkrView.zoom * Math.max(0.2, sx));
        ctx.strokeRect(0, 0, lw, lh);
        ctx.restore();

        const hSize = 9 / (bkrView.zoom * Math.max(0.2, sx));
        const rotDist = 24 / (bkrView.zoom * Math.max(0.2, sy));
        const handles = getBakerLayerLocalHandles(lw, lh, bkrView.zoom, sx, sy);

        // Draw top rotation stalk
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(lw / 2, 0);
        ctx.lineTo(lw / 2, -rotDist);
        ctx.strokeStyle = "#10b981";
        ctx.lineWidth = 1.5 / (bkrView.zoom * Math.max(0.2, sx));
        ctx.stroke();

        // Top rotation handle
        ctx.beginPath();
        ctx.arc(lw / 2, -rotDist, hSize * 0.75, 0, Math.PI * 2);
        ctx.fillStyle = "#10b981";
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.5 / (bkrView.zoom * Math.max(0.2, sx));
        ctx.stroke();
        ctx.restore();

        // 8 scale handles
        handles.forEach(hp => {
          if (hp.isRotate) return;
          ctx.fillStyle = "#38bdf8";
          ctx.fillRect(hp.x - hSize / 2, hp.y - hSize / 2, hSize, hSize);
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.5 / (bkrView.zoom * Math.max(0.2, sx));
          ctx.strokeRect(hp.x - hSize / 2, hp.y - hSize / 2, hSize, hSize);
        });

        // Center rotation/anchor handle
        ctx.beginPath();
        ctx.arc(lw / 2, lh / 2, hSize * 0.6, 0, Math.PI * 2);
        ctx.fillStyle = "#10b981";
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1 / (bkrView.zoom * Math.max(0.2, sx));
        ctx.stroke();
      }

      ctx.restore();
    });

    ctx.restore();
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

      const isImmediatePan = e.button === 1 || (e.button === 0 && e.spaceKey);
      if (isImmediatePan) {
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
        const multi = e.ctrlKey || e.metaKey || e.shiftKey;
        const lyr = layers.find(l => l.layer_id === hit.layerId);
        if (!lyr) return;

        if (multi) {
          lyr.selected = !lyr.selected;
          if (!lyr.selected) {
            bkrView.draggingLayerId = null;
            bkrView.activeHandle = null;
            bkrView.dragStartTransform = null;
            drawBakerCanvas();
            window.ImageBaker.uiBaker.renderLayerSettings();
            window.ImageBaker.uiBaker.renderLayerLists();
            syncLayersToServer(false, "Toggled layer selection");
            return;
          }
        } else {
          // If clicking an already-selected layer's body when multiple are selected, keep the multi-selection so they move together
          if (!lyr.selected || (hit.part && hit.part !== "body")) {
            layers.forEach(l => {
              l.selected = (l.layer_id === hit.layerId);
            });
          }
        }

        const img = getLayerImageElement(lyr);
        const lw = lyr.width || (img && img.complete ? img.width : 100);
        const lh = lyr.height || (img && img.complete ? img.height : 100);
        const sx = lyr.scale_x ?? 1.0;
        const sy = lyr.scale_y ?? 1.0;
        const posX = lyr.position ? lyr.position[0] : 0;
        const posY = lyr.position ? lyr.position[1] : 0;
        const cx = (lw * sx) / 2;
        const cy = (lh * sy) / 2;

        const selectedLayers = layers.filter(l => l.selected);
        bkrView.draggingLayerId = hit.layerId;
        bkrView.activeHandle = hit.part === "scale" || hit.part === "rotate" ? hit.handleId : null;
        bkrView.dragStartScene = { ...scenePt };
        bkrView.dragStartTransform = {
          position: [posX, posY],
          rotation: lyr.rotation ?? 0,
          scale_x: sx,
          scale_y: sy,
          width: lw,
          height: lh,
          centerScene: { x: posX + cx, y: posY + cy },
          startScenePt: { ...scenePt },
          initialAngle: Math.atan2(scenePt.y - (posY + cy), scenePt.x - (posX + cx)),
          u: hit.u ?? 0.5,
          v: hit.v ?? 0.5,
          part: hit.part,
          selectedLayersStarts: selectedLayers.map(l => ({
            layer_id: l.layer_id,
            position: l.position ? [...l.position] : [0, 0]
          }))
        };
        drawBakerCanvas();
        window.ImageBaker.uiBaker.renderLayerSettings();
        window.ImageBaker.uiBaker.renderLayerLists();
        bkrView.hasMovedDuringDrag = false;
      } else {
        // Ctrl/Cmd + drag on empty space pans the Baker canvas
        if (e.ctrlKey || e.metaKey) {
          bkrView.isPanning = true;
          bkrView.panStartX = sx;
          bkrView.panStartY = sy;
          bkrView.panStartOffX = bkrView.offsetX;
          bkrView.panStartOffY = bkrView.offsetY;
          bkrCanvas.style.cursor = CURSORS.PAN_ACTIVE;
          return;
        }
        // Deselect all
        (state.baker.layers || []).forEach(l => l.selected = false);
        bkrView.draggingLayerId = null;
        bkrView.activeHandle = null;
        bkrView.dragStartTransform = null;
        drawBakerCanvas();
        window.ImageBaker.uiBaker.renderLayerSettings();
        window.ImageBaker.uiBaker.renderLayerLists();
        syncLayersToServer(false, "Deselected all layers");
      }
    });

    bkrCanvas.addEventListener("pointermove", e => {
      const rect = bkrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const sceneX = (sx - bkrView.offsetX) / bkrView.zoom;
      const sceneY = (sy - bkrView.offsetY) / bkrView.zoom;
      const scenePt = { x: sceneX, y: sceneY };
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
        requestDrawBaker();
        return;
      }

      if (!bkrView.draggingLayerId && !bkrView.isPanning) {
        if (e.ctrlKey || e.metaKey || e.spaceKey) {
          bkrCanvas.style.cursor = CURSORS.PAN;
        } else if (bkrView.drawingMode || bkrView.drawMode) {
          bkrCanvas.style.cursor = CURSORS.DRAW;
        } else if (bkrView.eraseMode) {
          bkrCanvas.style.cursor = CURSORS.ERASE;
        } else {
          const hit = hitTestBakerLayer(scenePt);
          bkrCanvas.style.cursor = hit ? (hit.cursor || CURSORS.MOVE || "move") : CURSORS.IDLE;
        }
      }

      if (bkrView.draggingLayerId && bkrView.dragStartTransform) {
        bkrView.hasMovedDuringDrag = true;
        const start = bkrView.dragStartTransform;
        const layers = state.baker.layers || [];
        const lyr = layers.find(l => l.layer_id === bkrView.draggingLayerId);
        if (lyr) {
          if (!bkrView.activeHandle || start.part === "body") {
            const dx = sceneX - start.startScenePt.x;
            const dy = sceneY - start.startScenePt.y;
            if (start.selectedLayersStarts && start.selectedLayersStarts.length > 1) {
              start.selectedLayersStarts.forEach(s => {
                const targetLyr = layers.find(l => l.layer_id === s.layer_id);
                if (targetLyr) {
                  targetLyr.position = [
                    Math.round(s.position[0] + dx),
                    Math.round(s.position[1] + dy)
                  ];
                }
              });
            } else {
              lyr.position = [
                Math.round(start.position[0] + dx),
                Math.round(start.position[1] + dy)
              ];
            }
            requestDrawBaker();
            window.ImageBaker.uiBaker.renderLayerSettings();
          } else if (start.part === "rotate") {
            const curAngle = Math.atan2(sceneY - start.centerScene.y, sceneX - start.centerScene.x);
            const deltaAngle = (curAngle - start.initialAngle) * (180 / Math.PI);
            let newRot = Math.round(((start.rotation + deltaAngle) % 360 + 360) % 360 * 10) / 10;
            if (e.shiftKey) {
              newRot = Math.round(newRot / 15) * 15;
            }
            lyr.rotation = ((newRot % 360) + 360) % 360;
            requestDrawBaker();
            window.ImageBaker.uiBaker.renderLayerSettings();
          } else if (start.part === "scale") {
            const dxScene = sceneX - start.startScenePt.x;
            const dyScene = sceneY - start.startScenePt.y;
            const rotRad = (start.rotation * Math.PI) / 180;
            const cosR = Math.cos(rotRad);
            const sinR = Math.sin(rotRad);

            // Project delta into local unrotated layer axes
            const dxLocal = dxScene * cosR + dyScene * sinR;
            const dyLocal = -dxScene * sinR + dyScene * cosR;

            let newSx = start.scale_x;
            let newSy = start.scale_y;
            const origW = start.width;
            const origH = start.height;

            const hid = bkrView.activeHandle;
            if (hid === "se") {
              newSx = start.scale_x + dxLocal / origW;
              newSy = start.scale_y + dyLocal / origH;
            } else if (hid === "nw") {
              newSx = start.scale_x - dxLocal / origW;
              newSy = start.scale_y - dyLocal / origH;
            } else if (hid === "ne") {
              newSx = start.scale_x + dxLocal / origW;
              newSy = start.scale_y - dyLocal / origH;
            } else if (hid === "sw") {
              newSx = start.scale_x - dxLocal / origW;
              newSy = start.scale_y + dyLocal / origH;
            } else if (hid === "e") {
              newSx = start.scale_x + dxLocal / origW;
            } else if (hid === "w") {
              newSx = start.scale_x - dxLocal / origW;
            } else if (hid === "s") {
              newSy = start.scale_y + dyLocal / origH;
            } else if (hid === "n") {
              newSy = start.scale_y - dyLocal / origH;
            }

            if (e.shiftKey && (hid === "se" || hid === "nw" || hid === "ne" || hid === "sw")) {
              const scaleFactor = Math.max(newSx / start.scale_x, newSy / start.scale_y);
              newSx = start.scale_x * scaleFactor;
              newSy = start.scale_y * scaleFactor;
            }

            newSx = Math.max(0.05, Math.min(20.0, Math.round(newSx * 1000) / 1000));
            newSy = Math.max(0.05, Math.min(20.0, Math.round(newSy * 1000) / 1000));

            // Compute anchor scene coordinates at drag start
            const u = start.u;
            const v = start.v;
            const cx0 = (origW * start.scale_x) / 2;
            const cy0 = (origH * start.scale_y) / 2;
            const offX0 = (u - 0.5) * origW * start.scale_x;
            const offY0 = (v - 0.5) * origH * start.scale_y;
            const rotOffX0 = offX0 * cosR - offY0 * sinR;
            const rotOffY0 = offX0 * sinR + offY0 * cosR;
            const anchorSceneX = start.position[0] + cx0 + rotOffX0;
            const anchorSceneY = start.position[1] + cy0 + rotOffY0;

            // Compute new center and top-left position from fixed anchor
            const cxNew = (origW * newSx) / 2;
            const cyNew = (origH * newSy) / 2;
            const offXNew = (u - 0.5) * origW * newSx;
            const offYNew = (v - 0.5) * origH * newSy;
            const rotOffXNew = offXNew * cosR - offYNew * sinR;
            const rotOffYNew = offXNew * sinR + offYNew * cosR;

            const centerNewX = anchorSceneX - rotOffXNew;
            const centerNewY = anchorSceneY - rotOffYNew;

            lyr.scale_x = newSx;
            lyr.scale_y = newSy;
            lyr.position = [
              Math.round((centerNewX - cxNew) * 10) / 10,
              Math.round((centerNewY - cyNew) * 10) / 10
            ];

            requestDrawBaker();
            window.ImageBaker.uiBaker.renderLayerSettings();
          }
        }
      }
    });

    const stopDrag = async e => {
      try {
        bkrCanvas.releasePointerCapture(e.pointerId);
      } catch (_) {}

      if (bkrView.isPanning) {
        bkrView.isPanning = false;
        bkrCanvas.style.cursor = (e.ctrlKey || e.metaKey || e.spaceKey) ? CURSORS.PAN : CURSORS.IDLE;
        return;
      }

      if (bkrView.draggingLayerId) {
        const clickedLayerId = bkrView.draggingLayerId;
        const moved = Boolean(bkrView.hasMovedDuringDrag);
        const multi = e && (e.ctrlKey || e.metaKey || e.shiftKey);
        bkrView.draggingLayerId = null;
        bkrView.dragStartScene = null;
        bkrView.dragStartTransform = null;
        bkrView.activeHandle = null;
        bkrView.hasMovedDuringDrag = false;
        if (moved) {
          await syncLayersToServer(true, "Updated layer transform");
        } else {
          if (!multi) {
            const layers = state.baker.layers || [];
            layers.forEach(l => {
              l.selected = (l.layer_id === clickedLayerId);
            });
            drawBakerCanvas();
            window.ImageBaker.uiBaker.renderLayerSettings();
            window.ImageBaker.uiBaker.renderLayerLists();
          }
          await syncLayersToServer(false, "Selected layer");
        }
      }
    };

    bkrCanvas.addEventListener("pointerup", stopDrag);
    bkrCanvas.addEventListener("pointercancel", stopDrag);

    bkrCanvas.addEventListener("contextmenu", e => {
      e.preventDefault();
      if (bkrView.drawingMode || bkrView.eraseMode) {
        bkrView.drawingMode = false;
        bkrView.eraseMode = false;
        const drawBtn = document.getElementById("btn-draw-mode");
        const eraseBtn = document.getElementById("btn-erase-mode");
        if (drawBtn) drawBtn.classList.remove("active");
        if (eraseBtn) eraseBtn.classList.remove("active");
      }
      const rect = bkrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const sceneX = (sx - bkrView.offsetX) / bkrView.zoom;
      const sceneY = (sy - bkrView.offsetY) / bkrView.zoom;
      const hit = hitTestBakerLayer({ x: sceneX, y: sceneY });
      if (!hit) {
        const layers = state.baker.layers || [];
        if (layers.some(l => l.selected)) {
          layers.forEach(l => {
            l.selected = false;
          });
          bkrView.draggingLayerId = null;
          bkrView.activeHandle = null;
          bkrView.dragStartTransform = null;
          drawBakerCanvas();
          window.ImageBaker.uiBaker.renderLayerSettings();
          window.ImageBaker.uiBaker.renderLayerLists();
          syncLayersToServer(false, "Deselected all layers");
          return;
        }
      }
      drawBakerCanvas();
    });

    bkrCanvas.addEventListener("wheel", e => {
      e.preventDefault();
      if (bkrView.drawingMode || bkrView.eraseMode) {
        const delta = e.deltaY < 0 ? 2 : -2;
        bkrView.brushSize = Math.max(1, Math.min(200, (bkrView.brushSize || 12) + delta));
        showToast("baker", `Brush size: ${bkrView.brushSize}px`);
        return;
      }

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

    window.addEventListener("keydown", e => {
      if (window.ImageBaker.isTypingInTextField && window.ImageBaker.isTypingInTextField(e.target)) return;
      if (window.ImageBaker.isModalOpen && window.ImageBaker.isModalOpen()) return;
      if (state.active_tab === "Baker" && (e.key === "Control" || e.key === "Meta") && !bkrView.isPanning) {
        if (bkrCanvas) bkrCanvas.style.cursor = CURSORS.PAN;
      }
    });

    window.addEventListener("keyup", e => {
      if (state.active_tab === "Baker" && (e.key === "Control" || e.key === "Meta") && !bkrView.isPanning) {
        if (bkrCanvas) bkrCanvas.style.cursor = CURSORS.IDLE;
      }
    });
  }

  async function syncLayersToServer(pushUndo = true, message = "") {
    const seq = (bkrView.syncSeq || 0) + 1;
    bkrView.syncSeq = seq;
    bkrView.isSyncing = true;
    const payload = structuredClone(state.baker.layers || []);
    try {
      const res = await api.updateBakerLayers(payload, pushUndo, message);
      if (seq !== bkrView.syncSeq) {
        return;
      }
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
      }
    } catch (err) {
      if (seq === bkrView.syncSeq) {
        console.error("Failed to sync baker layers:", err);
        showToast("baker", "Sync failed: " + err.message);
      }
    } finally {
      if (seq === bkrView.syncSeq) {
        bkrView.isSyncing = false;
      }
    }
  }

  function startPlayingStates() {
    stopPlayingStates();
    const numStates = state.baker.states ? state.baker.states.length : (state.baker.num_states || 0);
    if (numStates <= 0) {
      showToast("baker", "No saved states to play");
      return;
    }

    bkrView.isPlaying = true;
    state.baker.is_playing = true;
    const sessionId = (bkrView.playSessionId || 0) + 1;
    bkrView.playSessionId = sessionId;

    const playBtn = document.getElementById("btn-play-states");
    if (playBtn) {
      playBtn.textContent = "⏸ Pause";
      playBtn.classList.add("active");
    }

    const stepIntervalMs = 500;

    const tick = async () => {
      if (!bkrView.isPlaying || bkrView.playSessionId !== sessionId) return;
      const total = state.baker.states ? state.baker.states.length : (state.baker.num_states || 0);
      if (total <= 0 || state.active_tab !== "Baker") {
        stopPlayingStates();
        return;
      }
      const curStep = state.baker.current_step ?? state.baker.current_state_step ?? 0;
      const nextStep = (curStep + 1) % total;
      try {
        const res = await api.manageStates({ action: "seek", step: nextStep });
        if (!bkrView.isPlaying || bkrView.playSessionId !== sessionId) return;
        if (res && res.ok && res.state) {
          window.ImageBaker.applyServerState(res.state);
        }
      } catch (_) {
        stopPlayingStates();
        return;
      }
      if (bkrView.isPlaying && bkrView.playSessionId === sessionId) {
        bkrView.playTimerId = setTimeout(tick, stepIntervalMs);
      }
    };

    bkrView.playTimerId = setTimeout(tick, stepIntervalMs);
  }

  function stopPlayingStates() {
    bkrView.isPlaying = false;
    if (state.baker) state.baker.is_playing = false;
    bkrView.playSessionId = (bkrView.playSessionId || 0) + 1;
    if (bkrView.playTimerId) {
      clearTimeout(bkrView.playTimerId);
      clearInterval(bkrView.playTimerId);
      bkrView.playTimerId = null;
    }
    const playBtn = document.getElementById("btn-play-states");
    if (playBtn) {
      playBtn.textContent = "▶ Play States";
      playBtn.classList.remove("active");
    }
  }

  let lastFittedCanvasId = null;
  let lastFittedLayerCount = -1;

  function fitBakerLayersIfNeeded(force = false) {
    if (!bkrCanvas || !bkrCanvasWrap) return;
    const dpr = window.devicePixelRatio || 1;
    const cw = bkrCanvas.width / dpr;
    const ch = bkrCanvas.height / dpr;
    if (cw <= 10 || ch <= 10) return;

    const currentCanvasId = state.baker?.current_canvas_id;
    const layers = state.baker?.layers || [];

    if (!force && lastFittedCanvasId === currentCanvasId && lastFittedLayerCount === layers.length && (bkrView.zoom !== 1.0 || bkrView.offsetX !== 0 || bkrView.offsetY !== 0)) {
      return;
    }

    lastFittedCanvasId = currentCanvasId;
    lastFittedLayerCount = layers.length;

    if (layers.length === 0) {
      const targetW = 960;
      const targetH = 640;
      const fitZoom = Math.min((cw - 80) / targetW, (ch - 80) / targetH, 1.0);
      bkrView.zoom = Math.max(0.2, fitZoom);
      bkrView.offsetX = Math.round((cw - targetW * bkrView.zoom) / 2);
      bkrView.offsetY = Math.round((ch - targetH * bkrView.zoom) / 2);
      drawBakerCanvas();
      return;
    }

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    layers.forEach(lyr => {
      if (lyr.visible === false) return;
      const px = lyr.position ? lyr.position[0] : 0;
      const py = lyr.position ? lyr.position[1] : 0;
      const sx = lyr.scale_x ?? 1.0;
      const sy = lyr.scale_y ?? 1.0;
      const img = getLayerImageElement(lyr);
      const lw = (lyr.width || (img && img.complete ? img.width : 200)) * sx;
      const lh = (lyr.height || (img && img.complete ? img.height : 200)) * sy;

      minX = Math.min(minX, px);
      minY = Math.min(minY, py);
      maxX = Math.max(maxX, px + lw);
      maxY = Math.max(maxY, py + lh);
    });

    if (!isFinite(minX) || !isFinite(maxX)) {
      minX = 0; minY = 0; maxX = 960; maxY = 640;
    }

    const boxW = Math.max(50, maxX - minX);
    const boxH = Math.max(50, maxY - minY);
    const padding = 60;
    const scaleX = (cw - padding) / boxW;
    const scaleY = (ch - padding) / boxH;
    const fitZoom = Math.max(0.05, Math.min(scaleX, scaleY, 1.0));

    bkrView.zoom = fitZoom;
    const boxCenterX = minX + boxW / 2;
    const boxCenterY = minY + boxH / 2;
    bkrView.offsetX = Math.round(cw / 2 - boxCenterX * fitZoom);
    bkrView.offsetY = Math.round(ch / 2 - boxCenterY * fitZoom);
    drawBakerCanvas();
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.canvasBaker = {
    initBakerCanvas,
    resizeBakerCanvas,
    drawBakerCanvas,
    fitBakerLayersIfNeeded,
    syncLayersToServer,
    startPlayingStates,
    stopPlayingStates,
  };
})(window);

