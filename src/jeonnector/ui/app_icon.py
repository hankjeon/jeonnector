"""프로그램 아이콘: 원형 연결기와 강조한 핀 하나를 코드로 그린다 (그림 파일 없음)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

SHELL_COLOR = QColor("#1e3a8a")
RING_COLOR = QColor("#cbd5e1")
FACE_COLOR = QColor("#1e40af")
PIN_COLOR = QColor("#f8fafc")
ACCENT_COLOR = QColor("#f59e0b")


def icon_pixmap(size: int) -> QPixmap:
    """size×size 크기의 아이콘 그림. 바깥 쉘·링·면, 위쪽 키, 가운데와 둘레 여섯 핀(맨 위 핀 강조)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    s = float(size)
    center = QPointF(s / 2, s / 2)
    for color, radius in ((SHELL_COLOR, 0.46), (RING_COLOR, 0.38), (FACE_COLOR, 0.34)):
        painter.setBrush(color)
        painter.drawEllipse(center, s * radius, s * radius)
    painter.setBrush(SHELL_COLOR)
    painter.drawRect(QRectF(s * 0.46, s * 0.04, s * 0.08, s * 0.14))
    pins = [center] + [
        QPointF(center.x() + s * 0.20 * math.cos(angle), center.y() + s * 0.20 * math.sin(angle))
        for angle in (math.radians(-90 + 60 * k) for k in range(6))
    ]
    for index, pin in enumerate(pins):
        painter.setBrush(ACCENT_COLOR if index == 1 else PIN_COLOR)
        painter.drawEllipse(pin, s * 0.055, s * 0.055)
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """제목 표시줄·작업 표시줄용으로 여러 크기를 담은 아이콘."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(icon_pixmap(size))
    return icon
