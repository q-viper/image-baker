/**
 * ImageBaker Web - Layerify Canvas Engine
 */
(function(window) {
  "use strict";

  const { state, lyrView, CURSORS, screenToImage, imageToScreen, showToast } = window.ImageBaker;
  const utils = window.ImageBaker.utils;
  const api = window.ImageBaker.api;
  const grid = window.ImageBaker.grid;

  let lyrCanvas, lyrCanvasWrap;

  function initLayerifyCanvas() {
    lyrCanvas = document.getElementById("layerify-canvas");
    lyrCanvasWrap = document.getElementById("layerify-canvas-wrap");
    if (!lyrCanvas || !lyrCanvasWrap) return;

    lyrView.canvas = lyrCanvas;
    lyrView.ctx = lyrCanvas.getContext("2d");
    lyrView.wrap = lyrCanvasWrap;

    resizeLayerifyCanvas();
    bindCanvasEvents();
    bindHudEvents();
  }

  function resizeLayerifyCanvas() {
    if (!lyrCanvas || !lyrCanvasWrap) return;
    const rect = lyrCanvasWrap.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const cssW = Math.max(10, Math.floor(rect.width));
    const cssH = Math.max(10, Math.floor(rect.height));
    const targetW = Math.round(cssW * dpr);
    const targetH = Math.round(cssH * dpr);
    if (lyrCanvas.width !== targetW || lyrCanvas.height !== targetH) {
      lyrCanvas.width = targetW;
      lyrCanvas.height = targetH;
      lyrCanvas.style.width = `${cssW}px`;
      lyrCanvas.style.height = `${cssH}px`;
      drawLayerifyCanvas();
    }
  }

  function fitLayerifyImageIfNeeded() {
    if (!lyrView.img || lyrView.img.width <= 0 || lyrView.img.height <= 0) return;
    if (!lyrCanvas) return;
    const dpr = window.devicePixelRatio || 1;
    const cw = lyrCanvas.width / dpr;
    const ch = lyrCanvas.height / dpr;
    if (cw <= 0 || ch <= 0) return;

    const scaleX = (cw - 60) / lyrView.img.width;
    const scaleY = (ch - 60) / lyrView.img.height;
    const fitZoom = Math.min(scaleX, scaleY, 1.0);
    lyrView.zoom = Math.max(0.05, fitZoom);
    lyrView.offsetX = Math.round((cw - lyrView.img.width * lyrView.zoom) / 2);
    lyrView.offsetY = Math.round((ch - lyrView.img.height * lyrView.zoom) / 2);
    drawLayerifyCanvas();
  }

  function syncLayerifyImage(lyr) {
    const idx = lyr.current_image_index;
    const rev = lyr.current_image_revision || 0;
    if (idx === null || idx === undefined || idx < 0) {
      lyrView.img = null;
      lyrView.imgKey = "";
      lyrView.isLoadingImage = false;
      if (window.ImageBaker.uiLayerify?.hideLoading) {
        window.ImageBaker.uiLayerify.hideLoading();
      }
      drawLayerifyCanvas();
      return;
    }
    const key = `${idx}:${rev}:${lyr.current_image_name}`;
    if (lyrView.imgKey === key && lyrView.img) {
      if (window.ImageBaker.uiLayerify?.hideLoading) {
        window.ImageBaker.uiLayerify.hideLoading();
      }
      return;
    }
    lyrView.imgKey = key;
    lyrView.img = null;
    lyrView.isLoadingImage = true;
    if (window.ImageBaker.uiLayerify?.showLoading) {
      window.ImageBaker.uiLayerify.showLoading(`Loading ${lyr.current_image_name || "image"}…`);
    }
    drawLayerifyCanvas();

    const img = new Image();
    img.onload = () => {
      if (lyrView.imgKey !== key) return;
      lyrView.img = img;
      lyrView.isLoadingImage = false;
      if (window.ImageBaker.uiLayerify?.hideLoading) {
        window.ImageBaker.uiLayerify.hideLoading();
      }
      fitLayerifyImageIfNeeded();
      drawLayerifyCanvas();
      if (window.ImageBaker.updateZoomReadout) {
        window.ImageBaker.updateZoomReadout();
      }
    };
    img.onerror = () => {
      if (lyrView.imgKey !== key) return;
      lyrView.isLoadingImage = false;
      if (window.ImageBaker.uiLayerify?.hideLoading) {
        window.ImageBaker.uiLayerify.hideLoading();
      }
      drawLayerifyCanvas();
    };
    img.src = `/api/layerify/image?index=${idx}&rev=${rev}`;
  }

  function preloadAnnotationMasks(annotations) {
    (annotations || []).forEach(ann => {
      if (ann.mask_png_b64 && !lyrView.maskImageCache.has(ann.annotation_id)) {
        const mImg = new Image();
        mImg.onload = () => drawLayerifyCanvas();
        mImg.src = "data:image/png;base64," + ann.mask_png_b64;
        lyrView.maskImageCache.set(ann.annotation_id, mImg);
      }
    });
  }

  function hitTestAnnotation(ix, iy) {
    const tol = 7 / lyrView.zoom;
    const scr = imageToScreen(ix, iy);
    for (let p = lyrView.labelPillRects.length - 1; p >= 0; p--) {
      const pill = lyrView.labelPillRects[p];
      if (
        scr.x >= pill.x - 2 &&
        scr.x <= pill.x + pill.w + 2 &&
        scr.y >= pill.y - 2 &&
        scr.y <= pill.y + pill.h + 2
      ) {
        return pill.annIdx;
      }
    }

    const annotations = state.layerify.annotations || [];
    for (let i = annotations.length - 1; i >= 0; i--) {
      const ann = annotations[i];
      if (ann.visible === false) continue;
      if (ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        for (const pt of ann.points) {
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol * 1.3) return i;
        }
      }
    }

    const hits = [];
    for (let i = annotations.length - 1; i >= 0; i--) {
      const ann = annotations[i];
      if (ann.visible === false) continue;
      if (ann.polygon && ann.polygon.length >= 3) {
        let onVert = false;
        for (const pt of ann.polygon) {
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol) {
            onVert = true;
            break;
          }
        }
        if (onVert || utils.pointInPolygon(ix, iy, ann.polygon)) {
          const xs = ann.polygon.map(p => p[0]);
          const ys = ann.polygon.map(p => p[1]);
          const area = Math.max(1, (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys)));
          hits.push({ idx: i, area });
          continue;
        }
      }
      if (ann.rectangle && ann.rectangle.length === 4) {
        const [x1, y1, x2, y2] = ann.rectangle;
        const rx1 = Math.min(x1, x2);
        const ry1 = Math.min(y1, y2);
        const rx2 = Math.max(x1, x2);
        const ry2 = Math.max(y1, y2);
        if (ix >= rx1 - tol && ix <= rx2 + tol && iy >= ry1 - tol && iy <= ry2 + tol) {
          const area = Math.max(1, (rx2 - rx1) * (ry2 - ry1));
          hits.push({ idx: i, area });
        }
      }
    }
    if (hits.length > 0) {
      hits.sort((a, b) => a.area - b.area);
      return hits[0].idx;
    }
    return null;
  }

  function hitTestAnnotationHandle(ix, iy) {
    const tol = 8.5 / lyrView.zoom;
    const annotations = state.layerify.annotations || [];
    const indices = [];
    for (let i = annotations.length - 1; i >= 0; i--) {
      if (annotations[i].visible !== false && annotations[i].selected) indices.push(i);
    }
    for (let i = annotations.length - 1; i >= 0; i--) {
      if (annotations[i].visible !== false && !annotations[i].selected) indices.push(i);
    }

    for (const i of indices) {
      const ann = annotations[i];
      if (ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        for (let p = 0; p < ann.points.length; p++) {
          const pt = ann.points[p];
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol * 1.2) {
            return { annIdx: i, type: "point", handleIdx: p };
          }
        }
      }
      if (ann.rectangle && ann.rectangle.length === 4) {
        const handles = utils.getRectHandles(ann.rectangle);
        for (let h = 0; h < handles.length; h++) {
          if (Math.hypot(ix - handles[h].x, iy - handles[h].y) <= tol) {
            return { annIdx: i, type: "rect", handleIdx: h, handleId: handles[h].id };
          }
        }
      }
      if (ann.polygon && ann.polygon.length >= 3) {
        for (let v = 0; v < ann.polygon.length; v++) {
          const pt = ann.polygon[v];
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol) {
            return { annIdx: i, type: "poly", handleIdx: v };
          }
        }
      }
    }
    return null;
  }

  function drawLayerifyCanvas() {
    if (!lyrCanvas || !lyrView.ctx) return;
    const ctx = lyrView.ctx;
    const dpr = window.devicePixelRatio || 1;
    const w = lyrCanvas.width / dpr;
    const h = lyrCanvas.height / dpr;

    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, w, h);
    lyrView.labelPillRects = [];

    // Background Canvas Fill
    const isDark = state.theme_mode === "dark";
    ctx.fillStyle = isDark ? "#0d131d" : "#e2e8f0";
    ctx.fillRect(0, 0, w, h);

    // 1. Draw Image with original full resolution & high-quality interpolation
    if (lyrView.img && lyrView.img.complete && lyrView.img.width > 0) {
      const sw = lyrView.img.width * lyrView.zoom;
      const sh = lyrView.img.height * lyrView.zoom;
      const isExact1to1 = Math.abs(lyrView.zoom - 1.0) < 0.001;
      const isPixelInspection = lyrView.zoom >= 2.0;

      if (isExact1to1) {
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(
          lyrView.img,
          Math.round(lyrView.offsetX),
          Math.round(lyrView.offsetY),
          lyrView.img.width,
          lyrView.img.height
        );
      } else if (isPixelInspection) {
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(
          lyrView.img,
          Math.round(lyrView.offsetX),
          Math.round(lyrView.offsetY),
          Math.round(sw),
          Math.round(sh)
        );
      } else {
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(lyrView.img, lyrView.offsetX, lyrView.offsetY, sw, sh);
      }
    } else {
      ctx.fillStyle = isDark ? "#475569" : "#94a3b8";
      ctx.font = "14px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("No Image Loaded", w / 2, h / 2);
    }

    // 2. Draw Multi-Depth Dimension-Adaptive Gridlines
    if (state.show_gridlines) {
      const hoverPt = lyrView.isMouseOver
        ? { x: imageToScreen(lyrView.mouseImgX, lyrView.mouseImgY).x, y: imageToScreen(lyrView.mouseImgX, lyrView.mouseImgY).y }
        : null;
      grid.drawGridlines(
        ctx, w, h, lyrView.offsetX, lyrView.offsetY, lyrView.zoom,
        hoverPt,
        lyrView.imgW || (lyrView.img ? lyrView.img.width : 800),
        lyrView.imgH || (lyrView.img ? lyrView.img.height : 600)
      );
    }

    // 3. Draw Annotations
    const annotations = state.layerify.annotations || [];
    annotations.forEach((ann, annIdx) => {
      if (ann.visible === false) return;
      const isSel = Boolean(ann.selected);
      const isHov = lyrView.hoverAnnIdx === annIdx;
      const [r, g, b] = ann.color || [47, 128, 237];
      const strokeCol = `rgb(${r}, ${g}, ${b})`;
      const fillCol = isSel ? `rgba(${r}, ${g}, ${b}, 0.28)` : (isHov ? `rgba(${r}, ${g}, ${b}, 0.18)` : `rgba(${r}, ${g}, ${b}, 0.08)`);

      ctx.save();
      ctx.lineWidth = isSel ? 2.5 : (isHov ? 2.0 : 1.5);
      ctx.strokeStyle = strokeCol;
      ctx.fillStyle = fillCol;

      // Draw Raster Mask (if any)
      if (ann.has_mask || ann.mask_png_b64) {
        const mImg = lyrView.maskImageCache.get(ann.annotation_id);
        if (mImg && mImg.complete) {
          ctx.save();
          ctx.globalAlpha = isSel ? 0.65 : 0.45;
          const maskX = lyrView.offsetX + (ann.mask_offset_x || 0) * lyrView.zoom;
          const maskY = lyrView.offsetY + (ann.mask_offset_y || 0) * lyrView.zoom;
          ctx.drawImage(mImg, maskX, maskY, mImg.width * lyrView.zoom, mImg.height * lyrView.zoom);
          ctx.restore();
        }
      }

      // Draw Rectangle
      if (ann.rectangle && ann.rectangle.length === 4) {
        const [x1, y1, x2, y2] = ann.rectangle;
        const s1 = imageToScreen(Math.min(x1, x2), Math.min(y1, y2));
        const s2 = imageToScreen(Math.max(x1, x2), Math.max(y1, y2));
        const rw = s2.x - s1.x;
        const rh = s2.y - s1.y;

        ctx.fillRect(s1.x, s1.y, rw, rh);
        ctx.strokeRect(s1.x, s1.y, rw, rh);

        // Resize handles if selected
        if (isSel) {
          const handles = utils.getRectHandles(ann.rectangle);
          handles.forEach(hnd => {
            const sh = imageToScreen(hnd.x, hnd.y);
            ctx.fillStyle = "#ffffff";
            ctx.strokeStyle = strokeCol;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(sh.x, sh.y, 4.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          });
        }
      }

      // Draw Polygon
      if (ann.polygon && ann.polygon.length >= 3) {
        ctx.beginPath();
        ann.polygon.forEach((pt, pidx) => {
          const sp = imageToScreen(pt[0], pt[1]);
          if (pidx === 0) ctx.moveTo(sp.x, sp.y);
          else ctx.lineTo(sp.x, sp.y);
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Polygon vertex handles if selected
        if (isSel) {
          ann.polygon.forEach(pt => {
            const sp = imageToScreen(pt[0], pt[1]);
            ctx.fillStyle = "#ffffff";
            ctx.strokeStyle = strokeCol;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          });
        }
      }

      // Draw Point
      if (ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        ann.points.forEach(pt => {
          const sp = imageToScreen(pt[0], pt[1]);
          ctx.fillStyle = strokeCol;
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(sp.x, sp.y, isSel ? 6.5 : 5, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        });
      }

      // Draw Interactive Label Pill
      const anchor = utils.getAnnotationAnchorPoint(ann);
      const scrAnchor = imageToScreen(anchor.x, anchor.y);
      const pillLabel = ann.label || "Undefined";
      ctx.font = "bold 11px system-ui, sans-serif";
      const txtWidth = ctx.measureText(pillLabel).width;
      const pillW = txtWidth + 16;
      const pillH = 18;
      const pillX = scrAnchor.x;
      const pillY = Math.max(2, scrAnchor.y - 20);

      lyrView.labelPillRects.push({
        annIdx,
        x: pillX,
        y: pillY,
        w: pillW,
        h: pillH
      });

      ctx.fillStyle = strokeCol;
      utils.roundRect(ctx, pillX, pillY, pillW, pillH, 4);
      ctx.fill();

      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(pillLabel, pillX + 8, pillY + pillH / 2);

      ctx.restore();
    });

    // 4. Draw Active Rectangle Draft
    if (lyrView.activeRectDraft) {
      const [x1, y1, x2, y2] = lyrView.activeRectDraft;
      const s1 = imageToScreen(Math.min(x1, x2), Math.min(y1, y2));
      const s2 = imageToScreen(Math.max(x1, x2), Math.max(y1, y2));
      ctx.save();
      ctx.strokeStyle = window.ImageBaker.getCurrentSelectedLabelColor();
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(s1.x, s1.y, s2.x - s1.x, s2.y - s1.y);
      ctx.restore();
    }

    // 5. Draw Active Polygon Draft
    if (lyrView.activePolyDraft && lyrView.activePolyDraft.length > 0) {
      ctx.save();
      ctx.strokeStyle = window.ImageBaker.getCurrentSelectedLabelColor();
      ctx.lineWidth = 2;
      ctx.beginPath();
      lyrView.activePolyDraft.forEach((pt, idx) => {
        const sp = imageToScreen(pt.x, pt.y);
        if (idx === 0) ctx.moveTo(sp.x, sp.y);
        else ctx.lineTo(sp.x, sp.y);
      });
      if (lyrView.isMouseOver) {
        const curSp = imageToScreen(lyrView.mouseImgX, lyrView.mouseImgY);
        ctx.lineTo(curSp.x, curSp.y);
      }
      ctx.stroke();

      lyrView.activePolyDraft.forEach(pt => {
        const sp = imageToScreen(pt.x, pt.y);
        ctx.fillStyle = "#ffffff";
        ctx.strokeStyle = window.ImageBaker.getCurrentSelectedLabelColor();
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      });
      ctx.restore();
    }

    // 6. Draw Active Brush Stroke
    if (lyrView.activeBrushStroke && lyrView.activeBrushStroke.length > 0) {
      ctx.save();
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.lineWidth = lyrView.brushSize * lyrView.zoom;
      ctx.strokeStyle = window.ImageBaker.getCurrentSelectedLabelColor();
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      lyrView.activeBrushStroke.forEach((pt, idx) => {
        const sp = imageToScreen(pt.x, pt.y);
        if (idx === 0) ctx.moveTo(sp.x, sp.y);
        else ctx.lineTo(sp.x, sp.y);
      });
      ctx.stroke();
      ctx.restore();
    }

    ctx.restore();
  }

  function setLayerifyMode(mode) {
    lyrView.activeMode = mode;
    lyrView.activeRectDraft = null;
    lyrView.activePolyDraft = [];
    lyrView.activeBrushStroke = [];

    document.querySelectorAll(".ls-tool-btn.mode-btn").forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-mode") === mode);
    });

    const pill = document.getElementById("hud-mode-pill");
    const hint = document.getElementById("hud-mode-hint");
    const brushWrap = document.getElementById("hud-brush-wrap");
    const finishPoly = document.getElementById("btn-finish-polygon");

    if (pill) pill.textContent = `Mode: ${mode}`;
    if (brushWrap) brushWrap.classList.toggle("hidden", mode !== "Brush");
    if (finishPoly) finishPoly.classList.toggle("hidden", mode !== "Polygon");

    if (hint) {
      switch (mode) {
        case "Rectangle": hint.textContent = "Drag to draw rectangle • Click region to select/resize"; break;
        case "Polygon": hint.textContent = "Click to place vertices • Double-click or press Enter to close"; break;
        case "Point": hint.textContent = "Click to place keypoint markers"; break;
        case "Brush": hint.textContent = "Click and drag to brush segmentation mask"; break;
        case "Pan": hint.textContent = "Drag to pan viewport • Mouse wheel to zoom"; break;
        default: hint.textContent = "Click any region or label pill to select and move"; break;
      }
    }

    if (lyrCanvas) {
      switch (mode) {
        case "Pan": lyrCanvas.style.cursor = CURSORS.PAN; break;
        case "Rectangle":
        case "Point":
        case "Polygon": lyrCanvas.style.cursor = CURSORS.RECTANGLE; break;
        case "Brush": lyrCanvas.style.cursor = CURSORS.BRUSH; break;
        default: lyrCanvas.style.cursor = CURSORS.IDLE; break;
      }
    }
    drawLayerifyCanvas();
  }

  function bindCanvasEvents() {
    if (!lyrCanvas) return;

    lyrCanvas.addEventListener("pointerdown", e => {
      lyrCanvas.setPointerCapture(e.pointerId);
      const rect = lyrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const imgPt = screenToImage(sx, sy);

      if (e.button === 1 || lyrView.activeMode === "Pan" || (e.button === 0 && e.spaceKey)) {
        lyrView.isPanning = true;
        lyrView.panStartX = sx;
        lyrView.panStartY = sy;
        lyrView.panStartOffX = lyrView.offsetX;
        lyrView.panStartOffY = lyrView.offsetY;
        lyrCanvas.style.cursor = CURSORS.PAN_ACTIVE;
        return;
      }

      if (e.button !== 0) return;

      // 1. Check if clicking on resize handle of selected annotation
      const handleHit = hitTestAnnotationHandle(imgPt.x, imgPt.y);
      if (handleHit) {
        lyrView.resizingAnnIdx = handleHit.annIdx;
        lyrView.resizeHandleId = handleHit.handleId || handleHit.handleIdx;
        lyrView.dragStartImg = { ...imgPt };
        return;
      }

      // 2. Check if clicking on an annotation or label pill
      const annHitIdx = hitTestAnnotation(imgPt.x, imgPt.y);
      if (annHitIdx !== null) {
        const annotations = state.layerify.annotations || [];
        annotations.forEach((a, idx) => {
          a.selected = (idx === annHitIdx);
        });
        lyrView.draggingAnnIdx = annHitIdx;
        lyrView.dragStartImg = { ...imgPt };
        drawLayerifyCanvas();
        return;
      }

      // 3. Mode-specific creation
      if (lyrView.activeMode === "Rectangle") {
        lyrView.activeRectDraft = [imgPt.x, imgPt.y, imgPt.x, imgPt.y];
      } else if (lyrView.activeMode === "Polygon") {
        lyrView.activePolyDraft.push({ x: imgPt.x, y: imgPt.y });
        drawLayerifyCanvas();
      } else if (lyrView.activeMode === "Point") {
        addNewAnnotation({ points: [[imgPt.x, imgPt.y]] });
      } else if (lyrView.activeMode === "Brush") {
        lyrView.activeBrushStroke = [{ x: imgPt.x, y: imgPt.y }];
      } else if (lyrView.activeMode === "Idle") {
        // Deselect all
        (state.layerify.annotations || []).forEach(a => a.selected = false);
        drawLayerifyCanvas();
      }
    });

    lyrCanvas.addEventListener("pointermove", e => {
      const rect = lyrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const imgPt = screenToImage(sx, sy);
      lyrView.mouseImgX = imgPt.x;
      lyrView.mouseImgY = imgPt.y;
      lyrView.isMouseOver = true;

      const coordsEl = document.getElementById("layerify-coords-pill");
      if (coordsEl) {
        coordsEl.textContent = `X: ${Math.round(imgPt.x)}, Y: ${Math.round(imgPt.y)}`;
      }

      if (lyrView.isPanning) {
        lyrView.offsetX = lyrView.panStartOffX + (sx - lyrView.panStartX);
        lyrView.offsetY = lyrView.panStartOffY + (sy - lyrView.panStartY);
        drawLayerifyCanvas();
        return;
      }

      // Dragging annotation
      if (lyrView.draggingAnnIdx >= 0 && lyrView.dragStartImg) {
        const dx = imgPt.x - lyrView.dragStartImg.x;
        const dy = imgPt.y - lyrView.dragStartImg.y;
        const annotations = state.layerify.annotations || [];
        const ann = annotations[lyrView.draggingAnnIdx];
        if (ann) {
          const maxW = lyrView.imgW || 2000;
          const maxH = lyrView.imgH || 2000;
          utils.moveAnnotationByDelta(ann, dx, dy, maxW, maxH);
          lyrView.dragStartImg = { ...imgPt };
          drawLayerifyCanvas();
        }
        return;
      }

      // Drawing drafts
      if (lyrView.activeRectDraft) {
        lyrView.activeRectDraft[2] = imgPt.x;
        lyrView.activeRectDraft[3] = imgPt.y;
        drawLayerifyCanvas();
      } else if (lyrView.activeBrushStroke && lyrView.activeBrushStroke.length > 0) {
        lyrView.activeBrushStroke.push({ x: imgPt.x, y: imgPt.y });
        drawLayerifyCanvas();
      } else if (lyrView.activePolyDraft && lyrView.activePolyDraft.length > 0) {
        drawLayerifyCanvas();
      } else {
        // Hover test
        const prevHover = lyrView.hoverAnnIdx;
        lyrView.hoverAnnIdx = hitTestAnnotation(imgPt.x, imgPt.y);
        if (prevHover !== lyrView.hoverAnnIdx) {
          drawLayerifyCanvas();
        }
      }
    });

    const stopInteraction = async e => {
      try {
        lyrCanvas.releasePointerCapture(e.pointerId);
      } catch (_) {}

      if (lyrView.isPanning) {
        lyrView.isPanning = false;
        lyrCanvas.style.cursor = lyrView.activeMode === "Pan" ? CURSORS.PAN : CURSORS.IDLE;
        return;
      }

      // Finish dragging
      if (lyrView.draggingAnnIdx >= 0) {
        lyrView.draggingAnnIdx = -1;
        lyrView.dragStartImg = null;
        await syncAnnotationsToServer(true, "Moved annotation");
        return;
      }

      // Finish rectangle
      if (lyrView.activeRectDraft) {
        const [x1, y1, x2, y2] = lyrView.activeRectDraft;
        lyrView.activeRectDraft = null;
        const minX = Math.min(x1, x2);
        const minY = Math.min(y1, y2);
        const rw = Math.abs(x2 - x1);
        const rh = Math.abs(y2 - y1);
        if (rw >= 4 && rh >= 4) {
          await addNewAnnotation({ rectangle: [minX, minY, minX + rw, minY + rh] });
        } else {
          drawLayerifyCanvas();
        }
      }

      // Finish brush stroke
      if (lyrView.activeBrushStroke && lyrView.activeBrushStroke.length > 0) {
        const pts = [...lyrView.activeBrushStroke];
        lyrView.activeBrushStroke = [];
        if (pts.length >= 2) {
          await addNewAnnotation({ points: pts.map(p => [p.x, p.y]) });
        } else {
          drawLayerifyCanvas();
        }
      }
    };

    lyrCanvas.addEventListener("pointerup", stopInteraction);
    lyrCanvas.addEventListener("pointercancel", stopInteraction);

    lyrCanvas.addEventListener("wheel", e => {
      e.preventDefault();
      const rect = lyrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.15 : 0.87;

      const newZoom = Math.max(0.05, Math.min(40.0, lyrView.zoom * factor));
      lyrView.offsetX = sx - (sx - lyrView.offsetX) * (newZoom / lyrView.zoom);
      lyrView.offsetY = sy - (sy - lyrView.offsetY) * (newZoom / lyrView.zoom);
      lyrView.zoom = newZoom;
      drawLayerifyCanvas();
    });

    lyrCanvas.addEventListener("dblclick", () => {
      if (lyrView.activeMode === "Polygon" && lyrView.activePolyDraft.length >= 3) {
        finishPolygon();
      }
    });

    lyrCanvas.addEventListener("contextmenu", e => {
      e.preventDefault();
      if (lyrView.activeMode === "Polygon" && lyrView.activePolyDraft.length > 0) {
        lyrView.activePolyDraft.pop();
        drawLayerifyCanvas();
      } else {
        setLayerifyMode("Idle");
      }
    });
  }

  function bindHudEvents() {
    const brushInput = document.getElementById("input-lyr-brush-size");
    const brushVal = document.getElementById("val-lyr-brush-size");
    if (brushInput) {
      brushInput.addEventListener("input", () => {
        lyrView.brushSize = parseInt(brushInput.value, 10) || 18;
        if (brushVal) brushVal.textContent = `${lyrView.brushSize}px`;
      });
    }

    const finishBtn = document.getElementById("btn-finish-polygon");
    if (finishBtn) {
      finishBtn.addEventListener("click", finishPolygon);
    }
  }

  async function finishPolygon() {
    if (lyrView.activePolyDraft.length >= 3) {
      const poly = lyrView.activePolyDraft.map(p => [p.x, p.y]);
      lyrView.activePolyDraft = [];
      await addNewAnnotation({ polygon: poly });
    } else {
      lyrView.activePolyDraft = [];
      drawLayerifyCanvas();
    }
  }

  async function addNewAnnotation(data) {
    const annotations = state.layerify.annotations || [];
    const activeLabel = (state.layerify.current_label || "").trim() || "Undefined";
    const [r, g, b] = utils.hexToRgb(window.ImageBaker.getCurrentSelectedLabelColor());

    const nextId = annotations.length > 0 ? Math.max(...annotations.map(a => a.annotation_id || 0)) + 1 : 1;
    const newAnn = {
      annotation_id: nextId,
      name: `Annotation ${nextId}`,
      label: activeLabel,
      color: [r, g, b],
      color_hex: utils.rgbToHex(r, g, b),
      visible: true,
      selected: true,
      points: data.points || [],
      rectangle: data.rectangle || null,
      polygon: data.polygon || [],
      has_mask: false,
      mask_png_b64: data.mask_png_b64 || null,
      caption: "",
      score: null,
    };

    annotations.forEach(a => a.selected = false);
    annotations.push(newAnn);
    drawLayerifyCanvas();

    await syncAnnotationsToServer(true, "Created annotation");
  }

  async function syncAnnotationsToServer(pushUndo = true, message = "") {
    try {
      const res = await api.updateAnnotations(state.layerify.annotations, pushUndo, message);
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
      }
    } catch (err) {
      console.error("Failed to sync annotations:", err);
      showToast("layerify", "Sync failed: " + err.message);
    }
  }

  async function performLayerifyUndo() {
    try {
      const res = await api.performAnnotationAction("undo");
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
        showToast("layerify", "Undo");
      }
    } catch (err) {
      showToast("layerify", "Undo error: " + err.message);
    }
  }

  async function performLayerifyRedo() {
    try {
      const res = await api.performAnnotationAction("redo");
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
        showToast("layerify", "Redo");
      }
    } catch (err) {
      showToast("layerify", "Redo error: " + err.message);
    }
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.canvasLayerify = {
    initLayerifyCanvas,
    resizeLayerifyCanvas,
    fitLayerifyImageIfNeeded,
    syncLayerifyImage,
    preloadAnnotationMasks,
    drawLayerifyCanvas,
    setLayerifyMode,
    addNewAnnotation,
    syncAnnotationsToServer,
    performLayerifyUndo,
    performLayerifyRedo,
  };
})(window);
