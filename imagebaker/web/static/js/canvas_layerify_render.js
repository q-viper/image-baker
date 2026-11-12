/**
 * ImageBaker Web - Layerify Canvas Rendering & Hit-Testing
 */
(function(window) {
  "use strict";

  const { state, lyrView, imageToScreen } = window.ImageBaker;
  const utils = window.ImageBaker.utils;
  const grid = window.ImageBaker.grid;
  const masks = window.ImageBaker.canvasLayerifyMasks;

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
      if (!masks.isBrushAnnotation(ann) && ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
        for (const pt of ann.points) {
          if (Math.hypot(ix - pt[0], iy - pt[1]) <= tol * 1.3) return i;
        }
      }
    }

    const hits = [];
    for (let i = annotations.length - 1; i >= 0; i--) {
      const ann = annotations[i];
      if (ann.visible === false) continue;

      if (masks.isBrushAnnotation(ann) || ann.has_mask) {
        masks.ensureMaskCanvasForAnnotation(ann);
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
          if (masks.isBrushAnnotation(ann)) continue;
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
      if (masks.isBrushAnnotation(ann)) continue;
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
    const lyrCanvas = lyrView.canvas;
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
        const mCanvas = masks.ensureMaskCanvasForAnnotation(ann);
        const mImg = mCanvas || lyrView.maskImageCache.get(ann.annotation_id);
        if (mImg && (mCanvas || mImg.complete)) {
          ctx.save();
          ctx.globalAlpha = isSel ? 0.65 : (isHov ? 0.52 : 0.40);
          const maskX = lyrView.offsetX + (ann.mask_offset_x || 0) * lyrView.zoom;
          const maskY = lyrView.offsetY + (ann.mask_offset_y || 0) * lyrView.zoom;
          ctx.drawImage(mImg, maskX, maskY, mImg.width * lyrView.zoom, mImg.height * lyrView.zoom);
          ctx.restore();
        }
        if (masks.isBrushAnnotation(ann) && (isSel || isHov) && ann.brush_bbox && ann.brush_bbox.length === 4) {
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
      if (!masks.isBrushAnnotation(ann) && (!ann.polygon || ann.polygon.length < 3) && ann.rectangle && ann.rectangle.length === 4) {
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
      if (!masks.isBrushAnnotation(ann) && ann.polygon && ann.polygon.length >= 3) {
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
      if (!masks.isBrushAnnotation(ann) && ann.points && ann.points.length > 0 && (!ann.polygon || ann.polygon.length === 0) && !ann.rectangle) {
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
      const selBrush = (state.layerify.annotations || []).find(a => a.selected && masks.isBrushAnnotation(a));
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

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.canvasLayerifyRender = {
    hitTestLabelPill,
    hitTestAnnotation,
    hitTestAnnotationHandle,
    hitTestPolygonEdge,
    drawLayerifyCanvas,
    requestDrawLayerify,
  };
})(window);
