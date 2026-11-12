/**
 * ImageBaker Web - Layerify Brush Mask & RLE Utilities
 */
(function(window) {
  "use strict";

  const { state, lyrView, showToast } = window.ImageBaker;
  const utils = window.ImageBaker.utils;

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
            window.ImageBaker.canvasLayerify.drawLayerifyCanvas();
          };
          mImg.src = "data:image/png;base64," + ann.mask_png_b64;
          lyrView.maskImageCache.set(ann.annotation_id, mImg);
          lyrView.maskSigCache.set(ann.annotation_id, sig);
        }
      }
    });
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
    const canvasLayerify = window.ImageBaker.canvasLayerify;
    const annotations = state.layerify.annotations || [];
    const imgW = lyrView.imgW || (lyrView.img ? lyrView.img.width : 800);
    const imgH = lyrView.imgH || (lyrView.img ? lyrView.img.height : 600);
    if (imgW <= 0 || imgH <= 0) return;

    // Find target brush annotation: either a currently selected brush annotation,
    // or (when erasing) the brush annotation under the start of the stroke.
    let targetAnn = annotations.find(a => a.selected && a.visible !== false && (isBrushAnnotation(a) || a.has_mask));
    if (!targetAnn && isErase) {
      const hitIdx = canvasLayerify.hitTestAnnotation(pts[0].x, pts[0].y);
      if (hitIdx !== null && annotations[hitIdx] && (isBrushAnnotation(annotations[hitIdx]) || annotations[hitIdx].has_mask)) {
        targetAnn = annotations[hitIdx];
        annotations.forEach((a, i) => {
          a.selected = (i === hitIdx);
        });
      }
    }

    if (isErase && !targetAnn) {
      showToast("layerify", "Select or click on a brush mask to erase");
      canvasLayerify.drawLayerifyCanvas();
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
        canvasLayerify.drawLayerifyCanvas();
        window.ImageBaker.uiLayerify.renderAnnotationList();
        await canvasLayerify.syncAnnotationsToServer(true, "Erased brush annotation");
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

      canvasLayerify.drawLayerifyCanvas();
      window.ImageBaker.uiLayerify.renderAnnotationList();
      await canvasLayerify.syncAnnotationsToServer(true, isErase ? "Erased from brush mask" : "Updated brush mask");
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
      canvasLayerify.drawLayerifyCanvas();
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
    canvasLayerify.drawLayerifyCanvas();
    window.ImageBaker.uiLayerify.renderAnnotationList();
    await canvasLayerify.syncAnnotationsToServer(true, "Created brush annotation");
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.canvasLayerifyMasks = {
    isBrushAnnotation,
    getAnnotationMaskSignature,
    ensureMaskCanvasForAnnotation,
    preloadAnnotationMasks,
    commitMovedBrushMasks,
    applyBrushStrokeToMask,
  };
})(window);
