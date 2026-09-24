"""앨범 아트 색상 추출 테스트.

색을 아는 합성 이미지를 넣어 검증하므로 결과가 결정적이다.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.palette import (  # noqa: E402
    TARGET_MAX_SATURATION,
    TARGET_MIN_VALUE,
    AccentPalette,
    extract_accent,
)


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    """QImage/QColor 연산에 QApplication이 필요하다."""
    app = QApplication.instance() or QApplication([])
    yield app


def cover(background: str, blob: str | None = None, size: int = 200) -> QImage:
    """가짜 앨범 표지를 만든다."""
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor(background))
    if blob:
        painter = QPainter(image)
        painter.fillRect(size // 6, size // 6, size // 2, size // 2, QColor(blob))
        painter.end()
    return image


def hue(color: QColor) -> int:
    return color.getHsv()[0]


# ---------------------------------------------------------------------------
#  대표색 선택
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,background,blob,low,high",
    [
        ("검정 배경 + 빨강", "#000000", "#E03A2F", 340, 20),
        ("흰 배경 + 파랑", "#FFFFFF", "#2E6FE0", 200, 240),
        ("회색 배경 + 보라", "#303030", "#8B3FD4", 260, 290),
        ("검정 배경 + 주황", "#0A0A0A", "#E8850B", 20, 50),
        ("검정 배경 + 청록", "#000000", "#12A89B", 160, 195),
    ],
)
def test_picks_vivid_color_over_background(name, background, blob, low, high):
    """배경이 면적의 대부분이어도 유채색을 골라야 한다.

    단순히 '가장 많은 색'을 쓰면 거의 모든 표지에서 검정/흰색이 뽑힌다.
    """
    h = hue(extract_accent(cover(background, blob)).base)
    matched = low <= h <= high if low < high else (h >= low or h <= high)
    assert matched, f"{name}: hue={h}, 기대 {low}~{high}"


def test_greyscale_cover_falls_back_to_default():
    """흑백 표지에서 회색을 뽑으면 강조색 역할을 못 한다."""
    assert extract_accent(cover("#1A1A1A", "#888888")) == AccentPalette.default()


def test_all_black_falls_back_to_default():
    assert extract_accent(cover("#000000")) == AccentPalette.default()


# ---------------------------------------------------------------------------
#  가독성 보정
# ---------------------------------------------------------------------------


def test_dark_cover_is_brightened_for_dark_background():
    """어두운 색을 그대로 쓰면 #0A0A0A 배경에서 안 보인다."""
    palette = extract_accent(cover("#000000", "#3A1010"))
    h, _s, v, _ = palette.base.getHsv()

    assert v >= TARGET_MIN_VALUE, f"명도가 너무 낮다: {v}"
    assert h >= 340 or h <= 20, "밝기를 올려도 색상은 유지해야 한다"


def test_neon_cover_is_toned_down():
    """형광색을 그대로 쓰면 눈이 아프다."""
    saturation = extract_accent(cover("#000000", "#00FF00")).base.getHsv()[1]
    assert saturation <= TARGET_MAX_SATURATION


# ---------------------------------------------------------------------------
#  파생색
# ---------------------------------------------------------------------------


def test_derived_colors_form_gradient():
    palette = extract_accent(cover("#000000", "#E03A2F"))
    bright = palette.bright.getHsv()[2]
    base = palette.base.getHsv()[2]
    dim = palette.dim.getHsv()[2]

    assert bright > base > dim, f"명도 순서가 어긋난다: {bright}/{base}/{dim}"


def test_derived_colors_share_hue():
    palette = extract_accent(cover("#000000", "#2E6FE0"))
    assert len({hue(palette.base), hue(palette.bright), hue(palette.dim)}) == 1


def test_palette_equality_compares_base_color():
    """같은 색이면 UI를 다시 칠하지 않도록 비교가 되어야 한다."""
    a = extract_accent(cover("#000000", "#E03A2F"))
    b = extract_accent(cover("#000000", "#E03A2F"))
    c = extract_accent(cover("#000000", "#2E6FE0"))

    assert a == b
    assert a != c
    assert a != "not a palette"


# ---------------------------------------------------------------------------
#  안전성 — 색은 장식이므로 실패해도 앱이 멈추면 안 된다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "image",
    [None, QImage(), QImage(1, 1, QImage.Format.Format_RGB32)],
)
def test_never_raises(image):
    assert isinstance(extract_accent(image), AccentPalette)


def test_accepts_pixmap():
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap.fromImage(cover("#000000", "#E03A2F"))
    assert extract_accent(pixmap).base.getHsv()[0] in range(0, 21)


def test_extraction_is_fast_enough_for_track_change():
    """곡이 바뀔 때마다 UI 스레드에서 실행되므로 빨라야 한다."""
    import time

    image = cover("#101010", "#D4483B", size=640)
    start = time.perf_counter()
    for _ in range(10):
        extract_accent(image)
    elapsed_ms = (time.perf_counter() - start) / 10 * 1000

    assert elapsed_ms < 40, f"색 추출이 {elapsed_ms:.1f}ms로 너무 느리다"
