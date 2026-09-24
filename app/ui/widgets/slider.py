"""재생 진행률 / 볼륨 슬라이더.

QSlider 대신 직접 그린다. 이유:

  1. **드래그 중 값 튐 방지** — 1초마다 서버 값이 도착하는데 사용자가 드래그 중이면
     핸들이 손가락에서 벗어난다. 드래그 중에는 서버 갱신을 무시해야 한다.
  2. 트랙 전체를 클릭하면 그 지점으로 바로 이동 (QSlider 기본은 한 칸씩 이동).
  3. 터치 LCD 대비 — 히트 영역을 시각적 두께보다 넓게 잡아야 손가락으로 누를 수 있다.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.palette import AccentPalette
from app.ui.theme import Colors


class ProgressSlider(QWidget):
    """드래그 가능한 가로 슬라이더.

    Signals:
        seek_requested(int): 사용자가 드래그를 끝냈을 때 최종 값.
        value_preview(int):  드래그 중 실시간 값 (시간 표시 갱신용).
    """

    seek_requested = Signal(int)
    value_preview = Signal(int)

    def __init__(
        self,
        *,
        height: int = 20,
        track_height: float = 4.0,
        handle_radius: float = 6.0,
        always_show_handle: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._maximum = 0
        self._value = 0
        self._dragging = False
        self._hovered = False

        self._accent = AccentPalette.default()
        self._track_height = track_height
        self._handle_radius = handle_radius
        self._always_show_handle = always_show_handle

        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

    def set_accent(self, palette: AccentPalette) -> None:
        """앨범에서 뽑은 강조색으로 채움 색을 바꾼다."""
        self._accent = palette
        self.update()

    # -- 값 ------------------------------------------------------------------

    @property
    def is_dragging(self) -> bool:
        """드래그 중이면 서버 값으로 덮어쓰면 안 된다."""
        return self._dragging

    @property
    def value(self) -> int:
        return self._value

    @property
    def maximum(self) -> int:
        return self._maximum

    def set_range(self, maximum: int) -> None:
        if maximum != self._maximum:
            self._maximum = max(0, maximum)
            self._value = min(self._value, self._maximum)
            self.update()

    def set_value(self, value: int, *, force: bool = False) -> None:
        """값을 설정한다.

        Args:
            force: True면 드래그 중이어도 덮어쓴다 (곡이 바뀐 경우 등).
        """
        if self._dragging and not force:
            return
        value = max(0, min(int(value), self._maximum))
        if value != self._value:
            self._value = value
            self.update()

    @property
    def ratio(self) -> float:
        if self._maximum <= 0:
            return 0.0
        return self._value / self._maximum

    # -- 마우스 --------------------------------------------------------------

    def _value_at(self, x: float) -> int:
        """x 좌표에 해당하는 값."""
        pad = self._handle_radius
        usable = max(1.0, self.width() - pad * 2)
        ratio = (x - pad) / usable
        return int(max(0.0, min(1.0, ratio)) * self._maximum)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._maximum <= 0:
            return
        self._dragging = True
        self._value = self._value_at(event.position().x())
        self.value_preview.emit(self._value)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging:
            self._value = self._value_at(event.position().x())
            self.value_preview.emit(self._value)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._dragging or event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self._value = self._value_at(event.position().x())
        self.update()
        self.seek_requested.emit(self._value)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """휠로 조절. 로터리 엔코더를 붙였을 때와 같은 조작감이다."""
        if self._maximum <= 0:
            return
        # 한 칸당 전체의 2% (볼륨이면 2%, 3분 곡이면 약 4초)
        step = max(1, int(self._maximum * 0.02))
        delta = step if event.angleDelta().y() > 0 else -step
        self._value = max(0, min(self._value + delta, self._maximum))
        self.update()
        self.seek_requested.emit(self._value)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # -- 렌더링 --------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        pad = self._handle_radius
        usable = max(1.0, self.width() - pad * 2)
        cy = self.height() / 2
        h = self._track_height
        radius = h / 2

        # 트랙 배경
        painter.setBrush(QColor(Colors.TRACK_BG))
        painter.drawRoundedRect(QRectF(pad, cy - h / 2, usable, h), radius, radius)

        # 채워진 부분 — 호버/드래그 시 Spotify 그린으로 강조
        active = self._hovered or self._dragging
        fill_color = QColor(self._accent.base) if active else QColor(Colors.TRACK_FILL)
        fill_width = usable * self.ratio
        if fill_width > 0:
            painter.setBrush(fill_color)
            painter.drawRoundedRect(
                QRectF(pad, cy - h / 2, max(fill_width, h), h), radius, radius
            )

        # 핸들
        if active or self._always_show_handle:
            painter.setBrush(QColor(Colors.TEXT))
            cx = pad + fill_width
            r = self._handle_radius
            painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        painter.end()
