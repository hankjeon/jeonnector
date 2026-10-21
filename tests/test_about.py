"""도움말 정보 창, 창 제목, 프로그램 아이콘 검증."""

from PySide6.QtWidgets import QLabel

from jeonnector import __version__
from jeonnector.storage import PartLibrary
from jeonnector.ui.about_dialog import AboutDialog
from jeonnector.ui.app_icon import ICON_SIZES, app_icon, icon_pixmap
from jeonnector.ui.main_window import MainWindow


def test_about_dialog_shows_product_texts_and_version(qtbot):
    dialog = AboutDialog()
    qtbot.addWidget(dialog)
    texts = [label.text() for label in dialog.findChildren(QLabel) if label.text()]
    assert texts == ["연결기 핀맵 뷰어", "JEONNECTOR", "전연결기", "I am connector.", f"버전 {__version__}"]
    assert dialog.windowTitle() == "전연결기 정보"
    assert any(not label.pixmap().isNull() for label in dialog.findChildren(QLabel))
    assert dialog.minimumSize() == dialog.maximumSize()


def test_help_menu_and_window_title(qtbot, tmp_path, monkeypatch):
    window = MainWindow(PartLibrary(storage_path=tmp_path / "parts.json"))
    qtbot.addWidget(window)
    menus = [action.text() for action in window.menuBar().actions()]
    assert menus[-1] == "도움말(&H)"
    assert window.about_act.text() == "전연결기 정보(&A)…"
    shown = []
    monkeypatch.setattr(AboutDialog, "exec", lambda self: shown.append(self) or 0)
    window.about_act.trigger()
    assert len(shown) == 1
    assert window.windowTitle() == "JEONNECTOR 전연결기 - 새 프로젝트"
    window.mark_dirty(True)
    assert window.windowTitle() == "JEONNECTOR 전연결기 - 새 프로젝트 *"
    window.mark_dirty(False)


def test_app_icon_has_all_sizes_with_accent_pin():
    icon = app_icon()
    sizes = {size.width() for size in icon.availableSizes()}
    assert set(ICON_SIZES) <= sizes
    image = icon_pixmap(64).toImage()
    assert image.pixelColor(0, 0).alpha() == 0  # 모서리는 투명
    assert image.pixelColor(32, 19).name() == "#f59e0b"  # 맨 위 핀 강조
    assert image.pixelColor(32, 32).name() == "#f8fafc"  # 가운데 핀
