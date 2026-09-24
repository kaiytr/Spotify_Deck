"""웨이브 바 렌더링 미리보기 도구 (개발용).

앱을 띄우지 않고 웨이브 바만 PNG로 그려서 디자인을 비교한다.

    python tools/render_wave.py out.png

막대 높이를 고정값으로 넣으므로 매번 똑같은 그림이 나오고,
수정 전후를 나란히 비교할 수 있다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.audio.base import WaveSource  # noqa: E402
from app.ui.theme import Colors, build_stylesheet  # noqa: E402
from app.ui.widgets.wave_bar import WaveBarWidget  # noqa: E402


class FixedSource(WaveSource):
    """검증용 고정 레벨 소스."""

    name = "fixed"

    def __init__(self, levels: np.ndarray) -> None:
        super().__init__(len(levels))
        self._values = levels.astype(np.float32)

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def levels(self) -> np.ndarray:
        return self._values


#: 실제 음악처럼 보이는 대표 패턴 (저음 크고 고음 작음 + 들쭉날쭉)
DEMO_LEVELS = np.array(
    [0.62, 0.95, 0.88, 0.71, 0.45, 0.58, 0.82, 0.66, 0.39, 0.52,
     0.74, 0.61, 0.33, 0.47, 0.69, 0.55, 0.28, 0.41, 0.36, 0.49,
     0.31, 0.24, 0.38, 0.29, 0.18, 0.26, 0.15, 0.21],
    dtype=np.float32,
)

#: 피크는 현재 레벨보다 조금 위에 떠 있는 상태를 재현한다.
DEMO_PEAKS = np.clip(DEMO_LEVELS + np.array(
    [0.10, 0.03, 0.14, 0.08, 0.22, 0.05, 0.02, 0.16, 0.27, 0.11,
     0.06, 0.19, 0.30, 0.13, 0.04, 0.21, 0.25, 0.09, 0.17, 0.07,
     0.23, 0.31, 0.12, 0.20, 0.28, 0.15, 0.24, 0.18], dtype=np.float32,
), 0.0, 1.0)


def _render_one(levels, peaks, width, height) -> QPixmap:
    source = FixedSource(levels)
    widget = WaveBarWidget(source, height=height)
    # 앱과 같은 다크 테마를 적용해야 실제 화면과 같은 색으로 보인다.
    widget.setStyleSheet(build_stylesheet())
    widget.resize(width, height)
    widget._levels = levels.copy()
    widget._peaks = peaks.copy()
    widget._update_visible_bars()

    pixmap = QPixmap(QSize(width, height))
    pixmap.fill(QColor(Colors.BG))
    widget.render(pixmap)
    return pixmap


def render(path: str, width: int = 560, height: int = 68, zoom: int = 2) -> None:
    """두 가지 상황을 위아래로 이어 붙여 그린다.

    위: 피크가 막대에서 떨어져 떠 있는 상태 (감쇠 중)
    아래: 피크가 막대 꼭대기에 붙은 상태 (막 올라온 직후)
          <- 사용자 스크린샷에서 '뚜껑'처럼 보이던 경우
    """
    from PySide6.QtCore import Qt

    app = QApplication.instance() or QApplication(sys.argv)

    gap = 10
    top = _render_one(DEMO_LEVELS, DEMO_PEAKS, width, height)
    bottom = _render_one(DEMO_LEVELS, DEMO_LEVELS.copy(), width, height)

    combined = QPixmap(QSize(width, height * 2 + gap))
    combined.fill(QColor(Colors.BG))
    painter = QPainter(combined)
    painter.drawPixmap(0, 0, top)
    painter.drawPixmap(0, height + gap, bottom)
    painter.end()

    if zoom > 1:
        combined = combined.scaled(
            combined.width() * zoom,
            combined.height() * zoom,
            mode=Qt.TransformationMode.FastTransformation,
        )

    combined.save(path)
    print(f"저장: {path}  ({combined.width()}x{combined.height()})")
    print("  위: 피크가 떠 있는 상태 / 아래: 피크가 막대에 붙은 상태")
    _ = app


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "wave_preview.png"
    render(out)
