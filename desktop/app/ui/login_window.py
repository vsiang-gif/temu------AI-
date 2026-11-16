from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .. import config
from ..license_client import LicenseError, LicenseSession, NetworkError, load_saved_code, save_code


class LoginWindow(QDialog):
    finished_login = Signal(object, str)  # session, error message

    def __init__(self, auto_login: bool = True):
        super().__init__()
        self.session: LicenseSession | None = None
        self.setWindowTitle(f"{config.APP_NAME} - 登录")
        self.setFixedWidth(420)

        try:
            self._session = LicenseSession()
            config_error = ""
        except LicenseError as exc:
            self._session = None
            config_error = exc.message

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        panel = QFrame(objectName="Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        root.addWidget(panel)

        layout.addWidget(QLabel(config.APP_NAME, objectName="Title"))
        layout.addWidget(QLabel("请输入卡密登录使用", objectName="Muted"))

        self.code_input = QLineEdit(placeholderText="XXXX-XXXX-XXXX-XXXX")
        self.code_input.setText(load_saved_code())
        self.code_input.returnPressed.connect(self.login)
        layout.addWidget(self.code_input)

        self.remember = QCheckBox("记住卡密，下次自动登录")
        self.remember.setChecked(bool(self.code_input.text()))
        layout.addWidget(self.remember)

        self.error = QLabel(config_error, objectName="Error", wordWrap=True)
        layout.addWidget(self.error)

        self.button = QPushButton("登录", objectName="Primary")
        self.button.clicked.connect(self.login)
        self.button.setEnabled(self._session is not None)
        layout.addWidget(self.button)

        if self._session:
            row = QHBoxLayout()
            mid = self._session.machine_id
            row.addWidget(QLabel(f"本机识别码：{mid[:12]}…", objectName="Muted"))
            copy = QPushButton("复制")
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(mid))
            row.addStretch()
            row.addWidget(copy)
            layout.addLayout(row)

        layout.addWidget(QLabel(f"版本 {config.APP_VERSION}", objectName="Muted"), alignment=Qt.AlignRight)
        self.finished_login.connect(self._on_finished)

        if auto_login and self._session and self.code_input.text():
            self.login()

    def login(self):
        code = self.code_input.text().strip()
        if not code or not self._session:
            self.error.setText("请输入卡密")
            return
        self.button.setEnabled(False)
        self.button.setText("登录中…")
        self.error.setText("")

        def worker():
            try:
                self._session.activate(code)
                self.finished_login.emit(self._session, "")
            except (LicenseError, NetworkError) as exc:
                self.finished_login.emit(None, getattr(exc, "message", str(exc)))
            except Exception as exc:
                self.finished_login.emit(None, f"登录失败：{exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_finished(self, session, message: str):
        self.button.setEnabled(True)
        self.button.setText("登录")
        if session is None:
            self.error.setText(message)
            return
        save_code(self.code_input.text().strip() if self.remember.isChecked() else "")
        self.session = session
        self.accept()
