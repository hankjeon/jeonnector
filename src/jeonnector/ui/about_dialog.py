"""도움말 → 전연결기 정보 대화창."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from jeonnector import __version__
from jeonnector.ui.app_icon import icon_pixmap

APP_TITLE = "JEONNECTOR 전연결기"


class AboutDialog(QDialog):
    """아이콘, 소개 문구, 제품명과 버전을 가운데 정렬로 보여 주는 고정 크기 창."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("전연결기 정보")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 20)
        layout.setSpacing(6)

        icon = QLabel()
        icon.setPixmap(icon_pixmap(64))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addSpacing(6)
        self._add_label(layout, "연결기 핀맵 뷰어", 10, color="#475569")
        self._add_label(layout, "JEONNECTOR", 24, bold=True)
        self._add_label(layout, "전연결기", 15)
        self._add_label(layout, "I am connector.", 11, italic=True, color="#334155")
        layout.addSpacing(10)
        self._add_label(layout, f"버전 {__version__}", 9, color="#94a3b8")
        layout.addSpacing(8)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        buttons.setCenterButtons(True)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.setFixedSize(self.sizeHint())

    @staticmethod
    def _add_label(
        layout: QVBoxLayout, text: str, point_size: float,
        bold: bool = False, italic: bool = False, color: str = "",
    ) -> None:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = label.font()
        font.setPointSizeF(point_size)
        font.setBold(bold)
        font.setItalic(italic)
        label.setFont(font)
        if color:
            label.setStyleSheet(f"color: {color};")
        layout.addWidget(label)
