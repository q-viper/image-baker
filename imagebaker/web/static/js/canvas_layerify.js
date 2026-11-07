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
    setLayerifyMode(lyrView.activeMode || "Rectangle");

    if (window.ResizeObserver && lyrCanvasWrap) {
      const ro = new ResizeObserver(() => {
        resizeLayerifyCanvas();
      });
      ro.observe(lyrCanvasWrap);
    }
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

  function isBrushAnnotation(ann) {
    if (!ann) return false;
    if (ann.type === "brush" || ann.type === "brushlabels") return true;
    const hasMask = Boolean(ann.has_mask || (ann.rle && ann.rle.length > 0) || ann.mask_png_b64);
    const hasPoly = Boolean(ann.polygon && ann.polygon.length >= 3);
    const hasRect = Boolean(ann.rectangle && ann.rectangle.length === 4);
    return hasMask && !hasPoly && !hasRect;
  }

  function getAnnotationMaskSignature(ann) {
    const col = (ann.color || [47, 128, 237]).join(",");
    if (ann.rle && ann.rle.length > 0) {
      const sz = (ann.mask_size || []).join("x");
      return `rle:${col}:${sz}:${ann.rle.length}:${ann.rle[0]}:${ann.rle[ann.rle.length - 1]}`;
    }
    if (ann.mask_png_b64) {
      return `b64:${col}:${ann.mask_png_b64.length}:${ann.mask_png_b64.slice(-32)}`;
    }
    return "";
  }

  function ensureMaskCanvasForAnnotation(ann) {
    if (!ann) return null;
    if (!lyrView.maskCanvasCache) lyrView.maskCanvasCache = new Map();
    if (!lyrView.maskBinaryCache) lyrView.maskBinaryCache = new Map();
    if (!lyrView.maskSigCache) lyrView.maskSigCache = new Map();

    const sig = getAnnotationMaskSignature(ann);
    const existingCanvas = lyrView.maskCanvasCache.get(ann.annotation_id);
    if (existingCanvas && lyrView.maskSigCache.get(ann.annotation_id) === sig) {
      return existingCanvas;
    }

    if (ann.rle && ann.rle.length > 0) {
      const h = (ann.mask_size && ann.mask_size.length === 2)
        ? ann.mask_size[0]
        : (lyrView.imgH || (lyrView.img ? lyrView.img.height : 600));
      const w = (ann.mask_size && ann.mask_size.length === 2)
        ? ann.mask_size[1]
        : (lyrView.imgW || (lyrView.img ? lyrView.img.width : 800));
      if (w > 0 && h > 0) {
        const mCanvas = existingCanvas || document.createElement("canvas");
        if (mCanvas.width !== w || mCanvas.height !== h) {
          mCanvas.width = w;
          mCanvas.height = h;
        }
        const mctx = mCanvas.getContext("2d");
        const imgData = utils.decodeRLEToImageData(ann.rle, w, h, ann.color || [47, 128, 237], 215);
        mctx.putImageData(imgData, 0, 0);
        const binGrid = utils.decodeRLEToBinary(ann.rle, w, h);
        lyrView.maskCanvasCache.set(ann.annotation_id, mCanvas);
        lyrView.maskBinaryCache.set(ann.annotation_id, { grid: binGrid, width: w, height: h });
        lyrView.maskSigCache.set(ann.annotation_id, sig);
        if (!ann.brush_bbox) {
          ann.brush_bbox = utils.computeMaskBBoxFromRLE(ann.rle, w, h);
        }
        return mCanvas;
      }
    }
    return existingCanvas || null;
  }

  function preloadAnnotationMasks(annotations) {
    if (!lyrView.maskCanvasCache) lyrView.maskCanvasCache = new Map();
    if (!lyrView.maskBinaryCache) lyrView.maskBinaryCache = new Map();
    if (!lyrView.maskSigCache) lyrView.maskSigCache = new Map();

    (annotations || []).forEach(ann => {
      if (ann.rle && ann.rle.length > 0) {
        ensureMaskCanvasForAnnotation(ann);
        return;
      }
      if (ann.mask_png_b64) {
        const sig = getAnnotationMaskSignature(ann);
        if (lyrView.maskSigCache.get(ann.annotation_id) !== sig || !lyrView.maskImageCache.has(ann.annotation_id)) {
          const mImg = new Image();
          mImg.onload = () => {
            const w = mImg.width;
            const h = mImg.height;
            if (w > 0 && h > 0) {
              const mCanvas = document.createElement("canvas");
              mCanvas.width = w;
              mCanvas.height = h;
              const mctx = mCanvas.getContext("2d");
              mctx.drawImage(mImg, 0, 0);
              const imgData = mctx.getImageData(0, 0, w, h);
              const rle = utils.encodeMaskToRLE(imgData.data, w, h, 4, 3);
              ann.rle = rle;
              ann.mask_size = [h, w];
              if (!ann.brush_bbox) {
                ann.brush_bbox = utils.computeMaskBBoxFromRLE(rle, w, h);
              }
              const tinted = utils.decodeRLEToImageData(rle, w, h, ann.color || [47, 128, 237], 215);
              mctx.putImageData(tinted, 0, 0);
              lyrView.maskCanvasCache.set(ann.annotation_id, mCanvas);
              lyrView.maskBinaryCache.set(ann.annotation_id, {
                grid: utils.decodeRLEToBinary(rle, w, h),
                width: w,
                height: h,
              });
              lyrView.maskSigCache.set(ann.annotation_id, getAnnotationMaskSignature(ann));
            }
            drawLayerifyCanvas();
          };
          mImg.src = "data:image/png;base64," + ann.mask_png_b64;
          lyrView.maskImageCache.set(ann.annotation_id, mImg);
          lyrView.maskSigCache.set(ann.annotation_id, sig);
        }
      }
    });
  }

  function hitTestLabelPill(ix, iy) {
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
    return null;
  }

  function hitTestAnnotation(ix, iy) {
    const tol = 7 / lyrView.zoom;
    const pillHit = hitTestLabelPill(ix, iy);
    if (pillHit !== null) return pillHit;

    const annotations = state.layerify.annotations || [];
    for (let i = annotations.length - 1; i >= 0; i--) {
      const ann = annotations[i];
      if (ann.visible === false) continue;
      if (!isBrushAnnotation(ann) && ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        for (const pt of ann.points) {
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol * 1.3) return i;
        }
      }
    }

    const hits = [];
    for (let i = annotations.length - 1; i >= 0; i--) {
      const ann = annotations[i];
      if (ann.visible === false) continue;

      if (isBrushAnnotation(ann) || ann.has_mask) {
        ensureMaskCanvasForAnnotation(ann);
        const mx = Math.round(ix - (ann.mask_offset_x || 0));
        const my = Math.round(iy - (ann.mask_offset_y || 0));
        const binEntry = lyrView.maskBinaryCache ? lyrView.maskBinaryCache.get(ann.annotation_id) : null;
        const bbox = ann.brush_bbox;
        const rad = Math.min(8, Math.max(1, Math.ceil(5 / lyrView.zoom)));
        let maskHit = false;

        if (binEntry && binEntry.grid && binEntry.width > 0 && binEntry.height > 0) {
          if (
            !bbox ||
            (mx >= bbox[0] - rad && mx <= bbox[2] + rad && my >= bbox[1] - rad && my <= bbox[3] + rad)
          ) {
            const w = binEntry.width;
            const h = binEntry.height;
            for (let dy = -rad; dy <= rad && !maskHit; dy += Math.max(1, Math.floor(rad / 2))) {
              const py = my + dy;
              if (py < 0 || py >= h) continue;
              for (let dx = -rad; dx <= rad; dx += Math.max(1, Math.floor(rad / 2))) {
                const px = mx + dx;
                if (px < 0 || px >= w) continue;
                if (binEntry.grid[py * w + px] > 0) {
                  maskHit = true;
                  break;
                }
              }
            }
            if (!maskHit && mx >= 0 && mx < w && my >= 0 && my < h && binEntry.grid[my * w + mx] > 0) {
              maskHit = true;
            }
          }
        } else if (bbox && bbox.length === 4) {
          if (mx >= bbox[0] - tol && mx <= bbox[2] + tol && my >= bbox[1] - tol && my <= bbox[3] + tol) {
            maskHit = true;
          }
        }

        if (maskHit) {
          const area = (bbox && bbox.length === 4)
            ? Math.max(1, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            : 1000;
          hits.push({ idx: i, area });
          if (isBrushAnnotation(ann)) continue;
        }
      }

      if (ann.polygon && ann.polygon.length >= 3) {
        let onVert = false;
        for (const pt of ann.polygon) {
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol) {
            onVert = true;
            break;
          }
        }
        let onEdge = false;
        if (!onVert) {
          for (let e = 0; e < ann.polygon.length; e++) {
            const p1 = ann.polygon[e];
            const p2 = ann.polygon[(e + 1) % ann.polygon.length];
            if (utils.distToSegment(ix, iy, p1[0], p1[1], p2[0], p2[1]) <= tol) {
              onEdge = true;
              break;
            }
          }
        }
        if (onVert || onEdge || utils.pointInPolygon(ix, iy, ann.polygon)) {
          const xs = ann.polygon.map(p => p[0]);
          const ys = ann.polygon.map(p => p[1]);
          const area = Math.max(1, (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys)));
          hits.push({ idx: i, area });
          continue;
        }
      }
      if ((!ann.polygon || ann.polygon.length < 3) && ann.rectangle && ann.rectangle.length === 4) {
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
    const tol = 9.0 / lyrView.zoom;
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
      if (isBrushAnnotation(ann)) continue;
      if (ann.polygon && ann.polygon.length >= 3) {
        for (let v = 0; v < ann.polygon.length; v++) {
          const pt = ann.polygon[v];
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol) {
            return { annIdx: i, type: "poly", handleIdx: v };
          }
        }
      }
      if ((!ann.polygon || ann.polygon.length < 3) && ann.rectangle && ann.rectangle.length === 4) {
        const handles = utils.getRectHandles(ann.rectangle);
        for (let h = 0; h < handles.length; h++) {
          if (Math.hypot(ix - handles[h].x, iy - handles[h].y) <= tol) {
            return { annIdx: i, type: "rect", handleIdx: h, handleId: handles[h].id };
          }
        }
      }
      if (ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        for (let p = 0; p < ann.points.length; p++) {
          const pt = ann.points[p];
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol * 1.2) {
            return { annIdx: i, type: "point", handleIdx: p };
          }
        }
      }
    }
    return null;
  }

  function hitTestPolygonEdge(ix, iy) {
    const tol = 9.0 / lyrView.zoom;
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
      if (!ann.polygon || ann.polygon.length < 3) continue;

      let bestEdgeIdx = -1;
      let bestPoint = null;
      let bestDist = Infinity;

      for (let e = 0; e < ann.polygon.length; e++) {
        const p1 = ann.polygon[e];
        const p2 = ann.polygon[(e + 1) % ann.polygon.length];
        const proj = utils.projectPointToSegment(ix, iy, p1[0], p1[1], p2[0], p2[1]);
        if (proj.dist <= tol && proj.dist < bestDist) {
          bestDist = proj.dist;
          bestEdgeIdx = e;
          bestPoint = [proj.x, proj.y];
        }
      }

      if (bestEdgeIdx >= 0 && bestPoint) {
        return {
          annIdx: i,
          edgeIdx: bestEdgeIdx,
          point: bestPoint,
          dist: bestDist,
        };
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
      if (ann.has_mask || (ann.rle && ann.rle.length > 0) || ann.mask_png_b64) {
        const mCanvas = ensureMaskCanvasForAnnotation(ann);
        const mImg = mCanvas || lyrView.maskImageCache.get(ann.annotation_id);
        if (mImg && (mCanvas || mImg.complete)) {
          ctx.save();
          ctx.globalAlpha = isSel ? 0.65 : (isHov ? 0.52 : 0.40);
          const maskX = lyrView.offsetX + (ann.mask_offset_x || 0) * lyrView.zoom;
          const maskY = lyrView.offsetY + (ann.mask_offset_y || 0) * lyrView.zoom;
          ctx.drawImage(mImg, maskX, maskY, mImg.width * lyrView.zoom, mImg.height * lyrView.zoom);
          ctx.restore();
        }
        if (isBrushAnnotation(ann) && (isSel || isHov) && ann.brush_bbox && ann.brush_bbox.length === 4) {
          const offX = ann.mask_offset_x || 0;
          const offY = ann.mask_offset_y || 0;
          const b1 = imageToScreen(ann.brush_bbox[0] + offX, ann.brush_bbox[1] + offY);
          const b2 = imageToScreen(ann.brush_bbox[2] + offX, ann.brush_bbox[3] + offY);
          ctx.save();
          ctx.strokeStyle = strokeCol;
          ctx.lineWidth = isSel ? 2.0 : 1.5;
          ctx.setLineDash([5, 4]);
          ctx.strokeRect(b1.x, b1.y, b2.x - b1.x, b2.y - b1.y);
          ctx.restore();
        }
      }

      // Draw Rectangle (only if not a polygon or brush annotation)
      if (!isBrushAnnotation(ann) && (!ann.polygon || ann.polygon.length < 3) && ann.rectangle && ann.rectangle.length === 4) {
        const [x1, y1, x2, y2] = ann.rectangle;
        const s1 = imageToScreen(Math.min(x1, x2), Math.min(y1, y2));
        const s2 = imageToScreen(Math.max(x1, x2), Math.max(y1, y2));
        const rw = s2.x - s1.x;
        const rh = s2.y - s1.y;

        ctx.fillRect(s1.x, s1.y, rw, rh);
        ctx.strokeRect(s1.x, s1.y, rw, rh);

        // Resize handles when selected or hovered
        if (isSel || isHov) {
          const handleRadius = isSel ? 4.5 : 4.0;
          const handles = utils.getRectHandles(ann.rectangle);
          handles.forEach(hnd => {
            const sh = imageToScreen(hnd.x, hnd.y);
            ctx.fillStyle = "#ffffff";
            ctx.strokeStyle = strokeCol;
            ctx.lineWidth = isSel ? 1.8 : 1.5;
            ctx.beginPath();
            ctx.arc(sh.x, sh.y, handleRadius, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          });
        }
      }

      // Draw Polygon
      if (!isBrushAnnotation(ann) && ann.polygon && ann.polygon.length >= 3) {
        ctx.beginPath();
        ann.polygon.forEach((pt, pidx) => {
          const sp = imageToScreen(pt[0], pt[1]);
          if (pidx === 0) ctx.moveTo(sp.x, sp.y);
          else ctx.lineTo(sp.x, sp.y);
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Polygon vertex handles only when selected or hovered
        if (isSel || isHov) {
          const vertexRadius = isSel ? 4.5 : 4.0;
          ann.polygon.forEach(pt => {
            const sp = imageToScreen(pt[0], pt[1]);
            ctx.fillStyle = "#ffffff";
            ctx.strokeStyle = strokeCol;
            ctx.lineWidth = isSel ? 1.8 : 1.5;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, vertexRadius, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          });
        }
      }

      // Draw Keypoints (only for Point annotations)
      if (!isBrushAnnotation(ann) && ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        ann.points.forEach(pt => {
          const sp = imageToScreen(pt[0], pt[1]);
          ctx.fillStyle = strokeCol;
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(sp.x, sp.y, isSel ? 6.5 : (isHov ? 6.0 : 5), 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();

          if (isSel || isHov) {
            ctx.fillStyle = "#ffffff";
            ctx.strokeStyle = strokeCol;
            ctx.lineWidth = isSel ? 1.8 : 1.5;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, isSel ? 3.5 : 3.0, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          }
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

    // 6. Draw Active Brush Stroke & Brush Preview Ring
    if (lyrView.activeBrushStroke && lyrView.activeBrushStroke.length > 0) {
      const isErasing = Boolean(lyrView.activeBrushErase);
      const selBrush = (state.layerify.annotations || []).find(a => a.selected && isBrushAnnotation(a));
      const strokeHex = isErasing
        ? "#f2994a"
        : (selBrush && selBrush.color_hex ? selBrush.color_hex : window.ImageBaker.getCurrentSelectedLabelColor());
      ctx.save();
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.lineWidth = Math.max(2, (lyrView.brushSize || 18) * lyrView.zoom);
      ctx.strokeStyle = strokeHex;
      ctx.fillStyle = strokeHex;
      ctx.globalAlpha = isErasing ? 0.45 : 0.55;
      if (lyrView.activeBrushStroke.length === 1) {
        const sp = imageToScreen(lyrView.activeBrushStroke[0].x, lyrView.activeBrushStroke[0].y);
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, Math.max(1, ((lyrView.brushSize || 18) * lyrView.zoom) / 2), 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.beginPath();
        lyrView.activeBrushStroke.forEach((pt, idx) => {
          const sp = imageToScreen(pt.x, pt.y);
          if (idx === 0) ctx.moveTo(sp.x, sp.y);
          else ctx.lineTo(sp.x, sp.y);
        });
        ctx.stroke();
      }
      ctx.restore();
    }

    if (lyrView.activeMode === "Brush" && lyrView.isMouseOver && lyrView.brushSubMode !== "move") {
      const sp = imageToScreen(lyrView.mouseImgX, lyrView.mouseImgY);
      const radius = Math.max(2, ((lyrView.brushSize || 18) * lyrView.zoom) / 2);
      const isEraseRing = lyrView.brushSubMode === "erase";
      ctx.save();
      ctx.beginPath();
      ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2.5;
      ctx.stroke();
      ctx.strokeStyle = isEraseRing
        ? "#f2994a"
        : (window.ImageBaker.getCurrentSelectedLabelColor() || "#a855f7");
      ctx.lineWidth = 1.5;
      if (isEraseRing) ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.restore();
    }

    ctx.restore();
  }

  let drawLayerifyPending = false;
  function requestDrawLayerify() {
    if (drawLayerifyPending) return;
    drawLayerifyPending = true;
    requestAnimationFrame(() => {
      drawLayerifyPending = false;
      drawLayerifyCanvas();
    });
  }

  function getCursorForMode(mode) {
    switch (mode) {
      case "Pan": return CURSORS.PAN;
      case "Rectangle": return CURSORS.RECTANGLE;
      case "Point": return CURSORS.POINT;
      case "Polygon": return CURSORS.POLYGON;
      case "Brush": return CURSORS.BRUSH;
      default: return CURSORS.IDLE;
    }
  }

  function getRectResizeCursor(handleId) {
    switch (handleId) {
      case "nw":
      case "se":
        return "nwse-resize";
      case "ne":
      case "sw":
        return "nesw-resize";
      case "n":
      case "s":
        return "ns-resize";
      case "e":
      case "w":
        return "ew-resize";
      default:
        return "nwse-resize";
    }
  }

  function updateLayerifyCursor(e, imgPt) {
    if (!lyrCanvas) return;
    if (lyrView.isPanning) {
      lyrCanvas.style.cursor = CURSORS.PAN_ACTIVE;
      return;
    }
    if (lyrView.resizingAnnIdx >= 0) {
      lyrCanvas.style.cursor = lyrView.resizeHandleType === "rect"
        ? getRectResizeCursor(lyrView.resizeHandleId)
        : "grabbing";
      return;
    }
    if (lyrView.draggingAnnIdx >= 0) {
      lyrCanvas.style.cursor = CURSORS.MOVE || "move";
      return;
    }
    if (lyrView.activeMode === "Pan") {
      lyrCanvas.style.cursor = CURSORS.PAN;
      return;
    }
    if (lyrView.activeMode === "Polygon" && lyrView.activePolyDraft && lyrView.activePolyDraft.length > 0) {
      if (lyrView.activePolyDraft.length >= 3 && imgPt) {
        const firstPt = lyrView.activePolyDraft[0];
        if (Math.hypot(imgPt.x - firstPt.x, imgPt.y - firstPt.y) <= 10.0 / lyrView.zoom) {
          lyrCanvas.style.cursor = "pointer";
          return;
        }
      }
      lyrCanvas.style.cursor = CURSORS.POLYGON;
      return;
    }
    if (lyrView.activeRectDraft) {
      lyrCanvas.style.cursor = CURSORS.RECTANGLE;
      return;
    }
    if (lyrView.activeBrushStroke && lyrView.activeBrushStroke.length > 0) {
      lyrCanvas.style.cursor = lyrView.activeBrushErase ? (CURSORS.ERASE || CURSORS.BRUSH) : CURSORS.BRUSH;
      return;
    }

    const multi = Boolean(e && (e.ctrlKey || e.metaKey || e.shiftKey));
    if (imgPt && !multi && lyrView.activeMode !== "Brush") {
      const handleHit = hitTestAnnotationHandle(imgPt.x, imgPt.y);
      if (handleHit) {
        lyrCanvas.style.cursor = handleHit.type === "rect"
          ? getRectResizeCursor(handleHit.handleId)
          : "pointer";
        return;
      }
    }

    if (lyrView.hoverAnnIdx !== null && lyrView.hoverAnnIdx !== undefined) {
      if (multi) {
        lyrCanvas.style.cursor = "pointer";
        return;
      }
      if (lyrView.activeMode === "Idle" || (lyrView.activeMode === "Brush" && lyrView.brushSubMode === "move")) {
        lyrCanvas.style.cursor = CURSORS.MOVE || "move";
        return;
      }
      if (imgPt && hitTestLabelPill(imgPt.x, imgPt.y) !== null) {
        lyrCanvas.style.cursor = CURSORS.MOVE || "move";
        return;
      }
    }

    if (lyrView.activeMode === "Brush") {
      if (lyrView.brushSubMode === "erase" || (e && e.altKey)) {
        lyrCanvas.style.cursor = CURSORS.ERASE || CURSORS.BRUSH;
        return;
      }
      if (lyrView.brushSubMode === "move") {
        lyrCanvas.style.cursor = CURSORS.MOVE || "move";
        return;
      }
    }

    if (e && (e.ctrlKey || e.metaKey || e.spaceKey)) {
      lyrCanvas.style.cursor = CURSORS.PAN;
      return;
    }

    lyrCanvas.style.cursor = getCursorForMode(lyrView.activeMode);
  }

  function setBrushSubMode(subMode) {
    lyrView.brushSubMode = subMode || "paint";
    const paintBtn = document.getElementById("btn-lyr-brush-paint");
    const eraseBtn = document.getElementById("btn-lyr-brush-erase");
    const moveBtn = document.getElementById("btn-lyr-brush-move");
    if (paintBtn) paintBtn.classList.toggle("active", lyrView.brushSubMode === "paint");
    if (eraseBtn) eraseBtn.classList.toggle("active", lyrView.brushSubMode === "erase");
    if (moveBtn) moveBtn.classList.toggle("active", lyrView.brushSubMode === "move");
    if (lyrCanvas && lyrView.activeMode === "Brush") {
      lyrCanvas.style.cursor = getCursorForMode("Brush");
      drawLayerifyCanvas();
    }
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
        case "Polygon": hint.textContent = "Click to place vertices • Double-click vertex to remove or edge to add point"; break;
        case "Point": hint.textContent = "Click to place keypoint markers"; break;
        case "Brush": hint.textContent = "Drag to paint/erase mask • Use Paint/Erase/Move or Alt+drag to erase"; break;
        case "Pan": hint.textContent = "Drag to pan viewport • Mouse wheel to zoom"; break;
        default: hint.textContent = "Click any region or label pill to select and move"; break;
      }
    }

    if (lyrCanvas) {
      lyrCanvas.style.cursor = getCursorForMode(mode);
    }
    drawLayerifyCanvas();
  }

  function commitMovedBrushMasks() {
    const annotations = state.layerify.annotations || [];
    annotations.forEach(ann => {
      const dx = Math.round(ann.mask_offset_x || 0);
      const dy = Math.round(ann.mask_offset_y || 0);
      if (dx === 0 && dy === 0) return;

      const mCanvas = ensureMaskCanvasForAnnotation(ann);
      if (mCanvas && mCanvas.width > 0 && mCanvas.height > 0) {
        const w = mCanvas.width;
        const h = mCanvas.height;
        const tmp = document.createElement("canvas");
        tmp.width = w;
        tmp.height = h;
        tmp.getContext("2d").drawImage(mCanvas, dx, dy);

        const mctx = mCanvas.getContext("2d");
        mctx.clearRect(0, 0, w, h);
        mctx.drawImage(tmp, 0, 0);

        const imgData = mctx.getImageData(0, 0, w, h);
        const rle = utils.encodeMaskToRLE(imgData.data, w, h, 4, 3);
        ann.rle = rle;
        ann.mask_size = [h, w];
        ann.format = "rle";
        ann.brush_bbox = utils.computeMaskBBoxFromRLE(rle, w, h);
        ann.mask_png_b64 = mCanvas.toDataURL("image/png").split(",")[1];
        ann.mask_offset_x = 0;
        ann.mask_offset_y = 0;
        lyrView.maskBinaryCache.set(ann.annotation_id, {
          grid: utils.decodeRLEToBinary(rle, w, h),
          width: w,
          height: h,
        });
        lyrView.maskSigCache.set(ann.annotation_id, getAnnotationMaskSignature(ann));
      }
    });
  }

  async function applyBrushStrokeToMask(pts, isErase) {
    if (!pts || pts.length === 0) return;
    const annotations = state.layerify.annotations || [];
    const imgW = lyrView.imgW || (lyrView.img ? lyrView.img.width : 800);
    const imgH = lyrView.imgH || (lyrView.img ? lyrView.img.height : 600);
    if (imgW <= 0 || imgH <= 0) return;

    // Find target brush annotation: either a currently selected brush annotation,
    // or (when erasing) the brush annotation under the start of the stroke.
    let targetAnn = annotations.find(a => a.selected && a.visible !== false && (isBrushAnnotation(a) || a.has_mask));
    if (!targetAnn && isErase) {
      const hitIdx = hitTestAnnotation(pts[0].x, pts[0].y);
      if (hitIdx !== null && annotations[hitIdx] && (isBrushAnnotation(annotations[hitIdx]) || annotations[hitIdx].has_mask)) {
        targetAnn = annotations[hitIdx];
        annotations.forEach((a, i) => {
          a.selected = (i === hitIdx);
        });
      }
    }

    if (isErase && !targetAnn) {
      showToast("layerify", "Select or click on a brush mask to erase");
      drawLayerifyCanvas();
      return;
    }

    const strokeWidth = Math.max(1, lyrView.brushSize || 18);

    if (targetAnn) {
      commitMovedBrushMasks();
      let mCanvas = ensureMaskCanvasForAnnotation(targetAnn);
      if (!mCanvas) {
        mCanvas = document.createElement("canvas");
        mCanvas.width = imgW;
        mCanvas.height = imgH;
        lyrView.maskCanvasCache.set(targetAnn.annotation_id, mCanvas);
      }
      const w = mCanvas.width;
      const h = mCanvas.height;
      const mctx = mCanvas.getContext("2d");

      mctx.save();
      mctx.lineCap = "round";
      mctx.lineJoin = "round";
      mctx.lineWidth = strokeWidth;
      if (isErase) {
        mctx.globalCompositeOperation = "destination-out";
        mctx.strokeStyle = "rgba(0,0,0,1)";
        mctx.fillStyle = "rgba(0,0,0,1)";
      } else {
        mctx.globalCompositeOperation = "source-over";
        const [r, g, b] = targetAnn.color || [47, 128, 237];
        mctx.strokeStyle = `rgba(${r},${g},${b},1)`;
        mctx.fillStyle = `rgba(${r},${g},${b},1)`;
      }
      if (pts.length === 1) {
        mctx.beginPath();
        mctx.arc(pts[0].x, pts[0].y, strokeWidth / 2, 0, Math.PI * 2);
        mctx.fill();
      } else {
        mctx.beginPath();
        mctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) {
          mctx.lineTo(pts[i].x, pts[i].y);
        }
        mctx.stroke();
      }
      mctx.restore();

      const rawImgData = mctx.getImageData(0, 0, w, h);
      const rle = utils.encodeMaskToRLE(rawImgData.data, w, h, 4, 3);
      const bbox = utils.computeMaskBBoxFromRLE(rle, w, h);

      if (!bbox || rle.length <= 1) {
        // Entire brush mask was erased
        const idx = annotations.indexOf(targetAnn);
        if (idx >= 0) annotations.splice(idx, 1);
        lyrView.maskCanvasCache.delete(targetAnn.annotation_id);
        lyrView.maskBinaryCache.delete(targetAnn.annotation_id);
        lyrView.maskSigCache.delete(targetAnn.annotation_id);
        drawLayerifyCanvas();
        window.ImageBaker.uiLayerify.renderAnnotationList();
        await syncAnnotationsToServer(true, "Erased brush annotation");
        return;
      }

      // Normalize alpha to 215 across all painted pixels
      const normImgData = utils.decodeRLEToImageData(rle, w, h, targetAnn.color || [47, 128, 237], 215);
      mctx.putImageData(normImgData, 0, 0);

      targetAnn.type = "brush";
      targetAnn.format = "rle";
      targetAnn.brushlabels = [targetAnn.label || "Undefined"];
      targetAnn.has_mask = true;
      targetAnn.rle = rle;
      targetAnn.mask_size = [h, w];
      targetAnn.brush_bbox = bbox;
      targetAnn.points = [];
      targetAnn.polygon = [];
      targetAnn.rectangle = null;
      targetAnn.mask_offset_x = 0;
      targetAnn.mask_offset_y = 0;
      targetAnn.mask_png_b64 = mCanvas.toDataURL("image/png").split(",")[1];

      lyrView.maskBinaryCache.set(targetAnn.annotation_id, {
        grid: utils.decodeRLEToBinary(rle, w, h),
        width: w,
        height: h,
      });
      lyrView.maskSigCache.set(targetAnn.annotation_id, getAnnotationMaskSignature(targetAnn));

      drawLayerifyCanvas();
      window.ImageBaker.uiLayerify.renderAnnotationList();
      await syncAnnotationsToServer(true, isErase ? "Erased from brush mask" : "Updated brush mask");
      return;
    }

    // Create a new brush annotation
    const activeLabel = (state.layerify.current_label || "").trim() || "Undefined";
    const [r, g, b] = utils.hexToRgb(window.ImageBaker.getCurrentSelectedLabelColor());
    const nextId = annotations.length > 0 ? Math.max(...annotations.map(a => a.annotation_id || 0)) + 1 : 1;

    const mCanvas = document.createElement("canvas");
    mCanvas.width = imgW;
    mCanvas.height = imgH;
    const mctx = mCanvas.getContext("2d");
    mctx.save();
    mctx.lineCap = "round";
    mctx.lineJoin = "round";
    mctx.lineWidth = strokeWidth;
    mctx.strokeStyle = `rgba(${r},${g},${b},1)`;
    mctx.fillStyle = `rgba(${r},${g},${b},1)`;
    if (pts.length === 1) {
      mctx.beginPath();
      mctx.arc(pts[0].x, pts[0].y, strokeWidth / 2, 0, Math.PI * 2);
      mctx.fill();
    } else {
      mctx.beginPath();
      mctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) {
        mctx.lineTo(pts[i].x, pts[i].y);
      }
      mctx.stroke();
    }
    mctx.restore();

    const rawImgData = mctx.getImageData(0, 0, imgW, imgH);
    const rle = utils.encodeMaskToRLE(rawImgData.data, imgW, imgH, 4, 3);
    const bbox = utils.computeMaskBBoxFromRLE(rle, imgW, imgH);
    if (!bbox) {
      drawLayerifyCanvas();
      return;
    }

    const normImgData = utils.decodeRLEToImageData(rle, imgW, imgH, [r, g, b], 215);
    mctx.putImageData(normImgData, 0, 0);

    const newAnn = {
      annotation_id: nextId,
      name: `Annotation ${nextId}`,
      type: "brush",
      format: "rle",
      brushlabels: [activeLabel],
      label: activeLabel,
      color: [r, g, b],
      color_hex: utils.rgbToHex(r, g, b),
      visible: true,
      selected: true,
      points: [],
      rectangle: null,
      polygon: [],
      has_mask: true,
      rle: rle,
      mask_size: [imgH, imgW],
      brush_bbox: bbox,
      mask_png_b64: mCanvas.toDataURL("image/png").split(",")[1],
      caption: "",
      score: null,
    };

    if (!lyrView.maskCanvasCache) lyrView.maskCanvasCache = new Map();
    if (!lyrView.maskBinaryCache) lyrView.maskBinaryCache = new Map();
    if (!lyrView.maskSigCache) lyrView.maskSigCache = new Map();
    lyrView.maskCanvasCache.set(nextId, mCanvas);
    lyrView.maskBinaryCache.set(nextId, {
      grid: utils.decodeRLEToBinary(rle, imgW, imgH),
      width: imgW,
      height: imgH,
    });
    lyrView.maskSigCache.set(nextId, getAnnotationMaskSignature(newAnn));

    annotations.forEach(a => a.selected = false);
    annotations.push(newAnn);
    drawLayerifyCanvas();
    window.ImageBaker.uiLayerify.renderAnnotationList();
    await syncAnnotationsToServer(true, "Created brush annotation");
  }

  function bindCanvasEvents() {
    if (!lyrCanvas) return;

    lyrCanvas.addEventListener("pointerdown", e => {
      lyrCanvas.setPointerCapture(e.pointerId);
      const rect = lyrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const imgPt = screenToImage(sx, sy);

      const isImmediatePan = e.button === 1 || lyrView.activeMode === "Pan" || (e.button === 0 && e.spaceKey);
      if (isImmediatePan) {
        lyrView.isPanning = true;
        lyrView.panStartX = sx;
        lyrView.panStartY = sy;
        lyrView.panStartOffX = lyrView.offsetX;
        lyrView.panStartOffY = lyrView.offsetY;
        lyrCanvas.style.cursor = CURSORS.PAN_ACTIVE;
        return;
      }

      if (e.button !== 0) return;

      // 0. If actively drawing a polygon draft, continue the draft without selecting existing annotations
      if (lyrView.activeMode === "Polygon" && lyrView.activePolyDraft.length > 0) {
        if (lyrView.activePolyDraft.length >= 3) {
          const firstPt = lyrView.activePolyDraft[0];
          if (Math.hypot(imgPt.x - firstPt.x, imgPt.y - firstPt.y) <= 10.0 / lyrView.zoom) {
            finishPolygon();
            return;
          }
        }
        const lastPt = lyrView.activePolyDraft[lyrView.activePolyDraft.length - 1];
        if (!lastPt || Math.hypot(imgPt.x - lastPt.x, imgPt.y - lastPt.y) > 2.0 / lyrView.zoom) {
          lyrView.activePolyDraft.push({ x: imgPt.x, y: imgPt.y });
        }
        drawLayerifyCanvas();
        return;
      }

      const multi = e.ctrlKey || e.metaKey || e.shiftKey;
      const pillHitIdx = hitTestLabelPill(imgPt.x, imgPt.y);

      // In Brush Paint/Erase mode (without Ctrl/Shift and not clicking a label pill), prioritize brushing/erasing!
      if (lyrView.activeMode === "Brush" && lyrView.brushSubMode !== "move" && !multi && pillHitIdx === null) {
        lyrView.activeBrushErase = Boolean(lyrView.brushSubMode === "erase" || e.altKey);
        lyrView.activeBrushStroke = [{ x: imgPt.x, y: imgPt.y }];
        drawLayerifyCanvas();
        return;
      }

      // 1. Check if clicking on resize/vertex handle of an annotation (when not Ctrl/Shift multi-selecting)
      const handleHit = !multi ? hitTestAnnotationHandle(imgPt.x, imgPt.y) : null;
      if (handleHit) {
        const annotations = state.layerify.annotations || [];
        annotations.forEach((a, idx) => {
          a.selected = (idx === handleHit.annIdx);
        });
        lyrView.resizingAnnIdx = handleHit.annIdx;
        lyrView.resizeHandleType = handleHit.type;
        lyrView.resizeHandleId = handleHit.handleId !== undefined ? handleHit.handleId : handleHit.handleIdx;
        lyrView.dragStartImg = { ...imgPt };
        lyrView.hasMovedDuringDrag = false;
        drawLayerifyCanvas();
        window.ImageBaker.uiLayerify.renderAnnotationList();
        return;
      }

      // 2. Check if clicking on an annotation or label pill
      const annHitIdx = pillHitIdx !== null ? pillHitIdx : hitTestAnnotation(imgPt.x, imgPt.y);
      if (annHitIdx !== null) {
        const annotations = state.layerify.annotations || [];
        if (multi) {
          annotations[annHitIdx].selected = !annotations[annHitIdx].selected;
          if (annotations[annHitIdx].selected) {
            lyrView.draggingAnnIdx = annHitIdx;
            lyrView.dragStartImg = { ...imgPt };
            lyrView.hasMovedDuringDrag = false;
          } else {
            lyrView.draggingAnnIdx = -1;
            lyrView.dragStartImg = null;
            lyrView.hasMovedDuringDrag = false;
            syncAnnotationsToServer(false, "Toggled annotation selection");
          }
        } else {
          // If clicking an already-selected annotation when multiple are selected, keep the multi-selection so they move together
          if (!annotations[annHitIdx].selected) {
            annotations.forEach((a, idx) => {
              a.selected = (idx === annHitIdx);
            });
          }
          lyrView.draggingAnnIdx = annHitIdx;
          lyrView.dragStartImg = { ...imgPt };
          lyrView.hasMovedDuringDrag = false;
        }
        drawLayerifyCanvas();
        window.ImageBaker.uiLayerify.renderAnnotationList();
        return;
      }

      // 2b. Ctrl/Cmd + drag on empty space pans the canvas
      if (e.ctrlKey || e.metaKey) {
        lyrView.isPanning = true;
        lyrView.panStartX = sx;
        lyrView.panStartY = sy;
        lyrView.panStartOffX = lyrView.offsetX;
        lyrView.panStartOffY = lyrView.offsetY;
        lyrCanvas.style.cursor = CURSORS.PAN_ACTIVE;
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
        if (lyrView.brushSubMode === "move") {
          (state.layerify.annotations || []).forEach(a => a.selected = false);
          drawLayerifyCanvas();
          window.ImageBaker.uiLayerify.renderAnnotationList();
          syncAnnotationsToServer(false, "Deselected all annotations");
        } else {
          lyrView.activeBrushErase = Boolean(lyrView.brushSubMode === "erase" || e.altKey);
          lyrView.activeBrushStroke = [{ x: imgPt.x, y: imgPt.y }];
          drawLayerifyCanvas();
        }
      } else if (lyrView.activeMode === "Idle") {
        // Deselect all
        (state.layerify.annotations || []).forEach(a => a.selected = false);
        drawLayerifyCanvas();
        window.ImageBaker.uiLayerify.renderAnnotationList();
        syncAnnotationsToServer(false, "Deselected all annotations");
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
        requestDrawLayerify();
        return;
      }

      // Dragging vertex or resize handle
      if (lyrView.resizingAnnIdx >= 0 && lyrView.dragStartImg) {
        const dx = imgPt.x - lyrView.dragStartImg.x;
        const dy = imgPt.y - lyrView.dragStartImg.y;
        if (Math.hypot(dx, dy) > 0.5) {
          lyrView.hasMovedDuringDrag = true;
        }
        const annotations = state.layerify.annotations || [];
        const ann = annotations[lyrView.resizingAnnIdx];
        if (ann) {
          if (lyrView.resizeHandleType === "poly" && ann.polygon && ann.polygon[lyrView.resizeHandleId]) {
            ann.polygon[lyrView.resizeHandleId] = [imgPt.x, imgPt.y];
            if (ann.rectangle && ann.polygon.length >= 3) {
              const xs = ann.polygon.map(p => p[0]);
              const ys = ann.polygon.map(p => p[1]);
              ann.rectangle = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
            }
          } else if (lyrView.resizeHandleType === "point" && ann.points && ann.points[lyrView.resizeHandleId]) {
            ann.points[lyrView.resizeHandleId] = [imgPt.x, imgPt.y];
          } else if (lyrView.resizeHandleType === "rect" && ann.rectangle && ann.rectangle.length === 4) {
            const [rx1, ry1, rx2, ry2] = ann.rectangle;
            let x1 = Math.min(rx1, rx2);
            let y1 = Math.min(ry1, ry2);
            let x2 = Math.max(rx1, rx2);
            let y2 = Math.max(ry1, ry2);
            const hid = lyrView.resizeHandleId;
            if (hid === "nw" || hid === "w" || hid === "sw") x1 = imgPt.x;
            if (hid === "ne" || hid === "e" || hid === "se") x2 = imgPt.x;
            if (hid === "nw" || hid === "n" || hid === "ne") y1 = imgPt.y;
            if (hid === "sw" || hid === "s" || hid === "se") y2 = imgPt.y;
            ann.rectangle = [x1, y1, x2, y2];
          }
          lyrView.dragStartImg = { ...imgPt };
          requestDrawLayerify();
        }
        return;
      }

      // Dragging annotation
      if (lyrView.draggingAnnIdx >= 0 && lyrView.dragStartImg) {
        const dx = imgPt.x - lyrView.dragStartImg.x;
        const dy = imgPt.y - lyrView.dragStartImg.y;
        if (Math.hypot(dx, dy) > 0.5) {
          lyrView.hasMovedDuringDrag = true;
        }
        const annotations = state.layerify.annotations || [];
        const draggingAnn = annotations[lyrView.draggingAnnIdx];
        if (draggingAnn) {
          const maxW = lyrView.imgW || (lyrView.img ? lyrView.img.width : 10000);
          const maxH = lyrView.imgH || (lyrView.img ? lyrView.img.height : 10000);
          if (draggingAnn.selected) {
            annotations.filter(a => a.selected).forEach(a => {
              utils.moveAnnotationByDelta(a, dx, dy, maxW, maxH);
            });
          } else {
            utils.moveAnnotationByDelta(draggingAnn, dx, dy, maxW, maxH);
          }
          lyrView.dragStartImg = { ...imgPt };
          requestDrawLayerify();
        }
        return;
      }

      // Drawing drafts
      if (lyrView.activeRectDraft) {
        lyrView.activeRectDraft[2] = imgPt.x;
        lyrView.activeRectDraft[3] = imgPt.y;
        updateLayerifyCursor(e, imgPt);
        requestDrawLayerify();
      } else if (lyrView.activeBrushStroke && lyrView.activeBrushStroke.length > 0) {
        lyrView.activeBrushStroke.push({ x: imgPt.x, y: imgPt.y });
        updateLayerifyCursor(e, imgPt);
        requestDrawLayerify();
      } else if (lyrView.activePolyDraft && lyrView.activePolyDraft.length > 0) {
        updateLayerifyCursor(e, imgPt);
        requestDrawLayerify();
      } else {
        // Hover test
        const prevHover = lyrView.hoverAnnIdx;
        lyrView.hoverAnnIdx = hitTestAnnotation(imgPt.x, imgPt.y);
        updateLayerifyCursor(e, imgPt);
        if (prevHover !== lyrView.hoverAnnIdx || lyrView.activeMode === "Brush") {
          requestDrawLayerify();
        }
      }
    });

    const stopInteraction = async e => {
      try {
        lyrCanvas.releasePointerCapture(e.pointerId);
      } catch (_) {}

      const rect = lyrCanvas.getBoundingClientRect();
      const imgPt = e && typeof e.clientX === "number"
        ? screenToImage(e.clientX - rect.left, e.clientY - rect.top)
        : { x: lyrView.mouseImgX || 0, y: lyrView.mouseImgY || 0 };

      if (lyrView.isPanning) {
        lyrView.isPanning = false;
        updateLayerifyCursor(e, imgPt);
        return;
      }

      // Finish resizing / moving vertex handle
      if (lyrView.resizingAnnIdx >= 0) {
        const annotations = state.layerify.annotations || [];
        const ann = annotations[lyrView.resizingAnnIdx];
        if (ann && lyrView.resizeHandleType === "rect" && ann.rectangle && ann.rectangle.length === 4) {
          const [x1, y1, x2, y2] = ann.rectangle;
          ann.rectangle = [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
        }
        const moved = lyrView.hasMovedDuringDrag;
        lyrView.resizingAnnIdx = -1;
        lyrView.resizeHandleType = null;
        lyrView.resizeHandleId = null;
        lyrView.dragStartImg = null;
        lyrView.hasMovedDuringDrag = false;
        updateLayerifyCursor(e, imgPt);
        if (moved) {
          await syncAnnotationsToServer(true, "Updated annotation geometry");
        } else {
          await syncAnnotationsToServer(false, "Selected annotation");
        }
        return;
      }

      // Finish dragging
      if (lyrView.draggingAnnIdx >= 0) {
        const clickedIdx = lyrView.draggingAnnIdx;
        const moved = lyrView.hasMovedDuringDrag;
        const multi = e && (e.ctrlKey || e.metaKey || e.shiftKey);
        lyrView.draggingAnnIdx = -1;
        lyrView.dragStartImg = null;
        lyrView.hasMovedDuringDrag = false;
        updateLayerifyCursor(e, imgPt);
        if (moved) {
          commitMovedBrushMasks();
          drawLayerifyCanvas();
          await syncAnnotationsToServer(true, "Moved annotation(s)");
        } else {
          if (!multi) {
            const annotations = state.layerify.annotations || [];
            annotations.forEach((a, idx) => {
              a.selected = (idx === clickedIdx);
            });
            drawLayerifyCanvas();
            window.ImageBaker.uiLayerify.renderAnnotationList();
          }
          await syncAnnotationsToServer(false, "Selected annotation");
        }
        return;
      }

      // Finish rectangle
      if (lyrView.activeRectDraft) {
        const [x1, y1, x2, y2] = lyrView.activeRectDraft;
        lyrView.activeRectDraft = null;
        updateLayerifyCursor(e, imgPt);
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
        const isErase = Boolean(lyrView.activeBrushErase);
        lyrView.activeBrushStroke = [];
        lyrView.activeBrushErase = false;
        updateLayerifyCursor(e, imgPt);
        await applyBrushStrokeToMask(pts, isErase);
      }
    };

    lyrCanvas.addEventListener("pointerup", stopInteraction);
    lyrCanvas.addEventListener("pointercancel", stopInteraction);
    lyrCanvas.addEventListener("pointerleave", () => {
      lyrView.isMouseOver = false;
      if (lyrView.hoverAnnIdx !== null) {
        lyrView.hoverAnnIdx = null;
        requestDrawLayerify();
      }
    });

    lyrCanvas.addEventListener("wheel", e => {
      e.preventDefault();
      if (e.altKey || lyrView.activeMode === "Brush") {
        const delta = e.deltaY < 0 ? 2 : -2;
        lyrView.brushSize = Math.max(2, Math.min(200, (lyrView.brushSize || 18) + delta));
        const brushInput = document.getElementById("input-lyr-brush-size") || document.getElementById("input-brush-size");
        const brushVal = document.getElementById("val-lyr-brush-size") || document.getElementById("val-brush-size");
        if (brushInput) brushInput.value = lyrView.brushSize;
        if (brushVal) brushVal.textContent = `${lyrView.brushSize}px`;
        drawLayerifyCanvas();
        return;
      }

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

    lyrCanvas.addEventListener("dblclick", async e => {
      const rect = lyrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const imgPt = screenToImage(sx, sy);

      // 1. If actively drawing a polygon draft with >= 3 points, close & finish it
      if (lyrView.activeMode === "Polygon" && lyrView.activePolyDraft.length >= 3) {
        await finishPolygon();
        return;
      }

      const annotations = state.layerify.annotations || [];

      // 2. Double-clicking an existing polygon vertex removes that point (if > 3 points)
      const handleHit = hitTestAnnotationHandle(imgPt.x, imgPt.y);
      if (handleHit && handleHit.type === "poly") {
        lyrView.activePolyDraft = [];
        const ann = annotations[handleHit.annIdx];
        if (ann && ann.polygon) {
          if (ann.polygon.length > 3) {
            ann.polygon.splice(handleHit.handleIdx, 1);
            if (ann.rectangle && ann.polygon.length >= 3) {
              const xs = ann.polygon.map(p => p[0]);
              const ys = ann.polygon.map(p => p[1]);
              ann.rectangle = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
            }
            annotations.forEach((a, idx) => { a.selected = (idx === handleHit.annIdx); });
            drawLayerifyCanvas();
            window.ImageBaker.uiLayerify.renderAnnotationList();
            await syncAnnotationsToServer(true, "Removed polygon point");
            showToast("layerify", "Removed polygon point");
          } else {
            showToast("layerify", "Polygon must have at least 3 points");
          }
          return;
        }
      }

      // 3. Double-clicking on a completed polygon's edge inserts a new vertex at that edge position
      const edgeHit = hitTestPolygonEdge(imgPt.x, imgPt.y);
      if (edgeHit) {
        lyrView.activePolyDraft = [];
        const ann = annotations[edgeHit.annIdx];
        if (ann && ann.polygon && ann.polygon.length >= 3) {
          ann.polygon.splice(edgeHit.edgeIdx + 1, 0, [edgeHit.point[0], edgeHit.point[1]]);
          if (ann.rectangle) {
            const xs = ann.polygon.map(p => p[0]);
            const ys = ann.polygon.map(p => p[1]);
            ann.rectangle = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
          }
          annotations.forEach((a, idx) => { a.selected = (idx === edgeHit.annIdx); });
          drawLayerifyCanvas();
          window.ImageBaker.uiLayerify.renderAnnotationList();
          await syncAnnotationsToServer(true, "Added polygon point");
          showToast("layerify", "Added polygon point");
          return;
        }
      }
    });

    lyrCanvas.addEventListener("contextmenu", e => {
      e.preventDefault();
      if (lyrView.activeMode === "Polygon" && lyrView.activePolyDraft.length > 0) {
        lyrView.activePolyDraft.pop();
        drawLayerifyCanvas();
        return;
      }
      const rect = lyrCanvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const imgPt = screenToImage(sx, sy);
      const annHit = hitTestAnnotation(imgPt.x, imgPt.y);
      const handleHit = hitTestAnnotationHandle(imgPt.x, imgPt.y);
      if (annHit === null && handleHit === null) {
        const annotations = state.layerify.annotations || [];
        if (annotations.some(a => a.selected)) {
          annotations.forEach(a => {
            a.selected = false;
          });
          window.ImageBaker.uiLayerify.renderAnnotationList();
          syncAnnotationsToServer(false, "Deselected all annotations");
        }
      }
      setLayerifyMode("Idle");
    });

    window.addEventListener("keydown", e => {
      if (window.ImageBaker.isTypingInTextField && window.ImageBaker.isTypingInTextField(e.target)) return;
      if (window.ImageBaker.isModalOpen && window.ImageBaker.isModalOpen()) return;
      if (state.active_tab === "Layerify" && (e.key === "Control" || e.key === "Meta" || e.key === " ") && !lyrView.isPanning) {
        if (lyrCanvas) lyrCanvas.style.cursor = CURSORS.PAN;
      } else if (state.active_tab === "Layerify" && e.key === "Alt" && lyrView.activeMode === "Brush") {
        if (lyrCanvas) lyrCanvas.style.cursor = CURSORS.ERASE || CURSORS.BRUSH;
      }
    });

    window.addEventListener("keyup", e => {
      if (state.active_tab === "Layerify" && (e.key === "Control" || e.key === "Meta" || e.key === " " || e.key === "Alt") && !lyrView.isPanning) {
        if (lyrCanvas) lyrCanvas.style.cursor = getCursorForMode(lyrView.activeMode);
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

    const paintBtn = document.getElementById("btn-lyr-brush-paint");
    if (paintBtn) {
      paintBtn.addEventListener("click", () => setBrushSubMode("paint"));
    }
    const eraseBtn = document.getElementById("btn-lyr-brush-erase");
    if (eraseBtn) {
      eraseBtn.addEventListener("click", () => setBrushSubMode("erase"));
    }
    const moveBtn = document.getElementById("btn-lyr-brush-move");
    if (moveBtn) {
      moveBtn.addEventListener("click", () => setBrushSubMode("move"));
    }
    const newBrushBtn = document.getElementById("btn-lyr-brush-new");
    if (newBrushBtn) {
      newBrushBtn.addEventListener("click", async () => {
        const annotations = state.layerify.annotations || [];
        const hadSel = annotations.some(a => a.selected);
        annotations.forEach(a => { a.selected = false; });
        setBrushSubMode("paint");
        drawLayerifyCanvas();
        window.ImageBaker.uiLayerify.renderAnnotationList();
        if (hadSel) {
          await syncAnnotationsToServer(false, "Ready for new brush annotation");
        }
        showToast("layerify", "Ready to paint a new brush annotation");
      });
    }

    const finishBtn = document.getElementById("btn-finish-polygon");
    if (finishBtn) {
      finishBtn.addEventListener("click", finishPolygon);
    }
  }

  async function finishPolygon() {
    const cleaned = [];
    for (const p of lyrView.activePolyDraft) {
      const prev = cleaned[cleaned.length - 1];
      if (!prev || Math.hypot(p.x - prev.x, p.y - prev.y) > 2.0 / lyrView.zoom) {
        cleaned.push(p);
      }
    }
    if (cleaned.length >= 3) {
      const poly = cleaned.map(p => [p.x, p.y]);
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
      selected: false,
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
    const seq = (lyrView.syncSeq || 0) + 1;
    lyrView.syncSeq = seq;
    lyrView.isSyncing = true;
    const payload = structuredClone(state.layerify.annotations || []);
    try {
      const res = await api.updateAnnotations(payload, pushUndo, message);
      if (seq !== lyrView.syncSeq) {
        return;
      }
      if (res.ok && res.state) {
        window.ImageBaker.applyServerState(res.state);
      }
    } catch (err) {
      if (seq === lyrView.syncSeq) {
        console.error("Failed to sync annotations:", err);
        showToast("layerify", "Sync failed: " + err.message);
      }
    } finally {
      if (seq === lyrView.syncSeq) {
        lyrView.isSyncing = false;
      }
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
