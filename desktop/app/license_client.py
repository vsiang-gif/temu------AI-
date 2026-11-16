"""卡密登录、心跳与 Google AI 中转调用。所有授权响应都用 Ed25519 验签并校验随机数，防伪造、防重放。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import threading
import time
import uuid

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import config


class LicenseError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NetworkError(Exception):
    pass


def _windows_ids() -> list[str]:
    ids: list[str] = []
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        ids.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
    except OSError:
        pass
    try:
        import ctypes

        serial = ctypes.c_uint32()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(os.environ.get("SystemDrive", "C:") + "\\"),
            None, 0, ctypes.byref(serial), None, None, None, 0,
        )
        if ok:
            ids.append(f"{serial.value:08X}")
    except Exception:
        pass
    return ids


def machine_id() -> str:
    parts = _windows_ids() if os.name == "nt" else []
    if not parts:
        parts.append(str(uuid.getnode()))
    parts.append(platform.machine())
    return hashlib.sha256(("TPE|" + "|".join(parts)).encode()).hexdigest()


def machine_name() -> str:
    return (platform.node() or "unknown")[:100]


def _appdata_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = os.path.join(base, "TemuPrintExtractor")
    os.makedirs(path, exist_ok=True)
    return path


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def load_saved_code() -> str:
    try:
        with open(os.path.join(_appdata_dir(), "auth.dat"), "rb") as f:
            raw = base64.b64decode(f.read())
        return _xor(raw, machine_id().encode()).decode()
    except Exception:
        return ""


def save_code(code: str) -> None:
    path = os.path.join(_appdata_dir(), "auth.dat")
    if not code:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "wb") as f:
        f.write(base64.b64encode(_xor(code.encode(), machine_id().encode())))


class LicenseSession:
    def __init__(self):
        try:
            self._public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(config.PUBLIC_KEY_B64))
        except Exception as exc:
            raise LicenseError("bad_config", "软件配置错误：验签公钥无效，请联系管理员") from exc
        self.machine_id = machine_id()
        self.token = ""
        self.expires_at: int | None = None
        self.gemini_enabled = False
        self.notice = ""
        self.latest_version = ""
        self.heartbeat_seconds = 120
        self._last_ok = 0.0
        self._time_offset = 0.0
        self._locked_reason = ""
        self._lock = threading.Lock()

    # ----- 网络与验签 -----

    def _post(self, path: str, body: dict, require_signature: bool = True, timeout: float = 20) -> dict:
        nonce = secrets.token_hex(16)
        body = {**body, "nonce": nonce}
        url = config.SERVER_URL.rstrip("/") + path
        try:
            resp = requests.post(url, json=body, timeout=timeout)
        except requests.RequestException as exc:
            raise NetworkError("无法连接授权服务器，请检查网络") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise LicenseError("bad_response", f"服务器响应异常（{resp.status_code}）") from exc

        if isinstance(data, dict) and "payload" in data and "signature" in data:
            try:
                self._public_key.verify(base64.b64decode(data["signature"]), data["payload"].encode("utf-8"))
            except (InvalidSignature, ValueError) as exc:
                raise LicenseError("bad_signature", "授权服务器签名无效") from exc
            payload = json.loads(data["payload"])
        elif require_signature and data.get("ok"):
            raise LicenseError("bad_signature", "授权服务器签名无效")
        else:
            payload = data

        if payload.get("nonce") != nonce and payload.get("error") != "bad_request":
            raise LicenseError("bad_nonce", "授权响应校验失败")
        if not payload.get("ok"):
            raise LicenseError(payload.get("error", "error"), payload.get("message", "操作失败"))
        return payload

    def _apply_status(self, payload: dict) -> None:
        with self._lock:
            self.expires_at = payload.get("expires_at")
            self.gemini_enabled = bool(payload.get("gemini_enabled"))
            self.notice = payload.get("notice", "") or ""
            self.latest_version = payload.get("latest_version", "") or ""
            self.heartbeat_seconds = int(payload.get("heartbeat_seconds") or 120)
            self._time_offset = payload["server_time"] / 1000.0 - time.time()
            self._last_ok = time.monotonic()
            self._locked_reason = ""

    # ----- 对外接口 -----

    def activate(self, code: str) -> None:
        payload = self._post(
            "/api/client/activate",
            {"code": code.strip().upper(), "machine_id": self.machine_id, "machine_name": machine_name()},
        )
        self.token = payload["token"]
        self._apply_status(payload)

    def heartbeat(self) -> None:
        """服务器拒绝时抛 LicenseError；断网超过宽限期抛 LicenseError；短暂断网静默忽略。"""
        try:
            payload = self._post("/api/client/heartbeat", {"token": self.token, "machine_id": self.machine_id})
        except NetworkError:
            if time.monotonic() - self._last_ok > config.OFFLINE_GRACE_SECONDS:
                self.lock("断网时间过长，请联网后重新登录")
                raise LicenseError("offline", self._locked_reason)
            return
        except LicenseError as exc:
            self.lock(exc.message)
            raise
        self._apply_status(payload)

    def lock(self, reason: str) -> None:
        with self._lock:
            self._locked_reason = reason
            self.token = ""

    def ensure_valid(self) -> None:
        with self._lock:
            if self._locked_reason:
                raise LicenseError("locked", self._locked_reason)
            if not self.token:
                raise LicenseError("locked", "未登录")
            if time.monotonic() - self._last_ok > config.OFFLINE_GRACE_SECONDS + self.heartbeat_seconds:
                raise LicenseError("offline", "授权校验超时，请联网后重新登录")
            if self.expires_at and (time.time() + self._time_offset) * 1000 >= self.expires_at:
                raise LicenseError("expired", "卡密已到期")

    def server_now(self) -> float:
        return time.time() + self._time_offset

    def gemini_cutout(
        self, image_b64: str, mime: str, shirt: str, file_name: str, aspect: str = "", key: str = "magenta",
        strict: bool = False,
    ) -> bytes:
        self.ensure_valid()
        try:
            payload = self._post(
                "/api/client/gemini",
                {
                    "token": self.token,
                    "machine_id": self.machine_id,
                    "image_base64": image_b64,
                    "mime": mime,
                    "mode": "cutout",
                    "key": key,
                    "strict": strict,
                    "aspect": aspect,
                    "shirt": shirt,
                    "file_name": file_name,
                },
                require_signature=False,
                timeout=150,
            )
        except LicenseError as exc:
            if exc.code in ("session_invalid", "disabled", "expired", "service_closed"):
                self.lock(exc.message)
            raise
        return base64.b64decode(payload["image_base64"])
