from typing import Any

import cv2
import numpy as np


def mask_to_rle(mask: np.ndarray | None) -> list[int]:
    """
    Encode a 2D binary/uint8 mask (H, W) into row-major run-length counts
    starting with background (0): [count_0, count_1, count_0, count_1, ...].
    """
    if mask is None:
        return []
    arr = np.asarray(mask)
    if arr.size == 0:
        return []
    if arr.ndim == 3:
        arr = arr[:, :, -1] if arr.shape[2] == 4 else arr[:, :, 0]
    flat = (arr.ravel() > 0).astype(np.uint8)
    if not np.any(flat):
        return []
    diffs = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    boundaries = np.concatenate(([0], diffs, [flat.size]))
    counts = np.diff(boundaries).tolist()
    if flat[0] == 1:
        counts.insert(0, 0)
    return [int(c) for c in counts]


def _decode_label_studio_bitstream_rle(
    rle: list[int], height: int, width: int
) -> np.ndarray | None:
    """Fallback decoder for Label Studio's packed bitstream RLE format."""
    try:
        bits = "".join(f"{int(b) & 0xFF:08b}" for b in rle)
        pos = 0
        total_bits = len(bits)

        def read_bits(n: int) -> int:
            nonlocal pos
            if pos + n > total_bits:
                val_str = bits[pos:].ljust(n, "0")
                pos = total_bits
                return int(val_str, 2) if val_str else 0
            val = int(bits[pos : pos + n], 2)
            pos += n
            return val

        num = read_bits(32)
        word_size = read_bits(5) + 1
        rle_sizes = [read_bits(4) + 1 for _ in range(4)]
        out = np.zeros(num, dtype=np.uint8)
        i = 0
        while i < num and pos < total_bits:
            flag = read_bits(1)
            run_len = 1 + read_bits(rle_sizes[read_bits(2)])
            if flag:
                val = read_bits(word_size)
                out[i : min(num, i + run_len)] = val
                i += run_len
            else:
                for _ in range(run_len):
                    if i >= num:
                        break
                    out[i] = read_bits(word_size)
                    i += 1
        expected = int(height) * int(width)
        if out.size == expected * 4:
            return (out.reshape((int(height), int(width), 4))[:, :, 3] > 0).astype(
                np.uint8
            )
        if out.size >= expected:
            return (out[:expected].reshape((int(height), int(width))) > 0).astype(
                np.uint8
            )
    except Exception:
        pass
    return None


def rle_to_mask(
    rle: list[int] | dict[str, Any] | None,
    height: int | None = None,
    width: int | None = None,
) -> np.ndarray | None:
    """
    Decode a run-length encoded mask (or Label Studio RLE dict) into a 2D uint8
    binary mask of shape (height, width) with values in {0, 1}.
    """
    if rle is None:
        return None
    if isinstance(rle, dict):
        size = rle.get("mask_size") or rle.get("size")
        if size and len(size) == 2:
            height = int(size[0])
            width = int(size[1])
        rle = rle.get("rle") or rle.get("counts") or []
    if not isinstance(rle, (list, tuple)) or len(rle) == 0:
        return None
    if not height or not width or int(height) <= 0 or int(width) <= 0:
        return None

    h, w = int(height), int(width)
    counts = [max(0, int(c)) for c in rle]
    total = sum(counts)
    expected = h * w
    if total == expected:
        vals = np.arange(len(counts), dtype=np.uint8) % 2
        flat = np.repeat(vals, counts)
        return flat.reshape((h, w))

    # Fallback: check if this is Label Studio's bitstream RLE
    ls_mask = _decode_label_studio_bitstream_rle(counts, h, w)
    if ls_mask is not None:
        return ls_mask

    # Fallback if total slightly differs: pad or truncate
    if total > 0:
        vals = np.arange(len(counts), dtype=np.uint8) % 2
        flat = np.repeat(vals, counts)
        if flat.size < expected:
            flat = np.pad(flat, (0, expected - flat.size), mode="constant")
        else:
            flat = flat[:expected]
        return flat.reshape((h, w))
    return None


def _extract_mask_geometry(
    mask_arr: np.ndarray | None,
) -> tuple[list[list[list[float]]], list[list[float]], list[int] | None, float]:
    """Extract all external contours, largest contour, union bbox, and pixel area."""
    if mask_arr is None or mask_arr.ndim < 2 or mask_arr.size == 0 or not np.any(mask_arr):
        return [], [], None, 0.0
    mask_uint8 = (mask_arr > 0).astype(np.uint8) * 255
    contours, _ = cv2.findContours(
        mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    ordered_contours = sorted(contours, key=cv2.contourArea, reverse=True)
    mask_polys: list[list[list[float]]] = []
    for contour in ordered_contours:
        if len(contour) >= 3:
            pts = [[float(p[0][0]), float(p[0][1])] for p in contour]
            if len(pts) >= 3:
                mask_polys.append(pts)
    mask_poly = mask_polys[0] if mask_polys else []
    mask_rect = None
    bx, by, bw, bh = cv2.boundingRect(mask_uint8)
    if bw > 0 and bh > 0:
        mask_rect = [int(bx), int(by), int(bw), int(bh)]
    mask_area = float(np.count_nonzero(mask_uint8))
    return mask_polys, mask_poly, mask_rect, mask_area


def shift_binary_mask(
    mask: np.ndarray | None,
    offset_x: int,
    offset_y: int,
) -> np.ndarray | None:
    """Translate a 2D mask array by integer (offset_x, offset_y) within its canvas bounds."""
    if mask is None or (offset_x == 0 and offset_y == 0):
        return mask
    h, w = mask.shape[:2]
    shifted = np.zeros_like(mask)
    sx1 = max(0, -int(offset_x))
    sy1 = max(0, -int(offset_y))
    sx2 = min(w, w - int(offset_x))
    sy2 = min(h, h - int(offset_y))
    dx1 = max(0, int(offset_x))
    dy1 = max(0, int(offset_y))
    dx2 = min(w, int(offset_x) + (sx2 - sx1))
    dy2 = min(h, int(offset_y) + (sy2 - sy1))
    if sx2 > sx1 and sy2 > sy1 and dx2 > dx1 and dy2 > dy1:
        shifted[dy1:dy2, dx1:dx2] = mask[sy1:sy2, sx1:sx2]
    return shifted
