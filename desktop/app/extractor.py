"""本地印花提取：U2-Net 找出衣服/人物主体，再按衣服底色分离出印花。

思路：
1. U2-Net（或 ISNet）得到主体区域，排除背景。
2. 在主体内找到黑/白布料像素，估计“每个位置的布料亮度”（用于消除褶皱和阴影）。
3. 与布料颜色差异大的像素 = 印花，得到柔和的 alpha。
4. 只保留被布料包围的区域（皮肤、头发、背景都和外部连通，会被自动排除）。
5. 去掉领标/吊牌等小杂块，导向滤波精修边缘，去除边缘的布料底色残留。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class ExtractOptions:
    shirt_color: str = "auto"  # auto / black / white
    sensitivity: int = 50  # 0-100，越大越能提取淡色/细小印花，但越容易带入褶皱
    feather: int = 2  # 0-5 边缘柔化
    enclosed_only: bool = True  # 只保留被衣服包围的区域
    remove_small: bool = True  # 去除领标、吊牌等小杂块
    use_u2net: bool = True
    knockout_fabric: bool = False  # Google AI 模式：把印花里露出的布料色挖成透明（仅斑驳做旧印花需要）


@dataclass
class ExtractResult:
    rgba: np.ndarray  # H x W x 4, BGRA uint8
    confidence: float
    shirt_color: str
    warnings: list[str] = field(default_factory=list)
    garment_ratio: float = 0.0  # AI 遮罩里被识别为整件衣服/背景而剔除的比例


class SaliencyModel:
    """U2-Net / U2-Netp / ISNet 的 ONNX 推理封装。"""

    def __init__(self, model_path: str):
        import onnxruntime as ort

        preferred = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
        available = ort.get_available_providers()
        providers = [p for p in preferred if p in available] or available
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(model_path, sess_options=options, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        name = os.path.basename(model_path).lower()
        if "isnet" in name:
            self.size = 1024
            self.mean = np.array([0.5, 0.5, 0.5], np.float32)
            self.std = np.array([1.0, 1.0, 1.0], np.float32)
        else:
            self.size = 320
            self.mean = np.array([0.485, 0.456, 0.406], np.float32)
            self.std = np.array([0.229, 0.224, 0.225], np.float32)
        self.name = os.path.basename(model_path)

    def predict(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        x = cv2.resize(rgb, (self.size, self.size), interpolation=cv2.INTER_AREA).astype(np.float32)
        x /= max(float(x.max()), 1e-6)
        x = (x - self.mean) / self.std
        x = x.transpose(2, 0, 1)[None].astype(np.float32)
        pred = self.session.run(None, {self.input_name: x})[0]
        pred = pred.reshape(pred.shape[-2], pred.shape[-1]).astype(np.float32)
        lo, hi = float(pred.min()), float(pred.max())
        pred = (pred - lo) / max(hi - lo, 1e-6)
        return cv2.resize(pred, (w, h), interpolation=cv2.INTER_LINEAR)


# ---------- 读写工具 ----------


def read_image(path: str) -> np.ndarray:
    """支持中文路径；带透明通道的图片会先铺白底。"""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("无法读取图片，文件可能已损坏或格式不支持")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        alpha = img[..., 3:4].astype(np.float32) / 255.0
        img = (img[..., :3].astype(np.float32) * alpha + 255.0 * (1 - alpha)).astype(np.uint8)
    if img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return img


# ---------- 图像算法工具 ----------


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    m = mask.astype(np.uint8) * 255
    h, w = m.shape
    padded = cv2.copyMakeBorder(m, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood = padded.copy()
    cv2.floodFill(flood, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 255)
    holes = cv2.bitwise_not(flood)[1:-1, 1:-1]
    return (m | holes) > 0


def _largest_component(mask: np.ndarray) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == idx


SHARPNESS_MIN = 0.2


def _sharpness_score(gray: np.ndarray, mask: np.ndarray) -> float:
    """How much detail is lost when the print is halved and scaled back up.

    Sharp prints lose a lot; blurry or upscaled ones barely change. Only edge-rich
    interior pixels are measured so the print/fabric boundary and flat fills don't
    skew it. Returns -1 when there isn't enough texture to judge (e.g. flat logos).
    """
    g = gray.astype(np.float32)
    h, w = g.shape
    if h < 32 or w < 32:
        return -1.0
    k = max(3, int(min(h, w) * 0.02)) | 1
    inner = cv2.erode(mask.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
    if inner.sum() < 400:
        return -1.0
    small = cv2.resize(g, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    back = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    mag = np.hypot(cv2.Sobel(back, cv2.CV_32F, 1, 0), cv2.Sobel(back, cv2.CV_32F, 0, 1))
    thr = max(float(np.percentile(mag[inner], 85)), 12.0)
    sel = inner & (mag >= thr)
    if sel.sum() < max(200, 0.002 * inner.sum()):
        return -1.0
    return float(np.abs(g - back)[sel].mean() / (mag[sel].mean() / 8 + 1e-6))


def _normalized_blur(values: np.ndarray, weights: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    wf = weights.astype(np.float32)
    num = cv2.GaussianBlur(values * wf, (0, 0), sigma)
    den = cv2.GaussianBlur(wf, (0, 0), sigma)
    return num / np.maximum(den, 1e-6), den


def _background_luminance(L: np.ndarray, fabric: np.ndarray, size: int) -> np.ndarray:
    """多尺度估计布料亮度：小尺度跟踪褶皱，大面积印花内部回退到大尺度。"""
    fallback = float(np.median(L[fabric])) if fabric.any() else float(L.mean())
    result = np.full(L.shape, fallback, np.float32)
    filled = np.zeros(L.shape, bool)
    for divisor in (70, 30, 12, 5):
        est, den = _normalized_blur(L, fabric, max(size / divisor, 2.0))
        ok = (den > 0.08) & ~filled
        result[ok] = est[ok]
        filled |= ok
    return result


def _guided_filter(guide: np.ndarray, src: np.ndarray, radius: int, eps: float) -> np.ndarray:
    k = (2 * radius + 1, 2 * radius + 1)
    mean_i = cv2.boxFilter(guide, -1, k)
    mean_p = cv2.boxFilter(src, -1, k)
    cov_ip = cv2.boxFilter(guide * src, -1, k) - mean_i * mean_p
    var_i = cv2.boxFilter(guide * guide, -1, k) - mean_i * mean_i
    a = cov_ip / (var_i + eps)
    b = mean_p - a * mean_i
    return cv2.boxFilter(a, -1, k) * guide + cv2.boxFilter(b, -1, k)


def _detect_shirt(L: np.ndarray, chroma: np.ndarray, region: np.ndarray, requested: str) -> str:
    if requested in ("black", "white"):
        return requested
    neutral = region & (chroma < 20)
    dark = int((neutral & (L < 90)).sum())
    light = int((neutral & (L > 165)).sum())
    return "black" if dark >= light else "white"


def _fabric_seed(L, chroma, region, shirt) -> np.ndarray:
    if shirt == "black":
        seed = region & (L < 85) & (chroma < 22)
        if seed.sum() < 0.05 * max(region.sum(), 1):
            seed = region & (L < 110) & (chroma < 28)
    else:
        seed = region & (L > 165) & (chroma < 22)
        if seed.sum() < 0.05 * max(region.sum(), 1):
            seed = region & (L > 135) & (chroma < 28)
    return seed


def _expand_to_garment(region: np.ndarray, L: np.ndarray, chroma: np.ndarray, shirt: str) -> np.ndarray:
    """U2-Net 有时只认出印花本身（比如大幅油画），而不是整件衣服。

    这时区域里几乎没有布料，后续“被衣服包围”的判断会把整幅印花当成外部排除掉。
    检测到这种情况时，把紧挨区域的同色布料并进来，恢复成整件衣服。
    """
    h, w = region.shape
    full = np.ones_like(region)
    seed = _fabric_seed(L, chroma, full, shirt)
    if (seed & region).sum() >= 0.3 * max(region.sum(), 1):
        return region
    n, labels, stats, _ = cv2.connectedComponentsWithStats(seed.astype(np.uint8), connectivity=8)
    if n <= 1:
        return region
    k = max(5, int(max(h, w) * 0.02)) | 1
    ring = cv2.dilate(region.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    touching = np.unique(labels[ring & seed])
    touching = touching[(touching > 0) & (stats[touching, cv2.CC_STAT_AREA] > 0.02 * h * w)]
    if touching.size == 0:
        return region
    grown = region | np.isin(labels, touching)
    return _fill_holes(cv2.morphologyEx(grown.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0)


def _missed_print_ratio(raw: np.ndarray, kept: np.ndarray, region: np.ndarray, size: int) -> float:
    """衣服中间（不接触区域边缘）的明显图案中，有多少比例没有导出。"""
    k = max(5, int(size * 0.02)) | 1
    eroded = cv2.erode(
        region.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)),
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    edge_band = region & ~(eroded > 0)
    n, labels, stats, _ = cv2.connectedComponentsWithStats((raw & region).astype(np.uint8), connectivity=8)
    if n <= 1:
        return 0.0
    touches = np.zeros(n, bool)
    touches[np.unique(labels[edge_band])] = True
    big = stats[:, cv2.CC_STAT_AREA] >= max(30, int(region.sum() * 0.002))
    inner = big & ~touches
    inner[0] = False
    target = inner[labels]
    total = int(target.sum())
    if total == 0:
        return 0.0
    covered = cv2.dilate(kept.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return 1.0 - float((target & covered).sum()) / total


def _soft_alpha(L, A, B, fabric, region, sensitivity, size):
    a0 = float(np.median(A[fabric])) if fabric.any() else 128.0
    b0 = float(np.median(B[fabric])) if fabric.any() else 128.0
    bg_l = _background_luminance(L, fabric, size)
    d_l = L - bg_l
    d_c = np.hypot(A - a0, B - b0)
    score = np.sqrt(d_l * d_l + (1.5 * d_c) ** 2)
    s = np.clip(sensitivity / 100.0, 0.0, 1.0)
    t_high = 44.0 - 30.0 * s
    t_low = t_high * 0.45
    alpha = np.clip((score - t_low) / (t_high - t_low), 0.0, 1.0) * region
    return alpha.astype(np.float32), bg_l, a0, b0


def _enclosed_mask(fabric_hard: np.ndarray) -> np.ndarray:
    """非布料区域中，不与图片边缘连通的部分（= 被衣服包围的印花）。"""
    inv = (~fabric_hard).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    h, w = inv.shape
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, cw, ch, _ = stats[i]
        if x > 0 and y > 0 and x + cw < w and y + ch < h:
            keep[i] = True
    return keep[labels]


def _clean_components(hard: np.ndarray, size: int, remove_small: bool) -> np.ndarray:
    h, w = hard.shape
    m = cv2.morphologyEx(hard.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    min_area = max(12, int(h * w * 0.00002))
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    m = keep[labels]
    if not remove_small or not m.any():
        return m

    k = max(3, int(size * 0.06)) | 1
    grouped = cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n2, labels2 = cv2.connectedComponents(grouped, connectivity=8)
    if n2 <= 2:
        return m
    areas = np.bincount(labels2[m], minlength=n2)
    keep2 = areas >= 0.15 * areas.max()
    keep2[0] = False
    return m & keep2[labels2]


def _drop_wrinkles(hard: np.ndarray, L: np.ndarray, chroma: np.ndarray, size: int, sensitivity: int) -> np.ndarray:
    """褶皱/阴影是无色、边缘平缓的明暗变化；印花边缘锐利。按“组”判断，避免误删印花里的细节。"""
    if not hard.any():
        return hard
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)
    n, labels, cstats, _ = cv2.connectedComponentsWithStats(hard.astype(np.uint8), connectivity=8)
    if n <= 1:
        return hard
    border = hard & ~(cv2.erode(hard.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    idx = labels[border]
    counts = np.bincount(idx, minlength=n).astype(np.float64)
    edge = np.bincount(idx, weights=grad[border], minlength=n) / np.maximum(counts, 1)
    area = cstats[:, cv2.CC_STAT_AREA].astype(np.float64)
    chroma_mean = np.bincount(labels.ravel(), weights=chroma.ravel(), minlength=n) / np.maximum(area, 1)
    l_sum = np.bincount(labels.ravel(), weights=L.ravel(), minlength=n)
    l_sq = np.bincount(labels.ravel(), weights=(L * L).ravel(), minlength=n)
    l_std = np.sqrt(np.maximum(l_sq / np.maximum(area, 1) - (l_sum / np.maximum(area, 1)) ** 2, 0))

    # 用面积加权的高分位作为“印花边缘强度”参考，避免被单个噪点拉偏
    order = np.argsort(edge[1:])[::-1] + 1
    cum = np.cumsum(area[order])
    ref = float(edge[order[min(np.searchsorted(cum, 0.3 * cum[-1]), len(order) - 1)]])
    s = np.clip(sensitivity / 100.0, 0.0, 1.0)
    ratio = 0.3 - 0.15 * s  # 灵敏度越高，越保留弱边缘
    threshold = max(100.0 * (1.2 - s), ratio * ref)

    strong = np.zeros(n, bool)
    strong[1:] = (edge[1:] >= threshold) | ((chroma_mean[1:] > 12) & (edge[1:] >= 0.5 * threshold)) | (l_std[1:] > 25)
    if not strong[1:].any():
        return hard
    strong_mask = strong[labels]
    k = max(5, int(size * 0.02)) | 1
    zone = cv2.dilate(strong_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    inside = np.bincount(labels[zone & hard], minlength=n) / np.maximum(area, 1)
    keep = strong | (inside > 0.9)
    keep[0] = False
    return hard & keep[labels]


def _restore_details(kept: np.ndarray, alpha: np.ndarray, region: np.ndarray, size: int) -> np.ndarray:
    """找回被过滤掉的标点、i 上的点、撇号等小细节。

    条件：紧挨着已保留的印花、形状紧凑（不是细长的褶皱）、与布料有明显反差。
    缺一个点就是货不对板，所以这里宁可多留。
    """
    if not kept.any():
        return kept
    h, w = kept.shape
    k = max(9, int(size * 0.035)) | 1
    zone = cv2.dilate(kept.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    candidates = (alpha > 0.3) & region & zone & ~kept
    if not candidates.any():
        return kept
    n, labels, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), connectivity=8)
    area = stats[:, cv2.CC_STAT_AREA].astype(np.float64)
    a_sum = np.bincount(labels.ravel(), weights=alpha.ravel(), minlength=n)
    a_max = np.zeros(n)
    np.maximum.at(a_max, labels.ravel(), alpha.ravel())
    mean_alpha = a_sum / np.maximum(area, 1)

    max_area = max(60.0, h * w * 0.003)
    bw = stats[:, cv2.CC_STAT_WIDTH].astype(np.float64)
    bh = stats[:, cv2.CC_STAT_HEIGHT].astype(np.float64)
    elongation = np.maximum(bw, bh) / np.maximum(np.minimum(bw, bh), 1)
    fill = area / np.maximum(bw * bh, 1)

    ok = (
        (area >= 2)
        & (area <= max_area)
        & (a_max >= 0.6)
        & (mean_alpha >= 0.4)
        & (elongation <= 4.0)
        & (fill >= 0.3)
    )
    ok[0] = False
    return kept | ok[labels]


# ---------- 主流程 ----------


def extract_local(bgr: np.ndarray, opts: ExtractOptions, model: SaliencyModel | None) -> ExtractResult:
    h, w = bgr.shape[:2]
    size = max(h, w)
    warnings: list[str] = []

    if opts.use_u2net and model is not None:
        pred = model.predict(bgr)
        region = _largest_component(pred > 0.5)
        region = _fill_holes(region)
        region = cv2.dilate(region.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        if region.sum() < 0.05 * h * w:
            warnings.append("主体识别失败，已改为整图分析")
            region = np.ones((h, w), bool)
    else:
        region = np.ones((h, w), bool)

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(A - 128.0, B - 128.0)
    shirt = _detect_shirt(L, chroma, region, opts.shirt_color)
    if opts.use_u2net and model is not None:
        expanded = _expand_to_garment(region, L, chroma, shirt)
        if expanded.sum() > region.sum():
            region = expanded
            shirt = _detect_shirt(L, chroma, region, opts.shirt_color)

    fabric = _fabric_seed(L, chroma, region, shirt)
    if fabric.sum() < 0.03 * region.sum():
        warnings.append(f"未找到足够的{'黑' if shirt == 'black' else '白'}色布料，请确认衣服颜色设置")

    alpha, bg_l, a0, b0 = _soft_alpha(L, A, B, fabric, region, opts.sensitivity, size)
    fabric = region & (alpha < 0.15)
    alpha, bg_l, a0, b0 = _soft_alpha(L, A, B, fabric, region, opts.sensitivity, size)

    hard = alpha > 0.5
    raw_hard = hard.copy()
    if opts.enclosed_only:
        enclosed = _enclosed_mask(region & ~hard)
        hard &= enclosed
    hard = _drop_wrinkles(hard, L, chroma, size, opts.sensitivity)
    hard = _clean_components(hard, size, opts.remove_small)
    hard = _restore_details(hard, alpha, region, size)

    keep = cv2.dilate(hard.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    alpha = alpha * keep

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    radius = 1 + int(opts.feather)
    alpha = np.clip(_guided_filter(gray, alpha, radius, 1e-3 / (1 + opts.feather)), 0, 1) * keep
    alpha[alpha < 0.04] = 0.0
    alpha[alpha > 0.96] = 1.0

    bg_lab = np.dstack([bg_l, np.full_like(bg_l, a0), np.full_like(bg_l, b0)])
    bg_bgr = cv2.cvtColor(np.clip(bg_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR).astype(np.float32)
    img = bgr.astype(np.float32)
    a3 = alpha[..., None]
    fg = np.where(a3 > 0.05, (img - (1 - a3) * bg_bgr) / np.maximum(a3, 0.05), img)
    fg = np.clip(fg, 0, 255)

    rgba = np.dstack([fg, alpha * 255.0]).astype(np.uint8)

    confidence = 1.0
    missed = _missed_print_ratio(raw_hard, hard, region, size)
    if missed > 0.4:
        warnings.append(f"约 {missed:.0%} 的图案未被导出，可能漏抠，建议改用 Google AI")
        confidence -= 0.6 if missed > 0.7 else 0.4
    covered = float(alpha.sum())
    if covered < 0.0015 * region.sum():
        warnings.append("未检测到明显印花")
        confidence -= 0.6
    else:
        soft = (alpha > 0.05) & (alpha < 0.85)
        ambiguity = float(soft.sum()) / max(float((alpha > 0.05).sum()), 1.0)
        if ambiguity > 0.6:
            warnings.append("印花边缘模糊，建议改用 Google AI")
            confidence -= 0.3
        ys, xs = np.nonzero(hard)
        if ys.size:
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            sharpness = _sharpness_score(gray[y0:y1, x0:x1] * 255.0, hard[y0:y1, x0:x1])
            if 0 <= sharpness < SHARPNESS_MIN:
                warnings.append(f"原图不清晰（清晰度 {sharpness:.2f}），建议改用 Google AI")
                confidence -= 0.35
            inner_fabric = fabric[y0:y1, x0:x1] & _fill_holes(hard[y0:y1, x0:x1])
            if inner_fabric.sum() > 0.3 * max(hard[y0:y1, x0:x1].sum(), 1):
                tone = "白" if shirt == "white" else "黑"
                warnings.append(f"印花内部有大面积{tone}色，可能是印花本身的{tone}色部分，请人工核对")
                confidence -= 0.2

    return ExtractResult(rgba=rgba, confidence=max(confidence, 0.0), shirt_color=shirt, warnings=warnings)


# ---------- Google AI 遮罩 + 原图像素（掩码分离法，颜色 100% 来自原图） ----------


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / max(float(union), 1.0)


def _align_mask(mask: np.ndarray, ref_alpha: np.ndarray) -> np.ndarray:
    """AI 生成的遮罩可能有几个像素的偏移/缩放，用本地结果做参考微调对齐，只在明显更贴合时采用。"""
    h, w = mask.shape
    s = 384.0 / max(h, w)
    size = (max(8, round(w * s)), max(8, round(h * s)))
    a = cv2.GaussianBlur(cv2.resize(mask, size, interpolation=cv2.INTER_AREA), (0, 0), 1.5)
    r = cv2.GaussianBlur(cv2.resize(ref_alpha.astype(np.float32) / 255.0, size, interpolation=cv2.INTER_AREA), (0, 0), 1.5)
    if (r > 0.5).sum() < 50 or (a > 0.5).sum() < 50:
        return mask
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(
            r, a, warp, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5), None, 5
        )
    except cv2.error:
        return mask
    det = float(np.linalg.det(warp[:, :2]))
    if not 0.85 < det < 1.18:
        return mask
    warp[:, 2] /= s
    aligned = cv2.warpAffine(mask, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    ref = ref_alpha > 127
    if _mask_iou(aligned > 0.5, ref) > _mask_iou(mask > 0.5, ref) + 0.01:
        return aligned
    return mask


def cutout_to_mask(img: np.ndarray, key_bgr: tuple[int, int, int]) -> np.ndarray:
    """从 AI 抠好的图里只取轮廓（0-255 遮罩），丢弃它的颜色。带透明通道就直接用 Alpha，否则按抠像底色反推。"""
    if img.ndim == 3 and img.shape[2] == 4 and img[..., 3].min() < 250:
        return img[..., 3].copy()
    rgb = img[..., :3] if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    lab = cv2.cvtColor(rgb, cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    key_lab = cv2.cvtColor(np.uint8([[key_bgr]]), cv2.COLOR_BGR2LAB).reshape(3).astype(np.float32)
    near_key = border[np.linalg.norm(border - key_lab, axis=1) < 60]
    ref = np.median(near_key, axis=0) if len(near_key) > 20 else key_lab
    dist = np.linalg.norm(lab - ref, axis=2)
    dist = cv2.medianBlur(dist.astype(np.float32), 3)
    lo, hi = 18.0, 45.0
    return (np.clip((dist - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


def apply_ai_mask(
    bgr: np.ndarray, mask_gray: np.ndarray, shirt: str, opts: ExtractOptions, ref_alpha: np.ndarray | None = None
) -> ExtractResult:
    """掩码分离法：AI 的结果只当轮廓遮罩，按原图尺寸 Lanczos 对齐后与原图 RGB 直接拼成 RGBA，颜色 100% 来自原图。"""
    h, w = bgr.shape[:2]
    size = max(h, w)
    warnings: list[str] = []
    m = np.clip(cv2.resize(mask_gray.astype(np.float32) / 255.0, (w, h), interpolation=cv2.INTER_LANCZOS4), 0, 1)
    if ref_alpha is not None:
        m = _align_mask(m, ref_alpha)
    hard = m > 0.5
    if hard.sum() < 0.0005 * h * w:
        empty = np.zeros((h, w, 4), np.uint8)
        return ExtractResult(rgba=empty, confidence=0.2, shirt_color=shirt, warnings=["Google AI 未识别到印花"])

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(A - 128.0, B - 128.0)
    everywhere = np.ones((h, w), bool)
    shirt = shirt if shirt in ("black", "white") else _detect_shirt(L, chroma, everywhere, opts.shirt_color)

    edge = np.zeros((h, w), bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    unkeyed = hard[edge].mean() > 0.5
    if unkeyed:
        # AI 没把背景换成抠像底色（几乎原样返回）：按照片边缘的背景色把与边缘相连的背景先去掉
        ref = np.median(lab[edge], axis=0)
        similar = (np.linalg.norm(lab - ref, axis=2) < 25).astype(np.uint8)
        n_bg, bg_labels = cv2.connectedComponents(similar, connectivity=8)
        ids = np.unique(bg_labels[edge & (similar > 0)])
        hard &= ~np.isin(bg_labels, ids[ids > 0])
        hard = cv2.morphologyEx(hard.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    hard = _drop_thin_strays(hard, size, opts.remove_small)
    hard, garment_ratio = _strip_garment(hard, L, chroma, shirt, size)
    if unkeyed:
        garment_ratio = max(garment_ratio, 1.0 - float(hard.sum()) / max(float((m > 0.5).sum()), 1.0))
    if not hard.any():
        empty = np.zeros((h, w, 4), np.uint8)
        return ExtractResult(rgba=empty, confidence=0.2, shirt_color=shirt, warnings=["Google AI 未识别到印花"])

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    radius = 1 + int(opts.feather)
    if garment_ratio > 0:
        warnings.append(f"AI 把整件衣服也抠了进来，已自动剔除衣服布料/背景（{garment_ratio:.0%}），请核对印花是否完整")
        # 剔除衣服后边缘紧贴布料，只留 1 像素余量，边缘按与布料的色差柔化，避免留下黑边
        zone = cv2.dilate(hard.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        alpha = m * zone
        ring = (cv2.dilate(hard.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0) & ~zone
        fabric = _fabric_seed(L, chroma, ring, shirt)
        if fabric.sum() > 200:
            diff, _, _, _ = _soft_alpha(L, A, B, fabric, zone, opts.sensitivity, size)
            diff = np.clip(_guided_filter(gray, diff, radius, 1e-3), 0, 1)
            band = zone & ~(cv2.erode(hard.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
            alpha[band] = np.minimum(alpha, diff)[band]
        alpha[alpha < 0.04] = 0.0
        alpha[alpha > 0.96] = 1.0
        rgba = np.dstack([bgr, (alpha * 255.0).astype(np.uint8)])
        return ExtractResult(rgba=rgba, confidence=0.7, shirt_color=shirt, warnings=warnings, garment_ratio=garment_ratio)

    k = max(5, int(size * 0.01)) | 1
    ellipse = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    zone = cv2.dilate(hard.astype(np.uint8), ellipse) > 0
    # 只用去掉杂线后的遮罩本身当透明度，不再做导向滤波/腐蚀等二次加工，避免把条纹、白毛挖出斑块
    alpha = m * zone

    if opts.knockout_fabric:
        ring = (cv2.dilate(hard.astype(np.uint8), ellipse, iterations=4) > 0) & ~zone
        fabric = _fabric_seed(L, chroma, ring, shirt)
        if fabric.sum() < 200:
            fabric = _fabric_seed(L, chroma, ~zone, shirt)
        diff, _, _, _ = _soft_alpha(L, A, B, fabric, zone, opts.sensitivity, size)
        diff = np.clip(_guided_filter(gray, diff, radius, 1e-3), 0, 1)
        alpha = np.minimum(alpha, diff)

    alpha[alpha < 0.04] = 0.0
    alpha[alpha > 0.96] = 1.0
    rgba = np.dstack([bgr, (alpha * 255.0).astype(np.uint8)])
    return ExtractResult(rgba=rgba, confidence=0.9, shirt_color=shirt, warnings=warnings)


GARMENT_RATIO = 0.25


def _strip_garment(hard: np.ndarray, L: np.ndarray, chroma: np.ndarray, shirt: str, size: int) -> tuple[np.ndarray, float]:
    """AI 有时把整件 T 恤（甚至衣架、背景）都当成印花保留。

    衣服布料是一大片与遮罩外部相连的黑/白纯色；印花里的黑色条纹被印花颜色包围，面积小。
    只有剔除比例明显（整件衣服的情况）才生效，正常的印花遮罩原样返回。
    """
    h, w = hard.shape
    total = int(hard.sum())
    if total == 0:
        return hard, 0.0
    k = max(3, int(size * 0.004)) | 1
    fabric = _fabric_seed(L, chroma, np.ones_like(hard), shirt)
    fabric = cv2.morphologyEx(fabric.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    cand = hard & fabric
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), connectivity=8)
    if n <= 1:
        return hard, 0.0
    edge = np.zeros((h, w), bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    outside = (cv2.dilate((~hard).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) | edge
    drop = np.zeros(n, bool)
    drop[np.unique(labels[outside & cand])] = True
    drop &= stats[:, cv2.CC_STAT_AREA] > 0.03 * total
    drop[0] = False
    kept = hard & ~drop[labels]

    # 剔除衣服后，与图片边缘相连的剩余部分就是背景/衣架/模特，一并去掉
    n2, labels2 = cv2.connectedComponents(kept.astype(np.uint8), connectivity=8)
    border_ids = np.unique(labels2[edge])
    kept &= ~np.isin(labels2, border_ids[border_ids > 0])
    kept = cv2.morphologyEx(kept.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    kept = _clean_components(kept, size, True)
    kept = _keep_enclosed_by_garment(kept, drop[labels], size)

    ratio = 1.0 - float(kept.sum()) / total
    if ratio < GARMENT_RATIO or not kept.any():
        return hard, 0.0
    return kept, ratio


ENCLOSED_RATIO = 0.75


def _keep_enclosed_by_garment(kept: np.ndarray, garment: np.ndarray, size: int) -> np.ndarray:
    """印花印在衣服正面，四周一圈全是布料；衣架、手、领口外的杂物只有一侧挨着衣服，另一侧是背景。

    逐块检查外围一圈有多少是衣服布料，不够的整块去掉。全部不达标时退回保留最大块，避免空图。
    """
    if not kept.any() or not garment.any():
        return kept
    n, labels, stats, _ = cv2.connectedComponentsWithStats(kept.astype(np.uint8), connectivity=8)
    if n <= 1:
        return kept
    pad = max(5, int(size * 0.015))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1, 2 * pad + 1))
    h, w = kept.shape
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, bw, bh = stats[i, :4]
        x0, y0 = max(0, x - pad - 1), max(0, y - pad - 1)
        x1, y1 = min(w, x + bw + pad + 1), min(h, y + bh + pad + 1)
        comp = labels[y0:y1, x0:x1] == i
        ring = (cv2.dilate(comp.astype(np.uint8), kernel) > 0) & ~_fill_holes(comp) & ~kept[y0:y1, x0:x1]
        if not ring.any():
            continue
        keep[i] = garment[y0:y1, x0:x1][ring].mean() >= ENCLOSED_RATIO
    if not keep[1:].any():
        keep[1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))] = True
    return keep[labels]


def _drop_thin_strays(hard: np.ndarray, size: int, remove_small: bool) -> np.ndarray:
    """去掉 AI 遮罩里与主体不相连的细线（如衣服轮廓线）和小碎块，主体上的胡须等细节保留。"""
    k = max(3, int(size * 0.006)) | 1
    core = cv2.morphologyEx(hard.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    core = _clean_components(core, size, remove_small)
    if not core.any():
        return hard
    n, labels = cv2.connectedComponents(hard.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[np.unique(labels[core])] = True
    keep[0] = False
    return keep[labels]


def _crop_alpha(alpha: np.ndarray) -> np.ndarray | None:
    ys, xs = np.nonzero(alpha > 20)
    if ys.size == 0:
        return None
    return alpha[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """比较两个印花的形状一致度（0-1），用于发现 AI 改动/脑补。"""
    ca, cb = _crop_alpha(a[..., 3]), _crop_alpha(b[..., 3])
    if ca is None or cb is None:
        return 0.0
    ra, rb = ca.shape[1] / ca.shape[0], cb.shape[1] / cb.shape[0]
    ratio_score = min(ra, rb) / max(ra, rb)
    sa = cv2.resize(ca, (192, 192), interpolation=cv2.INTER_AREA) > 100
    sb = cv2.resize(cb, (192, 192), interpolation=cv2.INTER_AREA) > 100
    ka = cv2.dilate(sa.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    kb = cv2.dilate(sb.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    inter = (ka & kb).sum()
    union = (ka | kb).sum()
    iou = inter / max(union, 1)
    return float(0.35 * ratio_score + 0.65 * iou)
