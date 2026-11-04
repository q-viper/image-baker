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

    // Candidate steps relative to image dimension, resolving down to 1px on high zoom
    const candidateSteps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000];
    let fineStep = candidateSteps[candidateSteps.length - 1];
    for (const s of candidateSteps) {
      if (s * z >= 5.0) {
        fineStep = s;
        break;
      }
    }
    let midStep = fineStep * 5;
    if (fineStep === 2) midStep = 10;
    else if (fineStep === 20 || fineStep === 25) midStep = 100;
    else if (fineStep === 200 || fineStep === 250) midStep = 1000;

    let majorStep = midStep * 5;
    if (midStep === 10) majorStep = 50;
    else if (midStep === 100) majorStep = 500;

    const imgScreenX0 = offsetX;
    const imgScreenY0 = offsetY;

    const minImgX = Math.floor((-offsetX) / (fineStep * z)) * fineStep;
    const maxImgX = Math.ceil((width - offsetX) / (fineStep * z)) * fineStep;
    const minImgY = Math.floor((-offsetY) / (fineStep * z)) * fineStep;
    const maxImgY = Math.ceil((height - offsetY) / (fineStep * z)) * fineStep;

    ctx.save();

    // 1. Draw Deep Fine Grid Lines
    ctx.lineWidth = 0.75;
    ctx.strokeStyle = isDark
      ? "rgba(148, 163, 184, 0.18)"
      : "rgba(100, 116, 139, 0.16)";
    ctx.beginPath();
    for (let ix = minImgX; ix <= maxImgX; ix += fineStep) {
      if (ix % midStep === 0) continue;
      const sx = Math.round(offsetX + ix * z) + 0.5;
      if (sx >= -1 && sx <= width + 1) {
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, height);
      }
    }
    for (let iy = minImgY; iy <= maxImgY; iy += fineStep) {
      if (iy % midStep === 0) continue;
      const sy = Math.round(offsetY + iy * z) + 0.5;
      if (sy >= -1 && sy <= height + 1) {
        ctx.moveTo(0, sy);
        ctx.lineTo(width, sy);
      }
    }
    ctx.stroke();

    // 2. Draw Medium Grid Lines
    ctx.lineWidth = 1.0;
    ctx.strokeStyle = isDark
      ? "rgba(148, 163, 184, 0.38)"
      : "rgba(71, 85, 105, 0.35)";
    ctx.beginPath();
    for (let ix = minImgX; ix <= maxImgX; ix += fineStep) {
      if (ix % midStep !== 0 || ix % majorStep === 0) continue;
      const sx = Math.round(offsetX + ix * z) + 0.5;
      if (sx >= -1 && sx <= width + 1) {
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, height);
      }
    }
    for (let iy = minImgY; iy <= maxImgY; iy += fineStep) {
      if (iy % midStep !== 0 || iy % majorStep === 0) continue;
      const sy = Math.round(offsetY + iy * z) + 0.5;
      if (sy >= -1 && sy <= height + 1) {
        ctx.moveTo(0, sy);
        ctx.lineTo(width, sy);
      }
    }
    ctx.stroke();

    // 3. Draw Major Grid Lines
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = isDark
      ? "rgba(186, 230, 253, 0.62)"
      : "rgba(30, 58, 138, 0.58)";
    ctx.beginPath();
    for (let ix = minImgX; ix <= maxImgX; ix += fineStep) {
      if (ix % majorStep !== 0) continue;
      const sx = Math.round(offsetX + ix * z) + 0.5;
      if (sx >= -1 && sx <= width + 1) {
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, height);
      }
    }
    for (let iy = minImgY; iy <= maxImgY; iy += fineStep) {
      if (iy % majorStep !== 0) continue;
      const sy = Math.round(offsetY + iy * z) + 0.5;
      if (sy >= -1 && sy <= height + 1) {
        ctx.moveTo(0, sy);
        ctx.lineTo(width, sy);
      }
    }
    ctx.stroke();

    // 4. Prominent Image Dimension Boundary Frame
    ctx.lineWidth = 1.75;
    ctx.strokeStyle = isDark ? "rgba(56, 189, 248, 0.85)" : "rgba(37, 99, 235, 0.85)";
    ctx.strokeRect(
      Math.round(imgScreenX0) + 0.5,
      Math.round(imgScreenY0) + 0.5,
      Math.round(targetW * z),
      Math.round(targetH * z)
    );

    // 5. Interactive Deep Snapping with Image Coordinate Tag
    if (
      hoverPos &&
      hoverPos.x >= 0 &&
      hoverPos.x < width &&
      hoverPos.y >= 0 &&
      hoverPos.y < height
    ) {
      const curImgX = (hoverPos.x - offsetX) / z;
      const curImgY = (hoverPos.y - offsetY) / z;
      const snapImgX = Math.round(curImgX / fineStep) * fineStep;
      const snapImgY = Math.round(curImgY / fineStep) * fineStep;
      const snapScreenX = Math.round(offsetX + snapImgX * z);
      const snapScreenY = Math.round(offsetY + snapImgY * z);

      const highlightColor = isDark
        ? "rgba(56, 189, 248, 0.9)"
        : "rgba(37, 99, 235, 0.9)";
      ctx.strokeStyle = highlightColor;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(snapScreenX + 0.5, 0);
      ctx.lineTo(snapScreenX + 0.5, height);
      ctx.moveTo(0, snapScreenY + 0.5);
      ctx.lineTo(width, snapScreenY + 0.5);
      ctx.stroke();

      ctx.fillStyle = highlightColor;
      ctx.beginPath();
      ctx.arc(snapScreenX, snapScreenY, 3.5, 0, Math.PI * 2);
      ctx.fill();

      // Precision Coordinate Readout Tag
      const coordText = `(${snapImgX}, ${snapImgY}) [${fineStep}px grid]`;
      ctx.font = "600 10.5px monospace";
      const tw = ctx.measureText(coordText).width;
      const tx = Math.min(width - tw - 12, Math.max(6, snapScreenX + 8));
      const ty = Math.min(height - 18, Math.max(18, snapScreenY - 8));
      ctx.fillStyle = isDark ? "rgba(15, 23, 42, 0.88)" : "rgba(255, 255, 255, 0.92)";
      utils.roundRect(ctx, tx - 4, ty - 12, tw + 8, 16, 3);
      ctx.fill();
      ctx.strokeStyle = highlightColor;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = isDark ? "#38bdf8" : "#1d4ed8";
      ctx.fillText(coordText, tx, ty);
    }

    ctx.restore();
  }

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.grid = {
    drawGridlines,
  };
})(window);
