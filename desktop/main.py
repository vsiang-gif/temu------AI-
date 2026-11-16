import sys

from PySide6.QtWidgets import QApplication, QDialog

from app import config
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow
from app.ui.style import STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)

    state = {"window": None, "auto": True}

    def show_login():
        login = LoginWindow(auto_login=state["auto"])
        state["auto"] = False
        if login.exec() != QDialog.Accepted or login.session is None:
            app.quit()
            return
        window = MainWindow(login.session)
        window.logout_requested.connect(lambda _msg: show_login_later())
        window.destroyed.connect(lambda: None)
        state["window"] = window
        window.show()

        def on_close(event, original=window.closeEvent):
            original(event)
            if event.isAccepted() and not window._closing_for_logout:
                app.quit()

        window.closeEvent = on_close

    def show_login_later():
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, show_login)

    if config.LICENSE_ENABLED:
        show_login()
    else:
        from PySide6.QtCore import QSettings

        from app.local_session import LocalSession

        s = QSettings("TemuPrintExtractor", "Desktop")
        session = LocalSession(str(s.value("gemini_key", "")), str(s.value("gemini_model", "")))
        window = MainWindow(session)
        state["window"] = window
        app.setQuitOnLastWindowClosed(True)
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
