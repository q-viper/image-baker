/**
 * ImageBaker Web - Multi-Depth Dimension-Adaptive Gridlines
 */
(function(window) {
  "use strict";

  const utils = window.ImageBaker.utils;

  function drawGridlines(ctx, width, height, offsetX, offsetY, zoom, hoverPos = null, imgW = null, imgH = null) {
    const appState = window.ImageBaker.state;
    if (!appState || !appState.show_gridlines) return;
    const isDark = appState.theme_mode === "dark";
    const z = Math.max(0.001, zoom);

    const lyrView = window.ImageBaker.lyrView;
    const targetW = Math.max(1, imgW || (lyrView.img ? lyrView.img.width : 1000));
    const targetH = Math.max(1, imgH || (lyrView.img ? lyrView.img.height : 1000));

    // Candidate steps relative to image dimension with readable screen spacing (>= 28px)
    const candidateSteps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000];
    let fineStep = candidateSteps[candidateSteps.length - 1];
    for (const s of candidateSteps) {
      if (s * z >= 28.0) {
        fineStep = s;
        break;
      }
    }
    const majorStep = fineStep * 5;

    const imgScreenX0 = offsetX;
    const imgScreenY0 = offsetY;

    const minImgX = Math.floor((-offsetX) / (fineStep * z)) * fineStep;
    const maxImgX = Math.ceil((width - offsetX) / (fineStep * z)) * fineStep;
    const minImgY = Math.floor((-offsetY) / (fineStep * z)) * fineStep;
    const maxImgY = Math.ceil((height - offsetY) / (fineStep * z)) * fineStep;

    ctx.save();

    // High-performance single-pass batched gridline paths
    const finePath = new Path2D();
    const majorPath = new Path2D();

    for (let ix = minImgX; ix <= maxImgX; ix += fineStep) {
      const sx = Math.round(offsetX + ix * z) + 0.5;
      if (sx >= -1 && sx <= width + 1) {
        const isMajor = (Math.round(ix / fineStep) % 5 === 0);
        const p = isMajor ? majorPath : finePath;
        p.moveTo(sx, 0);
        p.lineTo(sx, height);
      }
    }

    for (let iy = minImgY; iy <= maxImgY; iy += fineStep) {
      const sy = Math.round(offsetY + iy * z) + 0.5;
      if (sy >= -1 && sy <= height + 1) {
        const isMajor = (Math.round(iy / fineStep) % 5 === 0);
        const p = isMajor ? majorPath : finePath;
        p.moveTo(0, sy);
        p.lineTo(width, sy);
      }
    }

    // 1. Draw Subtle Secondary Lines
    ctx.lineWidth = 0.75;
    ctx.strokeStyle = isDark
      ? "rgba(148, 163, 184, 0.18)"
      : "rgba(100, 116, 139, 0.16)";
    ctx.stroke(finePath);

    // 2. Draw Major Lines (Every 5th)
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = isDark
      ? "rgba(186, 230, 253, 0.52)"
      : "rgba(30, 58, 138, 0.42)";
    ctx.stroke(majorPath);

    // 3. Image Dimension Boundary Frame
    ctx.lineWidth = 1.75;
    ctx.strokeStyle = isDark ? "rgba(56, 189, 248, 0.85)" : "rgba(37, 99, 235, 0.85)";
    ctx.strokeRect(
      Math.round(imgScreenX0) + 0.5,
      Math.round(imgScreenY0) + 0.5,
      Math.round(targetW * z),
      Math.round(targetH * z)
    );

    ctx.restore();
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.grid = {
    drawGridlines,
  };
})(window);

