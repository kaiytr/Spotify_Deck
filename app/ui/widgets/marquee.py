"""가로로 흐르는 한 줄 텍스트 라벨.

왜 필요한가:
    QLabel에 줄바꿈을 켜면 긴 제목이 두 줄이 되면서 **아래 요소를 밀어낸다.**
    곡이 바뀔 때마다 웨이브 바와 진행 바의 위치가 들썩이고,
    작은 화면에서는 아래 줄이 잘려 나가기도 한다.

    줄바꿈을 끄면 이번엔 글자가 소리 없이 잘린다
    ("...여기에 표시됩" 처럼 문장이 끊긴다).

해결:
    **높이를 한 줄로 고정**하고, 폭을 넘으면 가로로 흘려서 전체를 보여 준다.
    레이아웃이 절대 변하지 않으므로 곡이 바뀌어도 아래 요소가 움직이지 않는다.

동작:
    들어감  -> 그냥 왼쪽 정렬로 표시하고 애니메이션하지 않는다.
    넘침    -> 잠시 멈춤 → 왼쪽으로 흐름 → 끝에서 멈춤 → 처음으로 복귀

    끝에서 곧바로 되감지 않고 잠시 머무는 이유는, 마지막 글자를 읽을
    시간을 주기 위해서다.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget


class _Phase(Enum):
    """흐름 단계."""

    WAIT_START = auto()   # 시작 위치에서 대기
    SCROLL = auto()       # 왼쪽으로 흐르는 중
    WAIT_END = auto()     # 끝에서 대기


#: 스크롤 속도 (초당 픽셀). 너무 빠르면 읽을 수 없다.
DEFAULT_SPEED = 26.0

#: 양 끝에서 머무는 시간 (밀리초)
DEFAULT_PAUSE_MS = 1600

#: 애니메이션 프레임 간격 (밀리초). 33ms = 약 30fps.
FRAME_MS = 33

#: 흘러간 끝부분이 가장자리에서 바로 잘리지 않도록 두는 여백
EDGE_PADDING = 12.0


class MarqueeLabel(QWidget):
    """한 줄 높이가 고정된, 필요할 때만 흐르는 텍스트."""

    def __init__(
        self,
        text: str = "",
        *,
        font: QFont | None = None,
        color: str = "#FFFFFF",
        speed: float = DEFAULT_SPEED,
        pause_ms: int = DEFAULT_PAUSE_MS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        self._speed = speed
        self._pause_ms = pause_ms

        self._offset = 0.0
        self._phase = _Phase.WAIT_START
        self._phase_elapsed = 0

        # 타이머를 먼저 만든다.
        # setFont()가 _sync_timer()를 부르므로, 순서를 바꾸면
        # "'MarqueeLabel' object has no attribute '_timer'" 로 죽는다.
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._step)

        # 높이를 한 줄로 고정한다. 이게 이 위젯의 존재 이유다.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if font is not None:
            self.setFont(font)
        else:
            self._apply_fixed_height()

    # -- 공개 API ------------------------------------------------------------

    def setText(self, text: str) -> None:  # noqa: N802 - QLabel과 같은 이름
        """표시할 문자열을 바꾼다. 곡이 바뀌면 처음부터 다시 흐른다."""
        if text == self._text:
            return
        self._text = text
        self._reset()
        self.update()

    def text(self) -> str:
        return self._text

    def setColor(self, color: str | QColor) -> None:  # noqa: N802
        self._color = QColor(color)
        self.update()

    def setFont(self, font: QFont) -> None:  # noqa: N802
        super().setFont(font)
        self._apply_fixed_height()
        self._reset()

    @property
    def is_scrolling(self) -> bool:
        """지금 흐르고 있는지 (테스트/디버깅용)."""
        return self._timer.isActive()

    # -- 내부 -----------------------------------------------------------------

    def _apply_fixed_height(self) -> None:
        metrics = QFontMetricsF(self.font())
        self.setFixedHeight(int(metrics.height() + 0.5))

    def _text_width(self) -> float:
        return QFontMetricsF(self.font()).horizontalAdvance(self._text)

    def _overflow(self) -> float:
        """폭을 넘어가는 길이. 0 이하면 다 들어간다."""
        return self._text_width() + EDGE_PADDING - self.width()

    def _reset(self) -> None:
        self._offset = 0.0
        self._phase = _Phase.WAIT_START
        self._phase_elapsed = 0
        self._sync_timer()

    def _sync_timer(self) -> None:
        """넘칠 때만 타이머를 돌린다.

        다 들어가는 텍스트까지 30fps로 다시 그리면 낭비다.
        (ESP32에서는 이런 낭비가 곧 프레임 드랍이다)
        """
        should_run = self.isVisible() and self._overflow() > 0
        if should_run and not self._timer.isActive():
            self._timer.start()
        elif not should_run and self._timer.isActive():
            self._timer.stop()
            self._offset = 0.0

    def _step(self) -> None:
        overflow = self._overflow()
        if overflow <= 0:
            self._reset()
            self.update()
            return

        self._phase_elapsed += FRAME_MS

        if self._phase is _Phase.WAIT_START:
            if self._phase_elapsed >= self._pause_ms:
                self._phase = _Phase.SCROLL
                self._phase_elapsed = 0

        elif self._phase is _Phase.SCROLL:
            self._offset += self._speed * (FRAME_MS / 1000.0)
            if self._offset >= overflow:
                self._offset = overflow
                self._phase = _Phase.WAIT_END
                self._phase_elapsed = 0

        else:  # WAIT_END
            if self._phase_elapsed >= self._pause_ms:
                self._offset = 0.0
                self._phase = _Phase.WAIT_START
                self._phase_elapsed = 0

        self.update()

    # -- 이벤트 ---------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_timer()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self.font())
        painter.setPen(self._color)

        # 흐르는 동안 글자가 위젯 밖으로 새어 나가지 않게 자른다.
        painter.setClipRect(self.rect())
        painter.drawText(
            QRectF(-self._offset, 0, self._text_width() + EDGE_PADDING, self.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._text,
        )
        painter.end()
