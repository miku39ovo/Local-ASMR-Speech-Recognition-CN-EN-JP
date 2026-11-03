"""自定义进度条：空槽黄色，填充 0-30 白、31-99 蓝、100 全绿。

同时提供表格「进度」列的委托，让单元格里也能画同样的条。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QStyle, QStyledItemDelegate, QWidget

PROGRESS_ROLE = Qt.UserRole + 1

TRACK = QColor("#d8a52b")     # 空进度条：黄
C_WHITE = QColor("#f2f5fa")   # 1-30%
C_BLUE = QColor("#3f8ce8")    # 31-99%
C_GREEN = QColor("#43c07f")   # 100%
C_TEXT = QColor("#0f1319")

ROW_BG_A = QColor("#171a20")
ROW_BG_B = QColor("#1b1f26")
ROW_BG_SEL = QColor("#24344f")


def fill_color(pct: int) -> QColor | None:
    if pct <= 0:
        return None
    if pct >= 100:
        return C_GREEN
    if pct >= 31:
        return C_BLUE
    return C_WHITE


def paint_bar(
    painter: QPainter,
    rect: QRectF,
    pct: int,
    text: str = "",
    *,
    base_font: QFont | None = None,
) -> None:
    pct = max(0, min(100, int(pct)))
    r = QRectF(rect)
    if r.width() < 2 or r.height() < 2:
        return
    radius = min(5.0, r.height() / 2.0)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)

    track = QPainterPath()
    track.addRoundedRect(r, radius, radius)
    painter.fillPath(track, TRACK)

    color = fill_color(pct)
    if color is not None:
        w = r.width() * pct / 100.0
        if w > 0.6:
            painter.save()
            painter.setClipPath(track)
            painter.fillRect(QRectF(r.left(), r.top(), w, r.height()), color)
            painter.restore()

    if text:
        f = QFont(base_font or painter.font())
        f.setPixelSize(max(9, int(r.height()) - 5))
        f.setBold(True)
        painter.setFont(f)
        # 文字居中，低进度时压在黄色槽上、高进度时压在填充色上，统一用深色
        painter.setPen(C_TEXT)
        painter.drawText(r, Qt.AlignCenter, text)

    painter.restore()


class ProgressBar(QWidget):
    """状态栏用的进度条，文字画在条内。"""

    def __init__(self, parent=None, height: int = 17):
        super().__init__(parent)
        self._value = 0
        self._text_visible = True
        self.setFixedHeight(height)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802
        v = max(0, min(100, int(value)))
        if v != self._value:
            self._value = v
            self.update()

    def setTextVisible(self, visible: bool) -> None:  # noqa: N802
        self._text_visible = bool(visible)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, self.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(100, self.height())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        text = f"{self._value}%" if self._text_visible else ""
        paint_bar(painter, QRectF(self.rect()), self._value, text, base_font=self.font())
        painter.end()


class ProgressDelegate(QStyledItemDelegate):
    """表格「进度」列：画条 + 百分比文字。"""

    def __init__(self, parent=None, height: int = 16):
        super().__init__(parent)
        self._bar_h = height

    def paint(self, painter: QPainter, option, index) -> None:
        pct = index.data(PROGRESS_ROLE)
        if pct is None:
            super().paint(painter, option, index)
            return
        pct = int(pct)

        selected = bool(option.state & QStyle.State_Selected)
        bg = ROW_BG_SEL if selected else (ROW_BG_A if index.row() % 2 == 0 else ROW_BG_B)
        painter.save()
        painter.fillRect(option.rect, bg)

        rect = option.rect
        bar = QRectF(
            rect.left() + 7,
            rect.top() + (rect.height() - self._bar_h) / 2.0,
            max(20.0, rect.width() - 14.0),
            float(self._bar_h),
        )
        paint_bar(painter, bar, pct, f"{pct}%", base_font=option.font)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(92, 30)
