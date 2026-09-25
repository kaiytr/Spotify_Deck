"""아이콘 버튼 위젯.

QPushButton에 QSS를 씌우는 대신 직접 그린다.
호버/눌림/활성 상태의 색 전환을 애니메이션으로 부드럽게 처리하기 위해서다.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QEnterEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QWidget

from app.ui.icons import Icon, draw_icon
from app.ui.theme import Colors


class IconButton(QWidget):
    """아이콘 하나를 그리는 원형 버튼.

    `active` 속성으로 켜짐/꺼짐 상태를 표현한다 (셔플, 반복, 좋아요).
    """

    clicked = Signal()

    def __init__(
        self,
        icon: Icon,
        *,
        size: int = 40,
        icon_ratio: float = 0.55,
        color: str = Colors.TEXT_DIM,
        active_color: str = Colors.ACCENT,
        hover_color: str = Colors.TEXT,
        tooltip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon = icon
        self._base_size = size
        self._icon_ratio = icon_ratio

        self._color = QColor(color)
        self._active_color = QColor(active_color)
        self._hover_color = QColor(hover_color)

        self._active = False
        self._hovered = False
        self._pressed = False
        self._enabled_visual = True

        # 색 전환 애니메이션용 현재 색
        self._current = QColor(color)
        self._anim = QPropertyAnimation(self, b"iconColor", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if tooltip:
            self.setToolTip(tooltip)

    # -- 애니메이션 속성 ----------------------------------------------------

    def get_icon_color(self) -> QColor:
        return self._current

    def set_icon_color(self, color: QColor) -> None:
        self._current = color
        self.update()

    iconColor = Property(QColor, get_icon_color, set_icon_color)

    # -- 상태 ---------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    def set_accent(self, color: QColor) -> None:
        """켜짐 상태일 때 쓸 색을 앨범 강조색으로 바꾼다."""
        self._active_color = QColor(color)
        if self._active:
            self._animate_to(self._target_color())

    def set_active(self, value: bool) -> None:
        """켜짐 상태를 바꾼다 (셔플 on 등). 색이 부드럽게 전환된다."""
        if self._active == value:
            return
        self._active = value
        self._animate_to(self._target_color())

    def set_icon(self, icon: Icon) -> None:
        if self._icon is not icon:
            self._icon = icon
            self.update()

    def set_interactive(self, value: bool) -> None:
        """비활성화 시 회색으로 흐려지고 클릭을 받지 않는다."""
        if self._enabled_visual == value:
            return
        self._enabled_visual = value
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if value else Qt.CursorShape.ArrowCursor
        )
        self._animate_to(self._target_color())

    def _target_color(self) -> QColor:
        if not self._enabled_visual:
            return QColor(Colors.TEXT_MUTED)
        if self._active:
            return self._active_color
        if self._hovered:
            return self._hover_color
        return self._color

    def _animate_to(self, color: QColor) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._current)
        self._anim.setEndValue(color)
        self._anim.start()

    # -- 이벤트 -------------------------------------------------------------

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self._hovered = True
        self._animate_to(self._target_color())
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self._animate_to(self._target_color())
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._enabled_visual:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        was_pressed = self._pressed
        self._pressed = False
        self.update()
        if (
            was_pressed
            and self._enabled_visual
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()

    # -- 렌더링 -------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        side = min(self.width(), self.height()) * self._icon_ratio
        # 눌렀을 때 살짝 작아지는 피드백
        if self._pressed:
            side *= 0.9

        rect = QRectF(0, 0, side, side)
        rect.moveCenter(self.rect().center().toPointF())

        draw_icon(painter, self._icon, rect, self._current, stroke_width=2.0)
        painter.end()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._base_size, self._base_size)


class IconLabel(QWidget):
    """클릭할 수 없는 아이콘 표시용 위젯.

    로고처럼 '보여주기만' 하는 자리에 쓴다.
    IconButton을 쓰면 커서가 손가락으로 바뀌고 호버 효과가 생겨
    누를 수 있는 것처럼 오해하게 된다.
    """

    def __init__(
        self,
        icon: Icon,
        *,
        size: int = 24,
        color: str = Colors.ACCENT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon = icon
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_color(self, color: QColor) -> None:
        if color.rgb() != self._color.rgb():
            self._color = QColor(color)
            self.update()

    def set_icon(self, icon: Icon) -> None:
        if self._icon is not icon:
            self._icon = icon
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_icon(painter, self._icon, QRectF(self.rect()), self._color)
        painter.end()


class PlayButton(IconButton):
    """가운데 재생/일시정지 버튼.

    초록 원형 배경을 가진 주 버튼. 다른 버튼보다 크고 눈에 띄어야 한다.
    """

    def __init__(self, *, size: int = 64, parent: QWidget | None = None) -> None:
        super().__init__(
            Icon.PLAY,
            size=size,
            icon_ratio=0.46,
            color="#000000",
            hover_color="#000000",
            active_color="#000000",
            tooltip="재생 / 일시정지  (Space)",
            parent=parent,
        )
        self._playing = False
        self._circle = QColor(Colors.ACCENT)
        self._circle_hover = QColor(Colors.ACCENT_HI)

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        self.set_icon(Icon.PAUSE if playing else Icon.PLAY)

    def set_accent(self, color: QColor, hover: QColor | None = None) -> None:
        """원형 배경색을 앨범 강조색으로 바꾼다.

        아이콘은 계속 검정이므로, 배경이 충분히 밝아야 대비가 유지된다.
        (palette.py가 명도 하한을 보장한다)
        """
        self._circle = QColor(color)
        self._circle_hover = QColor(hover) if hover is not None else QColor(color).lighter(115)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 원형 배경
        if not self._enabled_visual:
            bg = QColor(Colors.SURFACE_HI)
        elif self._hovered:
            bg = self._circle_hover
        else:
            bg = self._circle

        inset = 2.0 if self._pressed else 0.0
        circle = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawEllipse(circle)

        # 아이콘
        side = circle.width() * self._icon_ratio
        rect = QRectF(0, 0, side, side)
        rect.moveCenter(circle.center())

        # 재생 삼각형은 시각적 무게중심이 왼쪽에 쏠려 보이므로 살짝 오른쪽으로 민다.
        if not self._playing:
            rect.translate(side * 0.06, 0)

        icon_color = QColor("#000000") if self._enabled_visual else QColor(Colors.TEXT_MUTED)
        draw_icon(painter, self._icon, rect, icon_color)
        painter.end()
