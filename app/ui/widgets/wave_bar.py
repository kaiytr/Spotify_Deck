"""웨이브 바(스펙트럼 애널라이저) 위젯.

주파수 대역별 레벨을 세로 막대로 그린다.

시각 설계:
  * 아래에서 위로 자라는 막대 + 바닥에 은은한 반사
  * 저음(왼쪽)은 Spotify 그린, 고음(오른쪽)으로 갈수록 밝게 — 대역이 눈에 구분된다
  * 막대 끝에 '피크 홀드' 점이 잠깐 머물다 떨어진다 (실제 오디오 기기 느낌)
  * 화면 폭에 맞춰 막대 개수를 자동으로 줄인다 (3.5인치 LCD 대응)

성능:
  60fps로 다시 그리므로 paintEvent가 무거우면 안 된다.
  QPainter 기본 도형만 쓰고 그라디언트는 한 번 만들어 재사용한다.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.audio.base import WaveSource
from app.ui.palette import AccentPalette
from app.ui.theme import Colors

#: 피크 점이 떨어지는 속도 (프레임당 비율)
PEAK_FALL_RATE = 0.012

#: 막대 하나의 최소 폭(px). 이보다 좁아지면 막대 수를 줄인다.
MIN_BAR_WIDTH = 3.0

#: 피크 표시가 나타나기 시작하는 최소 간격 (레벨 대비 비율).
#: 이보다 가까우면 막대에 붙은 '뚜껑'처럼 보이므로 그리지 않는다.
PEAK_MIN_GAP = 0.05

#: 이 간격만큼 더 벌어지면 피크가 완전히 불투명해진다 (서서히 나타남).
PEAK_FADE_RANGE = 0.07


class WaveBarWidget(QWidget):
    """실시간 스펙트럼 막대."""

    def __init__(
        self,
        source: WaveSource,
        *,
        height: int = 64,
        fps: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._band_count = source.band_count

        self._levels = np.zeros(self._band_count, dtype=np.float32)
        self._peaks = np.zeros(self._band_count, dtype=np.float32)

        #: 화면이 좁을 때 실제로 그릴 막대 수 (band_count 이하)
        self._visible_bars = self._band_count

        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # 마우스 이벤트를 아래 위젯으로 통과시킨다 (장식 요소이므로)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._gradient_cache: QLinearGradient | None = None
        self._cached_height = -1
        self._accent = AccentPalette.default()

        self._timer = QTimer(self)
        self._timer.setInterval(max(8, 1000 // max(1, fps)))
        self._timer.timeout.connect(self._tick)

    # -- 수명 주기 ----------------------------------------------------------

    def start(self) -> None:
        self._source.start()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._source.stop()

    def set_playing(self, playing: bool) -> None:
        self._source.set_playing(playing)

    def set_accent(self, palette: AccentPalette) -> None:
        """앨범에서 뽑은 강조색으로 막대 색을 바꾼다."""
        self._accent = palette
        self._gradient_cache = None   # 그라디언트를 다시 만들게 한다
        self.update()

    @property
    def source(self) -> WaveSource:
        return self._source

    # -- 프레임 갱신 ---------------------------------------------------------

    def _tick(self) -> None:
        if not self.isVisible():
            return

        levels = self._source.levels()
        if levels.shape != self._levels.shape:
            # 소스가 바뀌는 등 예외 상황. 크기를 맞춘다.
            self._levels = np.zeros_like(levels)
            self._peaks = np.zeros_like(levels)
        self._levels = levels

        # 피크 홀드: 새 값이 더 높으면 즉시 올리고, 아니면 천천히 떨어뜨린다.
        higher = levels > self._peaks
        self._peaks[higher] = levels[higher]
        self._peaks[~higher] = np.maximum(
            self._peaks[~higher] - PEAK_FALL_RATE, levels[~higher]
        )

        self.update()

    # -- 렌더링 --------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_visible_bars()
        self._gradient_cache = None

    def _update_visible_bars(self) -> None:
        """폭에 맞춰 그릴 막대 수를 정한다.

        좁은 화면(3.5인치 LCD)에서 막대가 1px 미만이 되면 뭉개져 보이므로
        대역을 솎아내 개수를 줄인다.
        """
        width = max(1, self.width())
        max_bars = int(width / MIN_BAR_WIDTH)
        self._visible_bars = max(6, min(self._band_count, max_bars))

    def _bar_values(self) -> tuple[np.ndarray, np.ndarray]:
        """화면에 그릴 막대 값. 필요하면 대역을 솎아낸다."""
        if self._visible_bars >= self._band_count:
            return self._levels, self._peaks
        # 균등 간격으로 골라낸다 (평균보다 최대값이 시각적으로 또렷하다)
        idx = np.linspace(0, self._band_count - 1, self._visible_bars).astype(int)
        return self._levels[idx], self._peaks[idx]

    def _gradient(self, height: float) -> QLinearGradient:
        """막대 세로 그라디언트 (아래 진한 색 → 위 밝은 색).

        색은 현재 앨범 아트에서 뽑은 것을 쓴다.
        """
        if self._gradient_cache is None or self._cached_height != height:
            grad = QLinearGradient(0, height, 0, 0)
            grad.setColorAt(0.0, self._accent.dim)
            grad.setColorAt(0.55, self._accent.base)
            grad.setColorAt(1.0, self._accent.bright)
            self._gradient_cache = grad
            self._cached_height = height
        return self._gradient_cache

    def paintEvent(self, event) -> None:  # noqa: N802
        levels, peaks = self._bar_values()
        count = len(levels)
        if count == 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        w = self.width()
        h = self.height()

        # 막대 영역은 위 80%, 아래 20%는 반사용
        bar_area = h * 0.78
        baseline = bar_area
        reflection_h = h - bar_area

        slot = w / count
        gap = min(3.0, slot * 0.28)
        bar_w = max(1.0, slot - gap)
        radius = min(bar_w / 2, 2.5)

        gradient = self._gradient(bar_area)
        painter.setBrush(gradient)

        for i in range(count):
            level = float(levels[i])
            x = i * slot + gap / 2

            # 아주 작은 값도 1px 씨앗을 남겨 바닥선이 보이게 한다.
            bar_h = max(1.5, level * bar_area)
            rect = QRectF(x, baseline - bar_h, bar_w, bar_h)
            painter.drawRoundedRect(rect, radius, radius)

            # 바닥 반사 — 같은 막대를 뒤집어 흐리게 그린다.
            if reflection_h > 2 and level > 0.02:
                ref_h = min(bar_h * 0.45, reflection_h)
                ref_color = QColor(self._accent.base)
                ref_color.setAlphaF(0.16 * min(1.0, level * 1.6))
                painter.setBrush(ref_color)
                painter.drawRoundedRect(
                    QRectF(x, baseline + 1, bar_w, ref_h), radius, radius
                )
                painter.setBrush(gradient)

        painter.end()
