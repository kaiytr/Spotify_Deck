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

    filled = {Icon.PLAY, Icon.PAUSE, Icon.NEXT, Icon.PREVIOUS, Icon.HEART_FILLED}
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


def _repeat_base(p: QPainter) -> None:
    """반복 화살표 테두리 (숫자 없음)."""
    path = QPainterPath()
    path.moveTo(7, 5.5)
    path.lineTo(16, 5.5)
    path.cubicTo(19, 5.5, 20.5, 7.5, 20.5, 10)
    path.lineTo(20.5, 11.5)
    p.drawPath(path)

    p.drawLine(QPointF(17.5, 3), QPointF(20.5, 5.5))
    p.drawLine(QPointF(17.5, 8), QPointF(20.5, 5.5))

    path2 = QPainterPath()
    path2.moveTo(17, 18.5)
    path2.lineTo(8, 18.5)
    path2.cubicTo(5, 18.5, 3.5, 16.5, 3.5, 14)
    path2.lineTo(3.5, 12.5)
    p.drawPath(path2)

    p.drawLine(QPointF(6.5, 21), QPointF(3.5, 18.5))
    p.drawLine(QPointF(6.5, 16), QPointF(3.5, 18.5))


def _repeat(p: QPainter, color: QColor) -> None:
    _repeat_base(p)


def _repeat_one(p: QPainter, color: QColor) -> None:
    _repeat_base(p)
    # 가운데 '1' 표시
    pen = p.pen()
    pen.setWidthF(1.8)
    p.setPen(pen)
    p.drawLine(QPointF(11.2, 14.2), QPointF(12.4, 13.2))
    p.drawLine(QPointF(12.4, 13.2), QPointF(12.4, 17.5))
    p.drawLine(QPointF(11.0, 17.5), QPointF(13.8, 17.5))


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
