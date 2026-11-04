/**
 * ImageBaker Web - Utility and Math Helpers
 */
(function(window) {
  "use strict";

  function pointInPolygon(x, y, poly) {
    if (!poly || poly.length < 3) return false;
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0];
      const yi = poly[i][1];
      const xj = poly[j][0];
      const yj = poly[j][1];
      const intersect = ((yi > y) !== (yj > y)) &&
        (x < (xj - xi) * (y - yi) / (yj - yi + 0.0000001) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  function distToSegment(px, py, x1, y1, x2, y2) {
    const l2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1);
    if (l2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
  }

  function roundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, Math.min(w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  function rgbToHex(r, g, b) {
    return "#" + [r, g, b].map(x => {
      const hex = Number(x).toString(16);
      return hex.length === 1 ? "0" + hex : hex;
    }).join("");
  }

  function hexToRgb(hex) {
    const res = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || "#ffffff");
    return res
      ? [parseInt(res[1], 16), parseInt(res[2], 16), parseInt(res[3], 16)]
      : [255, 255, 255];
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function downloadTextFile(filename, content) {
    const blob = new Blob([content], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const crossPatternCache = new Map();
  function getDiagCrossPattern(ctx, r, g, b, alpha = 0.45) {
    const key = `${r},${g},${b},${alpha}`;
    if (crossPatternCache.has(key)) {
      return crossPatternCache.get(key);
    }
    const patCanvas = document.createElement("canvas");
    patCanvas.width = 10;
    patCanvas.height = 10;
    const pctx = patCanvas.getContext("2d");
    pctx.strokeStyle = `rgba(${r},${g},${b},${alpha})`;
    pctx.lineWidth = 1.4;
    pctx.beginPath();
    pctx.moveTo(0, 0);
    pctx.lineTo(10, 10);
    pctx.moveTo(10, 0);
    pctx.lineTo(0, 10);
    pctx.stroke();
    const pat = ctx.createPattern(patCanvas, "repeat");
    crossPatternCache.set(key, pat);
    return pat;
  }

  function svgCursor(svgBody, hotX, hotY, fallback) {
    const encoded = encodeURIComponent(svgBody);
    return `url("data:image/svg+xml;utf8,${encoded}") ${hotX} ${hotY}, ${fallback}`;
  }

  function getRectHandles(rect) {
    if (!rect || rect.length < 4) return [];
    const [x1, y1, x2, y2] = rect;
    const mx = (x1 + x2) / 2.0;
    const my = (y1 + y2) / 2.0;
    return [
      { id: "nw", x: x1, y: y1 },
      { id: "ne", x: x2, y: y1 },
      { id: "se", x: x2, y: y2 },
      { id: "sw", x: x1, y: y2 },
      { id: "n", x: mx, y: y1 },
      { id: "e", x: x2, y: my },
      { id: "s", x: mx, y: y2 },
      { id: "w", x: x1, y: my }
    ];
  }

  function getAnnotationAnchorPoint(ann) {
    if (ann.rectangle) {
      return { x: ann.rectangle[0], y: ann.rectangle[1] };
    }
    if (ann.polygon && ann.polygon.length > 0) {
      let minY = Infinity;
      let minX = Infinity;
      for (const pt of ann.polygon) {
        if (pt[1] < minY || (pt[1] === minY && pt[0] < minX)) {
          minY = pt[1];
          minX = pt[0];
        }
      }
      return { x: minX, y: minY };
    }
    if (ann.points && ann.points.length > 0) {
      return { x: ann.points[0][0], y: ann.points[0][1] };
    }
    return { x: 0, y: 0 };
  }

  function moveAnnotationByDelta(ann, dx, dy, maxW, maxH) {
    if (ann.rectangle) {
      ann.rectangle = [
        Math.max(0, Math.min(maxW, ann.rectangle[0] + dx)),
        Math.max(0, Math.min(maxH, ann.rectangle[1] + dy)),
        Math.max(0, Math.min(maxW, ann.rectangle[2] + dx)),
        Math.max(0, Math.min(maxH, ann.rectangle[3] + dy)),
      ];
    }
    if (ann.polygon && ann.polygon.length > 0) {
      ann.polygon = ann.polygon.map(pt => [
        Math.max(0, Math.min(maxW, pt[0] + dx)),
        Math.max(0, Math.min(maxH, pt[1] + dy))
      ]);
    }
    if (ann.points && ann.points.length > 0) {
      ann.points = ann.points.map(pt => [
        Math.max(0, Math.min(maxW, pt[0] + dx)),
        Math.max(0, Math.min(maxH, pt[1] + dy))
      ]);
    }
    if (ann.has_mask || ann.mask_png_b64) {
      ann.mask_offset_x = (ann.mask_offset_x || 0) + dx;
      ann.mask_offset_y = (ann.mask_offset_y || 0) + dy;
    }
  }

  // Export to window.ImageBaker
  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.utils = {
    pointInPolygon,
    distToSegment,
    roundRect,
    rgbToHex,
    hexToRgb,
    escapeHtml,
    readFileAsDataUrl,
    downloadTextFile,
    getDiagCrossPattern,
    svgCursor,
    getRectHandles,
    getAnnotationAnchorPoint,
    moveAnnotationByDelta,
  };
})(window);

