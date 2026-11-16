"""单张图片的完整处理：本地 / Google AI / 智能 三种方式，输出与原文件同名的 PNG。"""

from __future__ import annotations

import base64
import os
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np

from .extractor import (
    ExtractOptions,
    ExtractResult,
    SaliencyModel,
    apply_ai_mask,
    cutout_to_mask,
    extract_local,
    read_image,
    similarity,
)
from .license_client import LicenseSession
from .local_session import KEY_COLORS, SUPPORTED_RATIOS, pick_key_color
from .output import OutputOptions, finalize, save_png

MODE_LOCAL = "local"
MODE_GEMINI = "gemini"
MODE_AUTO = "auto"


@dataclass
class JobOptions:
    mode: str = MODE_LOCAL
    extract: ExtractOptions = field(default_factory=ExtractOptions)
    output: OutputOptions = field(default_factory=OutputOptions)
    verify_ai: bool = True  # AI 结果与本地结果对比，发现改动
    auto_fallback: bool = True  # 本地可信度低于阈值时自动改用 Google AI
    auto_threshold: float = 0.8


@dataclass
class JobResult:
    ok: bool
    method: str
    confidence: float
    message: str
    output_path: str = ""
    needs_review: bool = False


def resource_dir() -> str:
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_model() -> str | None:
    candidates = []
    for base in {resource_dir(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}:
        folder = os.path.join(base, "models")
        for name in ("isnet-general-use.onnx", "u2net.onnx", "u2netp.onnx"):
            candidates.append(os.path.join(folder, name))
    return next((p for p in candidates if os.path.isfile(p)), None)


class Processor:
    def __init__(self, session: LicenseSession):
        self.session = session
        self._model: SaliencyModel | None = None
        self._model_error = ""
        self._model_loaded = False

    @property
    def model(self) -> SaliencyModel | None:
        if not self._model_loaded:
            self._model_loaded = True
            path = find_model()
            if path:
                try:
                    self._model = SaliencyModel(path)
                except Exception as exc:
                    self._model_error = f"模型加载失败：{exc}"
            else:
                self._model_error = "未找到 models/u2net.onnx，已使用纯颜色分析"
        return self._model

    @property
    def model_status(self) -> str:
        m = self.model
        return f"本地模型：{m.name}" if m else self._model_error

    def _gemini(
        self, bgr: np.ndarray, shirt: str, file_name: str, opts: ExtractOptions, ref_alpha: np.ndarray | None = None
    ) -> ExtractResult:
        first = self._gemini_once(bgr, shirt, file_name, opts, ref_alpha, strict=False)
        if first.garment_ratio <= 0:
            return first
        # AI 把整件衣服抠进来了：用更严格的提示词再要一次，取剔除得更少（更干净）的那次
        try:
            second = self._gemini_once(bgr, shirt, file_name, opts, ref_alpha, strict=True)
        except Exception:
            return first
        return second if second.garment_ratio < first.garment_ratio else first

    def _gemini_once(
        self, bgr: np.ndarray, shirt: str, file_name: str, opts: ExtractOptions,
        ref_alpha: np.ndarray | None, strict: bool,
    ) -> ExtractResult:
        h, w = bgr.shape[:2]
        scale = min(1.0, 1536 / max(h, w))
        small = cv2.resize(bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else bgr
        sh, sw = small.shape[:2]
        # 补边到 Google 支持的画幅比例，返回的遮罩才能与原图逐像素对齐
        aspect, target = min(SUPPORTED_RATIOS.items(), key=lambda kv: abs(np.log(kv[1] / (sw / sh))))
        pw, ph = (max(sw, round(sh * target)), sh) if sw / sh < target else (sw, max(sh, round(sw / target)))
        top, left = (ph - sh) // 2, (pw - sw) // 2
        fill = [int(v) for v in np.median(np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]]), axis=0)]
        padded = cv2.copyMakeBorder(small, top, ph - sh - top, left, pw - sw - left, cv2.BORDER_CONSTANT, value=fill)
        ok, buf = cv2.imencode(".jpg", padded, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise ValueError("图片编码失败")
        samples = bgr[ref_alpha > 127] if ref_alpha is not None and (ref_alpha > 127).sum() > 100 else bgr.reshape(-1, 3)
        samples = samples[:: max(1, len(samples) // 20000)]
        key = pick_key_color(samples)
        hx = KEY_COLORS[key]
        key_bgr = (int(hx[5:7], 16), int(hx[3:5], 16), int(hx[1:3], 16))
        data = self.session.gemini_cutout(
            base64.b64encode(buf.tobytes()).decode(), "image/jpeg", shirt, file_name, aspect, key, strict
        )
        cutout = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        if cutout is None:
            raise ValueError("Google AI 返回的图片无法解析")
        if cutout.dtype != np.uint8:
            cutout = (cutout / 257).astype(np.uint8)
        mask = cutout_to_mask(cutout, key_bgr)
        mask = cv2.resize(mask, (pw, ph), interpolation=cv2.INTER_LANCZOS4)[top : top + sh, left : left + sw]
        return apply_ai_mask(bgr, mask, shirt, opts, ref_alpha)

    def process(self, src: str, dst: str, opts: JobOptions) -> JobResult:
        self.session.ensure_valid()
        bgr = read_image(src)
        name = os.path.basename(src)
        notes: list[str] = []

        local: ExtractResult | None = None
        local = extract_local(bgr, opts.extract, self.model)

        fallback = opts.mode == MODE_AUTO or (opts.mode == MODE_LOCAL and opts.auto_fallback)
        use_ai = opts.mode == MODE_GEMINI or (
            fallback and local is not None and local.confidence < opts.auto_threshold
        )
        if use_ai and opts.mode != MODE_GEMINI and local is not None:
            notes.append(f"本地可信度 {local.confidence:.0%} 低于 {opts.auto_threshold:.0%}，已自动改用 Google AI")

        chosen = local
        method = "本地"
        if use_ai:
            if not self.session.gemini_enabled:
                if opts.mode == MODE_GEMINI:
                    raise PermissionError("Google AI 未开通（未填写 API Key）")
                notes[-1:] = [f"本地可信度 {local.confidence:.0%} 偏低，但 Google AI 未开通（未填 Key），使用本地结果"]
            else:
                shirt = local.shirt_color if local else opts.extract.shirt_color
                ref_alpha = local.rgba[..., 3] if local is not None and local.confidence > 0.3 else None
                try:
                    ai = self._gemini(bgr, shirt if shirt in ("black", "white") else "", name, opts.extract, ref_alpha)
                except Exception as exc:
                    if opts.mode == MODE_GEMINI or local is None:
                        raise
                    ai = None
                    notes.append(f"AI 失败，已用本地结果：{exc}")
                if ai is not None:
                    chosen, method = ai, "Google AI"
                    notes.append("颜色直接取自原图像素")
                    if local is not None and opts.verify_ai and local.confidence > 0.3:
                        score = similarity(ai.rgba, local.rgba)
                        if score < 0.5:
                            notes.append(f"AI 结果与原图印花差异较大（一致度 {score:.0%}），可能有改动，请核对")
                            ai.confidence = min(ai.confidence, 0.4)
                        else:
                            notes.append(f"与原图一致度 {score:.0%}")

        assert chosen is not None
        notes = chosen.warnings + notes
        final = finalize(chosen.rgba, opts.output)
        self.session.ensure_valid()
        save_png(final, dst, opts.output.dpi)
        needs_review = chosen.confidence < 0.6
        return JobResult(
            ok=True,
            method=method,
            confidence=chosen.confidence,
            message="；".join(notes) if notes else f"{final.shape[1]}×{final.shape[0]}",
            output_path=dst,
            needs_review=needs_review,
        )
