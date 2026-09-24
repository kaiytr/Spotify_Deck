"""앨범 아트에서 포인트 색 추출.

곡이 바뀌면 웨이브 바·진행 바·버튼의 강조색이 앨범 표지 색으로 함께 바뀐다.
덱이 "지금 이 곡"을 입고 있는 느낌을 준다.

핵심 어려움은 **아무 색이나 뽑으면 안 된다**는 것이다.

  * 어두운 배경(#0A0A0A) 위에서 읽혀야 하므로 너무 어두운 색은 못 쓴다.
  * 흑백 표지에서 회색을 뽑으면 강조색 역할을 못 한다.
  * 형광색을 그대로 쓰면 눈이 아프다.

그래서 후보를 **점수화**해 고르고, 고른 뒤 명도·채도를 보정한다.
적당한 색이 없으면 기본 Spotify 그린으로 돌아간다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap

from app.ui.theme import Colors

logger = logging.getLogger(__name__)

#: 색 추출용 축소 크기. 작을수록 빠르고, 이 정도면 대표색을 뽑기에 충분하다.
SAMPLE_SIZE = 48

#: 색상환을 이 개수로 나눠 묶는다 (비슷한 색끼리 합치기).
HUE_BUCKETS = 24

#: 이보다 채도가 낮으면 '무채색'으로 보고 강조색 후보에서 제외한다.
MIN_SATURATION = 60      # 0~255

#: 너무 어둡거나 너무 밝은 픽셀은 대표색이 되기 어렵다.
MIN_VALUE = 55
MAX_VALUE = 250

#: 최종 강조색이 가져야 할 최소 명도 (어두운 배경에서 읽히도록).
TARGET_MIN_VALUE = 165

#: 최종 강조색의 채도 범위. 너무 낮으면 밋밋하고 너무 높으면 눈이 아프다.
TARGET_MIN_SATURATION = 120
TARGET_MAX_SATURATION = 225


@dataclass(frozen=True)
class AccentPalette:
    """앨범에서 뽑아낸 강조색 묶음."""

    base: QColor       # 주 강조색
    bright: QColor     # 호버/하이라이트용 밝은 변형
    dim: QColor        # 그라디언트 아래쪽용 어두운 변형

    @classmethod
    def default(cls) -> "AccentPalette":
        """추출 실패 시 쓰는 Spotify 그린."""
        return cls(
            base=QColor(Colors.ACCENT),
            bright=QColor(Colors.ACCENT_HI),
            dim=QColor(Colors.ACCENT_DIM),
        )

    @classmethod
    def from_color(cls, color: QColor) -> "AccentPalette":
        """주 색에서 밝은/어두운 변형을 파생한다."""
        h, s, v, _ = color.getHsv()
        return cls(
            base=color,
            bright=QColor.fromHsv(h, max(0, s - 25), min(255, v + 35)),
            dim=QColor.fromHsv(h, min(255, s + 20), max(0, int(v * 0.52))),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AccentPalette):
            return NotImplemented
        return self.base.rgb() == other.base.rgb()

    def __hash__(self) -> int:
        return hash(self.base.rgb())


def extract_accent(pixmap: QPixmap | QImage | None) -> AccentPalette:
    """앨범 아트에서 강조색을 뽑는다.

    실패하거나 적당한 색이 없으면 기본 팔레트를 반환한다.
    예외를 던지지 않는다 — 색은 장식이라 실패해도 앱이 멈추면 안 된다.
    """
    if pixmap is None:
        return AccentPalette.default()

    try:
        image = pixmap.toImage() if isinstance(pixmap, QPixmap) else pixmap
        if image.isNull():
            return AccentPalette.default()

        color = _dominant_vivid_color(image)
        if color is None:
            return AccentPalette.default()

        return AccentPalette.from_color(_make_readable(color))
    except Exception as exc:  # noqa: BLE001 - 색 추출 실패가 재생을 막으면 안 된다
        # exception()으로 남긴다. debug()로 낮추면 프로그래밍 실수까지
        # 조용히 기본 팔레트로 떨어져 '왜 색이 안 바뀌지?'로만 보인다.
        # (실제로 Qt 열거형을 정수로 넘긴 버그가 이렇게 묻혔다)
        logger.exception("앨범 색상 추출 실패 - 기본 팔레트를 사용합니다: %s", exc)
        return AccentPalette.default()


def _dominant_vivid_color(image: QImage) -> QColor | None:
    """가장 눈에 띄는 유채색을 고른다.

    단순히 '가장 많은 색'을 고르면 대부분의 표지에서 배경(검정/흰색)이 뽑힌다.
    그래서 채도와 개수를 함께 점수로 매긴다.
    """
    # 축소해서 픽셀 수를 줄인다. 48x48이면 2304픽셀로 충분히 빠르다.
    # 대표색만 필요하므로 비율이 깨져도 무방하다.
    small = image.scaled(
        SAMPLE_SIZE,
        SAMPLE_SIZE,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_RGB32)

    # 색상(hue) 구간별로 채도 가중 점수를 누적한다.
    scores: dict[int, float] = {}
    sums: dict[int, list[int]] = {}

    for y in range(small.height()):
        for x in range(small.width()):
            color = small.pixelColor(x, y)
            h, s, v, _ = color.getHsv()

            # 무채색(h == -1)과 너무 어둡거나 밝은 픽셀은 건너뛴다.
            if h < 0 or s < MIN_SATURATION or not (MIN_VALUE <= v <= MAX_VALUE):
                continue

            bucket = (h * HUE_BUCKETS) // 360

            # 채도가 높을수록, 적당히 밝을수록 높은 점수.
            # 채도를 제곱해 선명한 색이 흐릿한 색보다 확실히 우위를 갖게 한다.
            weight = (s / 255.0) ** 2 * (v / 255.0)
            scores[bucket] = scores.get(bucket, 0.0) + weight

            acc = sums.setdefault(bucket, [0, 0, 0, 0])
            acc[0] += color.red()
            acc[1] += color.green()
            acc[2] += color.blue()
            acc[3] += 1

    if not scores:
        return None   # 흑백 표지 등 - 유채색이 없다

    best = max(scores, key=lambda k: scores[k])
    r, g, b, count = sums[best]
    return QColor(r // count, g // count, b // count)


def _make_readable(color: QColor) -> QColor:
    """어두운 배경에서 읽히도록 명도와 채도를 보정한다.

    앨범에서 뽑은 색을 그대로 쓰면
    어두운 표지에서는 거의 안 보이고, 형광 표지에서는 눈이 아프다.
    """
    h, s, v, _ = color.getHsv()

    v = max(v, TARGET_MIN_VALUE)
    s = max(TARGET_MIN_SATURATION, min(s, TARGET_MAX_SATURATION))

    return QColor.fromHsv(h, s, v)
