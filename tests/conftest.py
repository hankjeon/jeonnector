"""테스트 공통 설정."""

import os

# 단독 실행과 전체 실행이 같은 Qt 플랫폼(화면 없는 offscreen)에서 동작하도록 고정한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings

from jeonnector.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """사용자의 실제 설정(최근 파일, 창 배치)을 읽거나 덮어쓰지 않도록 임시 설정 파일을 쓴다."""
    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        MainWindow, "_settings", lambda self: QSettings(path, QSettings.Format.IniFormat)
    )
