"""전연결기(jeonnector) 애플리케이션 실행 진입점."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from jeonnector.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("전연결기 (jeonnector)")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
