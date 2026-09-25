"""실물 크기 미리보기 배율 계산.

문제:
    480x320은 픽셀 수일 뿐이고, 화면에 몇 밀리미터로 보이는지는
    모니터의 픽셀 밀도에 달렸다.

        4인치 480x320 패널  ->  대각 576.9px / 4in = 144 PPI
        일반 데스크톱 모니터 ->  약 96~110 PPI

    픽셀이 성길수록 같은 480px가 더 넓게 퍼진다.
    그래서 아무 조치 없이 띄우면 실물보다 30~50% 크게 보인다.

해결:
    **레이아웃은 480x320 그대로 두고, 그려진 결과만 축소한다.**
    창을 354x236으로 줄이면 안 된다 — 그건 작은 화면이 아니라
    폰트와 버튼이 다시 배치된 *다른 레이아웃*이 되어 버린다.

이 모듈은 Qt에 의존하지 않는 순수 계산이라 단독으로 검증할 수 있다.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4


def device_ppi(width_px: int, height_px: int, diagonal_inches: float) -> float:
    """기기 패널의 픽셀 밀도(PPI).

    예: 480x320이 4인치면 대각 576.9px / 4in = 144.2 PPI
    """
    if diagonal_inches <= 0:
        raise ValueError("대각 길이는 0보다 커야 합니다.")
    diagonal_px = math.hypot(width_px, height_px)
    return diagonal_px / diagonal_inches


def monitor_ppi(screen_width_px: int, screen_width_mm: float) -> float:
    """모니터의 픽셀 밀도(PPI).

    **논리 픽셀 기준**이다. Windows 배율(devicePixelRatio)이 걸려 있으면
    Qt가 보고하는 geometry도 논리 픽셀이므로 계산이 일관된다.
    """
    if screen_width_mm <= 0:
        raise ValueError("모니터 물리 폭을 알 수 없습니다.")
    return screen_width_px / (screen_width_mm / MM_PER_INCH)


def physical_scale(
    *,
    device_width_px: int,
    device_height_px: int,
    device_diagonal_inches: float,
    screen_width_px: int,
    screen_width_mm: float,
) -> float:
    """화면에 실물 크기로 보이게 하는 배율.

    Returns:
        1.0보다 작으면 축소(모니터가 기기보다 성김),
        1.0보다 크면 확대(모니터가 기기보다 조밀함).
    """
    dev = device_ppi(device_width_px, device_height_px, device_diagonal_inches)
    mon = monitor_ppi(screen_width_px, screen_width_mm)
    return mon / dev


def physical_size_mm(
    width_px: int, height_px: int, diagonal_inches: float
) -> tuple[float, float]:
    """기기 화면의 실제 가로·세로 (밀리미터).

    자를 대고 확인할 때 쓴다.
    """
    ppi = device_ppi(width_px, height_px, diagonal_inches)
    return (width_px / ppi * MM_PER_INCH, height_px / ppi * MM_PER_INCH)


def scale_for_screen(screen, *, device_width_px: int, device_height_px: int,
                     device_diagonal_inches: float) -> float:
    """QScreen에서 배율을 구한다.

    모니터의 물리 크기를 알 수 없으면 1.0(축소 없음)을 반환하고 경고한다.
    가상 머신이나 일부 드라이버는 물리 크기를 보고하지 않는다.
    """
    try:
        geometry = screen.geometry()
        physical = screen.physicalSize()
        width_mm = float(physical.width())

        if width_mm <= 0:
            raise ValueError("physicalSize가 0")

        return physical_scale(
            device_width_px=device_width_px,
            device_height_px=device_height_px,
            device_diagonal_inches=device_diagonal_inches,
            screen_width_px=geometry.width(),
            screen_width_mm=width_mm,
        )
    except Exception as exc:  # noqa: BLE001 - 미리보기 기능이 앱을 막으면 안 된다
        logger.warning(
            "모니터 물리 크기를 알 수 없어 실물 크기 보정을 건너뜁니다: %s", exc
        )
        return 1.0


def describe(scale: float, device_width_px: int, device_height_px: int,
             diagonal_inches: float) -> str:
    """로그에 남길 설명."""
    w_mm, h_mm = physical_size_mm(device_width_px, device_height_px, diagonal_inches)
    return (
        f"실물 크기 미리보기 배율 {scale:.3f} "
        f"({diagonal_inches}인치 = {w_mm:.1f} x {h_mm:.1f} mm)"
    )
