/**
 * ImageBaker Web - Layerify Canvas Engine
 */
(function(window) {
  "use strict";

  const { state, lyrView, CURSORS, screenToImage, showToast } = window.ImageBaker;
  const utils = window.ImageBaker.utils;
  const api = window.ImageBaker.api;
  const masks = window.ImageBaker.canvasLayerifyMasks;
  const render = window.ImageBaker.canvasLayerifyRender;

  const {
    hitTestLabelPill,
    hitTestAnnotation,
    hitTestAnnotationHandle,
    hitTestPolygonEdge,
    drawLayerifyCanvas,
    requestDrawLayerify,
  } = render;

  const {
    isBrushAnnotation,
    preloadAnnotationMasks,
    commitMovedBrushMasks,
    applyBrushStrokeToMask,
  } = masks;

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
    isBrushAnnotation,
    preloadAnnotationMasks,
    commitMovedBrushMasks,
    applyBrushStrokeToMask,
    hitTestLabelPill,
    hitTestAnnotation,
    hitTestAnnotationHandle,
    hitTestPolygonEdge,
    drawLayerifyCanvas,
    requestDrawLayerify,
    setBrushSubMode,
    setLayerifyMode,
    addNewAnnotation,
    syncAnnotationsToServer,
    performLayerifyUndo,
    performLayerifyRedo,
  };
})(window);
