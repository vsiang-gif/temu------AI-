"""免卡密模式：不连授权服务器，Google AI 直接用本机填写的 API Key 调用。"""

from __future__ import annotations

import base64
import time

import requests

from . import config
from .license_client import LicenseError


SUPPORTED_RATIOS = {
    "1:1": 1.0, "2:3": 2 / 3, "3:2": 3 / 2, "3:4": 3 / 4, "4:3": 4 / 3,
    "4:5": 4 / 5, "5:4": 5 / 4, "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9,
}


KEY_COLORS = {"magenta": "#FF00FF", "green": "#00FF00", "blue": "#0000FF"}


def build_cutout_prompt(shirt: str, key: str, strict: bool = False) -> str:
    """让 AI 做它擅长的“抠图”，程序只取它的轮廓当遮罩，颜色像素一律来自原图（掩码分离法）。"""
    hex_color = KEY_COLORS.get(key, KEY_COLORS["magenta"])
    parts = [
        "Context: we are a Temu print-on-demand seller of plain black and white T-shirts.",
        "We need ONLY the printed artwork from this photo, so we can print it again onto blank T-shirts in our factory.",
        "The T-shirt itself is the blank garment and is NOT part of the artwork.",
        f"This is a product photo of a {shirt} T-shirt with a printed graphic on the chest.",
        "Task: extract only the complete printed graphic (every part of the design: all text, lines, details).",
        "Strictly keep the original pixel colors, grayscale and vintage/distressed texture of the print;",
        "no AI redrawing, no color shift, no hue adjustment, no filter enhancement.",
        f"Paint EVERYTHING that is not the print with flat solid pure {key} ({hex_color}), including:",
        "the whole T-shirt body, sleeves, collar, neckline, seams, hem, wrinkles, folds and shadows;",
        "the plain fabric between and around the design and fabric showing through gaps inside it;",
        "neck labels, tags, hangers, mannequins, models, hands, props and the entire background.",
        f"The shirt outline must NOT appear: the result must not look like a T-shirt on a {key} background,",
        "it must look like only the artwork floating on a flat key color.",
        "No gradient, no checkerboard, no texture, no shadow, no border.",
        "Keep exactly the same framing, aspect ratio, position and size as the input photo:",
        "do not crop, zoom, shift, rotate, flatten, center or redraw anything.",
        "Output a single image.",
    ]
    if strict:
        parts.insert(0, "IMPORTANT: a previous attempt wrongly kept the whole T-shirt. Remove the entire shirt this time; keep only the print.")
    return " ".join(parts)


def pick_key_color(bgr_samples) -> str:
    """选一个与印花颜色差距最大的抠像底色，避免底色和印花撞色。"""
    import cv2
    import numpy as np

    if bgr_samples is None or len(bgr_samples) == 0:
        return "magenta"
    pix = np.asarray(bgr_samples, np.uint8).reshape(-1, 1, 3)
    lab = cv2.cvtColor(pix, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    best, best_score = "magenta", -1.0
    for name, hx in KEY_COLORS.items():
        r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
        k = cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2LAB).reshape(3).astype(np.float32)
        score = float(np.percentile(np.linalg.norm(lab - k, axis=1), 1))
        if score > best_score:
            best, best_score = name, score
    return best


class LocalSession:
    """与 LicenseSession 接口一致，供主窗口和处理流程直接替换使用。"""

    token = "local"
    expires_at = None
    notice = ""
    latest_version = ""
    heartbeat_seconds = 3600
    is_local = True

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key.strip()
        self.model = model.strip() or config.GEMINI_MODEL

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.api_key)

    def set_api_key(self, key: str, model: str = "") -> None:
        self.api_key = key.strip()
        if model.strip():
            self.model = model.strip()

    def heartbeat(self) -> None:
        return

    def ensure_valid(self) -> None:
        return

    def server_now(self) -> float:
        return time.time()

    def gemini_cutout(
        self, image_b64: str, mime: str, shirt: str, file_name: str, aspect: str = "", key: str = "magenta",
        strict: bool = False,
    ) -> bytes:
        if not self.api_key:
            raise PermissionError("未填写 Google API Key")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        generation: dict = {"responseModalities": ["IMAGE"]}
        if aspect in SUPPORTED_RATIOS and "image" in self.model:
            generation["imageConfig"] = {"aspectRatio": aspect}
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": build_cutout_prompt(shirt or "black or white", key, strict)},
                        {"inline_data": {"mime_type": mime, "data": image_b64}},
                    ]
                }
            ],
            "generationConfig": generation,
        }
        proxies = {"https": config.HTTPS_PROXY, "http": config.HTTPS_PROXY} if config.HTTPS_PROXY else None
        try:
            resp = requests.post(
                url,
                json=body,
                headers={"x-goog-api-key": self.api_key},
                timeout=150,
                proxies=proxies,
            )
        except requests.RequestException as exc:
            raise ConnectionError("无法连接 Google AI，请检查网络或代理设置") from exc
        if resp.status_code in (400, 401, 403) and "API key" in resp.text:
            raise LicenseError("gemini_key", "Google API Key 无效")
        if resp.status_code == 429:
            raise RuntimeError("Google AI 配额已用完：免费层不含图片模型额度，请在 AI Studio 为该项目开启结算（Billing）")
        if not resp.ok:
            raise RuntimeError(f"Google AI 调用失败（{resp.status_code}）：{resp.text[:200]}")
        parts = (resp.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        for p in parts:
            data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
            if data:
                return base64.b64decode(data)
        raise RuntimeError("Google AI 未返回图片，请重试或改用本地模型")
