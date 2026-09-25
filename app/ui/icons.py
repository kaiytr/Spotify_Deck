"""벡터 아이콘 렌더링.

PNG 에셋을 쓰지 않고 QPainter로 직접 그린다. 이유:

  1. 해상도 독립 — 27인치 모니터에서도, 3.5인치 LCD에서도 선명하다.
     RK3399 이식 시 화면 크기가 바뀌어도 아이콘을 다시 만들 필요가 없다.
  2. 색상 변경이 자유롭다 — 좋아요 on/off, 셔플 on/off를 이미지 2벌 없이 처리한다.
  3. 저장소에 바이너리가 없어 Git diff가 깨끗하다.

모든 함수는 24x24 논리 좌표계를 기준으로 그리며,
`draw_icon()`이 실제 크기에 맞게 배율을 조정한다.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

#: 아이콘 설계 기준 크기
BASE_SIZE = 24.0


class Icon(str, Enum):
    SPOTIFY = "spotify"
    MORE = "more"
    PLAY = "play"
    PAUSE = "pause"
    NEXT = "next"
    PREVIOUS = "previous"
    SHUFFLE = "shuffle"
    REPEAT = "repeat"
    REPEAT_ONE = "repeat_one"
    HEART = "heart"
    HEART_FILLED = "heart_filled"
    VOLUME = "volume"
    VOLUME_MUTE = "volume_mute"
    DEVICE = "device"


def draw_icon(
    painter: QPainter,
    icon: Icon,
    rect: QRectF,
    color: QColor,
    *,
    stroke_width: float = 2.0,
) -> None:
    """지정한 사각형 안에 아이콘을 그린다.

    Args:
        painter: 이미 begin()된 QPainter.
        icon: 그릴 아이콘.
        rect: 그릴 영역 (정사각형이 아니어도 가운데 맞춤).
        color: 아이콘 색.
        stroke_width: 선으로 그리는 아이콘의 두께 (24px 기준).
    """
    size = min(rect.width(), rect.height())
    if size <= 0:
        return
    scale = size / BASE_SIZE

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # 아이콘 좌표계를 rect 중앙에 맞춘다.
    painter.translate(
        rect.center().x() - size / 2,
        rect.center().y() - size / 2,
    )
    painter.scale(scale, scale)

    filled = {
        Icon.PLAY, Icon.PAUSE, Icon.NEXT, Icon.PREVIOUS, Icon.HEART_FILLED,
        Icon.SPOTIFY, Icon.MORE,
    }
    if icon in filled:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
    else:
        pen = QPen(color, stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    _PAINTERS[icon](painter, color)
    painter.restore()


# ---------------------------------------------------------------------------
#  개별 아이콘 (24x24 좌표계)
# ---------------------------------------------------------------------------


def _spotify(p: QPainter, color: QColor) -> None:
    """Spotify 마크 — 채워진 원 + 음파 3개.

    원은 전달받은 색으로 칠하고, 음파는 배경색으로 '파낸다'.
    배경색으로 그리므로 어떤 원 색에서도 음파가 또렷하게 보인다.
    """
    from app.ui.theme import Colors

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QRectF(1.5, 1.5, 21, 21))

    # 음파 3개. 위에서 아래로 갈수록 좁아지고 얇아진다.
    arcs = (
        ((5.6, 9.4), (12.0, 6.2), (18.4, 9.4), 2.5),
        ((7.0, 13.2), (12.0, 10.6), (17.0, 13.2), 2.1),
        ((8.4, 16.6), (12.0, 14.5), (15.6, 16.6), 1.8),
    )
    p.setBrush(Qt.BrushStyle.NoBrush)
    for start, control, end, width in arcs:
        pen = QPen(QColor(Colors.BG), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        path = QPainterPath()
        path.moveTo(*start)
        path.quadTo(control[0], control[1], end[0], end[1])
        p.drawPath(path)


def _more(p: QPainter, color: QColor) -> None:
    """가로로 놓인 점 세 개 (더보기)."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    radius = 1.6
    for cx in (5.5, 12.0, 18.5):
        p.drawEllipse(QRectF(cx - radius, 12 - radius, radius * 2, radius * 2))


