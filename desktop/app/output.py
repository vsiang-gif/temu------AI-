"""裁切、放大、放入印刷画布，并以 300DPI 透明 PNG 保存。"""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass
class OutputOptions:
    size_mode: str = "crop"  # crop 原始裁切 / long 长边放大到 / canvas 固定画布
    long_side: int = 4500
    canvas_w: int = 4500
    canvas_h: int = 5400
    align: str = "center"  # center 居中 / top 顶部居中
    padding: int = 20
    dpi: int = 300


def _resize_premultiplied(rgba: np.ndarray, w: int, h: int) -> np.ndarray:
    img = rgba.astype(np.float32)
    a = img[..., 3:4] / 255.0
    pre = np.concatenate([img[..., :3] * a, img[..., 3:4]], axis=2)
    up = w * h > rgba.shape[0] * rgba.shape[1]
    out = cv2.resize(pre, (w, h), interpolation=cv2.INTER_LANCZOS4 if up else cv2.INTER_AREA)
    out = np.clip(out, 0, 255)
    alpha = out[..., 3:4] / 255.0
    color = np.where(alpha > 1e-3, out[..., :3] / np.maximum(alpha, 1e-3), 0)
    return np.concatenate([np.clip(color, 0, 255), out[..., 3:4]], axis=2).astype(np.uint8)


def finalize(rgba: np.ndarray, opts: OutputOptions) -> np.ndarray:
    ys, xs = np.nonzero(rgba[..., 3] > 8)
    if ys.size == 0:
        raise ValueError("没有可导出的印花")
    pad = max(0, opts.padding)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + 1 + pad, rgba.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + 1 + pad, rgba.shape[1])
    art = rgba[y0:y1, x0:x1]
    h, w = art.shape[:2]

    if opts.size_mode == "long" and opts.long_side > 0:
        scale = opts.long_side / max(h, w)
        return _resize_premultiplied(art, max(1, round(w * scale)), max(1, round(h * scale)))

    if opts.size_mode == "canvas" and opts.canvas_w > 0 and opts.canvas_h > 0:
        scale = min(opts.canvas_w / w, opts.canvas_h / h)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        art = _resize_premultiplied(art, nw, nh)
        canvas = np.zeros((opts.canvas_h, opts.canvas_w, 4), np.uint8)
        x = (opts.canvas_w - nw) // 2
        y = 0 if opts.align == "top" else (opts.canvas_h - nh) // 2
        canvas[y : y + nh, x : x + nw] = art
        return canvas

    return art


def save_png(rgba: np.ndarray, path: str, dpi: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rgb = cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA)
    tmp = path + ".tmp"
    Image.fromarray(rgb, "RGBA").save(tmp, format="PNG", dpi=(dpi, dpi), optimize=False, compress_level=6)
    os.replace(tmp, path)
