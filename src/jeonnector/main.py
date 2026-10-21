"""전연결기(jeonnector) 애플리케이션 실행 진입점."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from jeonnector.ui.about_dialog import APP_TITLE
from jeonnector.ui.app_icon import app_icon
from jeonnector.ui.main_window import MainWindow

WINDOWS_APP_ID = "Jeonnector.Jeonnector"


def _set_windows_app_id() -> None:
    """python.exe로 실행해도 작업 표시줄에 파이썬 대신 프로그램 아이콘이 보이도록 고유 ID를 알린다."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)


def main(argv: list[str] | None = None) -> int:
    _set_windows_app_id()
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