def _play(p: QPainter, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(7, 4.5)
    path.lineTo(19.5, 12)
    path.lineTo(7, 19.5)
    path.closeSubpath()
    p.drawPath(path)


def _pause(p: QPainter, color: QColor) -> None:
    p.drawRoundedRect(QRectF(6.5, 4.5, 3.8, 15), 1.2, 1.2)
    p.drawRoundedRect(QRectF(13.7, 4.5, 3.8, 15), 1.2, 1.2)


def _next(p: QPainter, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(5, 5)
    path.lineTo(15, 12)
    path.lineTo(5, 19)
    path.closeSubpath()
    p.drawPath(path)
    p.drawRoundedRect(QRectF(16.5, 5, 2.8, 14), 1.0, 1.0)


def _previous(p: QPainter, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(19, 5)
    path.lineTo(9, 12)
    path.lineTo(19, 19)
    path.closeSubpath()
    p.drawPath(path)
    p.drawRoundedRect(QRectF(4.7, 5, 2.8, 14), 1.0, 1.0)


def _shuffle(p: QPainter, color: QColor) -> None:
    # 교차하는 두 화살표
    path = QPainterPath()
    path.moveTo(3, 7)
    path.lineTo(7, 7)
    path.cubicTo(10, 7, 11.5, 17, 14.5, 17)
    path.lineTo(19.5, 17)
    p.drawPath(path)

    path2 = QPainterPath()
    path2.moveTo(3, 17)
    path2.lineTo(7, 17)
    path2.cubicTo(10, 17, 11.5, 7, 14.5, 7)
    path2.lineTo(19.5, 7)
    p.drawPath(path2)

    _arrow_head(p, QPointF(19.5, 7), up=True)
    _arrow_head(p, QPointF(19.5, 17), up=True)


def _arrow_head(p: QPainter, tip: QPointF, *, up: bool) -> None:  # noqa: ARG001
    """오른쪽을 향하는 화살촉."""
    path = QPainterPath()
    path.moveTo(tip.x() - 3, tip.y() - 3)
    path.lineTo(tip.x(), tip.y())
    path.lineTo(tip.x() - 3, tip.y() + 3)
    p.drawPath(path)


#: 반복 아이콘의 고리 치수 (24x24 좌표계)
_LOOP_TOP = 7.0
_LOOP_BOTTOM = 17.0
_LOOP_LEFT = 4.0
_LOOP_RIGHT = 20.0
_LOOP_RADIUS = 3.5
_ARROW = 2.8


def _repeat_base(p: QPainter) -> None:
    """반복 고리 (숫자 없음).

    가로로 납작한 둥근 사각형 고리다. 두 획으로 나뉜다.

        ┌──────────────▶     위: 왼쪽 세로 → 모서리 → 오른쪽으로, 끝에 화살촉
        │              │
        ◀──────────────┘     아래: 오른쪽 세로 → 모서리 → 왼쪽으로, 끝에 화살촉

    이전 구현은 화살촉을 선이 끝나는 곳이 아닌 엉뚱한 좌표에 그려서
    화살표가 고리에서 떨어져 떠 있었다. 여기서는 각 획의 마지막 점에
    화살촉을 붙여 하나의 도형으로 읽히게 한다.
    """
    top = _LOOP_TOP
    bottom = _LOOP_BOTTOM
    left = _LOOP_LEFT
    right = _LOOP_RIGHT
    r = _LOOP_RADIUS

    # --- 위쪽 획: 왼쪽 세로 → 둥근 모서리 → 오른쪽 가로 ---
    upper = QPainterPath()
    upper.moveTo(left, bottom - r)          # 왼쪽 아래에서 시작
    upper.lineTo(left, top + r)             # 위로
    upper.quadTo(left, top, left + r, top)  # 왼쪽 위 모서리
    upper.lineTo(right - _ARROW, top)       # 오른쪽으로 (화살촉 자리는 남긴다)
    p.drawPath(upper)
    _arrow_right(p, right - _ARROW + 0.6, top)

    # --- 아래쪽 획: 오른쪽 세로 → 둥근 모서리 → 왼쪽 가로 ---
    lower = QPainterPath()
    lower.moveTo(right, top + r)                      # 오른쪽 위에서 시작
    lower.lineTo(right, bottom - r)                   # 아래로
    lower.quadTo(right, bottom, right - r, bottom)    # 오른쪽 아래 모서리
    lower.lineTo(left + _ARROW, bottom)               # 왼쪽으로
    p.drawPath(lower)
    _arrow_left(p, left + _ARROW - 0.6, bottom)


def _arrow_right(p: QPainter, tip_x: float, y: float) -> None:
    """오른쪽을 향하는 화살촉. tip이 선의 끝에 정확히 붙는다."""
    path = QPainterPath()
    path.moveTo(tip_x - _ARROW, y - _ARROW)
    path.lineTo(tip_x, y)
    path.lineTo(tip_x - _ARROW, y + _ARROW)
    p.drawPath(path)


def _arrow_left(p: QPainter, tip_x: float, y: float) -> None:
    """왼쪽을 향하는 화살촉."""
    path = QPainterPath()
    path.moveTo(tip_x + _ARROW, y - _ARROW)
    path.lineTo(tip_x, y)
    path.lineTo(tip_x + _ARROW, y + _ARROW)
    p.drawPath(path)


def _repeat(p: QPainter, color: QColor) -> None:
    _repeat_base(p)


def _repeat_one(p: QPainter, color: QColor) -> None:
    """한 곡 반복 — 고리 가운데에 '1'.

    '1'은 고리 안쪽 빈 공간(y 7~17의 가운데)에 놓는다.
    이전에는 아래쪽 가로선과 겹쳐 뭉개져 보였다.
    """
    _repeat_base(p)

    cx = (_LOOP_LEFT + _LOOP_RIGHT) / 2
    cy = (_LOOP_TOP + _LOOP_BOTTOM) / 2

    pen = p.pen()
    pen.setWidthF(1.7)
    p.setPen(pen)

    # 숫자 1: 왼쪽 위 사선 + 세로 획 + 아래 받침
    p.drawLine(QPointF(cx - 1.4, cy - 1.4), QPointF(cx, cy - 2.4))
    p.drawLine(QPointF(cx, cy - 2.4), QPointF(cx, cy + 2.4))
    p.drawLine(QPointF(cx - 1.5, cy + 2.4), QPointF(cx + 1.5, cy + 2.4))


def _heart_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(12, 20.4)
    path.cubicTo(12, 20.4, 2.6, 14.4, 2.6, 8.7)
    path.cubicTo(2.6, 5.6, 5.0, 3.5, 7.7, 3.5)
    path.cubicTo(9.6, 3.5, 11.2, 4.6, 12, 6.2)
    path.cubicTo(12.8, 4.6, 14.4, 3.5, 16.3, 3.5)
    path.cubicTo(19.0, 3.5, 21.4, 5.6, 21.4, 8.7)
    path.cubicTo(21.4, 14.4, 12, 20.4, 12, 20.4)
    path.closeSubpath()
    return path


def _heart(p: QPainter, color: QColor) -> None:
    p.drawPath(_heart_path())


def _heart_filled(p: QPainter, color: QColor) -> None:
    p.drawPath(_heart_path())


def _volume(p: QPainter, color: QColor) -> None:
    # 스피커 본체
    path = QPainterPath()
    path.moveTo(3.5, 9.5)
    path.lineTo(7, 9.5)
    path.lineTo(11.5, 5.5)
    path.lineTo(11.5, 18.5)
    path.lineTo(7, 14.5)
    path.lineTo(3.5, 14.5)
    path.closeSubpath()
    p.drawPath(path)
    # 음파 2개
    p.drawArc(QRectF(10.5, 7.5, 7, 9), -60 * 16, 120 * 16)
    p.drawArc(QRectF(12.5, 5, 9, 14), -60 * 16, 120 * 16)


def _volume_mute(p: QPainter, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(3.5, 9.5)
    path.lineTo(7, 9.5)
    path.lineTo(11.5, 5.5)
    path.lineTo(11.5, 18.5)
    path.lineTo(7, 14.5)
    path.lineTo(3.5, 14.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(15, 9.5), QPointF(20.5, 14.5))
    p.drawLine(QPointF(20.5, 9.5), QPointF(15, 14.5))


def _device(p: QPainter, color: QColor) -> None:
    p.drawRoundedRect(QRectF(3.5, 5.5, 17, 11), 1.8, 1.8)
    p.drawLine(QPointF(8.5, 19.5), QPointF(15.5, 19.5))


_PAINTERS = {
    Icon.SPOTIFY: _spotify,
    Icon.MORE: _more,
    Icon.PLAY: _play,
    Icon.PAUSE: _pause,
    Icon.NEXT: _next,
    Icon.PREVIOUS: _previous,
    Icon.SHUFFLE: _shuffle,
    Icon.REPEAT: _repeat,
    Icon.REPEAT_ONE: _repeat_one,
    Icon.HEART: _heart,
    Icon.HEART_FILLED: _heart_filled,
    Icon.VOLUME: _volume,
    Icon.VOLUME_MUTE: _volume_mute,
    Icon.DEVICE: _device,
}
