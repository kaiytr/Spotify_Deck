"""대상 하드웨어 정의.

⚠️ **이 모듈은 PC 실행에 전혀 관여하지 않는다.**
   ESP32 이식을 준비하기 위한 사양 기록이며, main.py는 이걸 import하지 않는다.

────────────────────────────────────────────────────────────────────────
 확인된 것과 확인되지 않은 것을 엄격히 구분한다
────────────────────────────────────────────────────────────────────────
 잘못된 핀 번호는 최악의 실수다. 보드가 부팅은 되는데 화면이 안 나오거나,
 최악의 경우 출력끼리 충돌해 하드웨어가 상한다.
 그래서 **확인되지 않은 값은 None으로 두고, 코드가 그걸 감지해 거부한다.**
 "일단 흔한 값으로 채워 두자"는 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Confidence(str, Enum):
    """정보의 출처와 신뢰도."""

    CONFIRMED = "confirmed"      # 판매 페이지/데이터시트에 명시됨
    LIKELY = "likely"            # 정황 증거가 강하지만 미확인
    UNKNOWN = "unknown"          # 확인된 바 없음 - 임의로 채우지 않는다


@dataclass(frozen=True)
class Spec:
    """사양 항목 하나. 값과 함께 출처를 들고 다닌다."""

    value: object | None
    confidence: Confidence
    source: str = ""

    @property
    def is_usable(self) -> bool:
        """코드에서 믿고 써도 되는 값인지."""
        return self.value is not None and self.confidence is Confidence.CONFIRMED


# ===========================================================================
#  대상 보드
# ===========================================================================
#
#  Hosyond 4.0" ESP32 디스플레이 (Amazon ASIN B0FGJJ24S1)
#
#  주의: Amazon 상품 페이지는 자동 조회가 차단되어(HTTP 503) 직접 읽지 못했다.
#        아래 CONFIRMED 항목은 검색 결과에 노출된 리스팅 사양이며,
#        **실물을 받으면 반드시 대조해야 한다.**
#
BOARD_NAME = "Hosyond 4.0in ESP32-32E ST7796S"
BOARD_SOURCE = "https://www.amazon.com/dp/B0FGJJ24S1"

SPECS: dict[str, Spec] = {
    # --- 확인됨 ---
    "mcu": Spec("ESP32-D0WD-V3 (ESP32-32E)", Confidence.CONFIRMED, "리스팅"),
    "cpu": Spec("dual-core LX6 @ 240MHz", Confidence.CONFIRMED, "리스팅"),
    "sram_bytes": Spec(520 * 1024, Confidence.CONFIRMED, "리스팅"),
    "flash_bytes": Spec(4 * 1024 * 1024, Confidence.CONFIRMED, "리스팅 (QSPI)"),
    "display_driver": Spec("ST7796S", Confidence.CONFIRMED, "리스팅"),
    "display_bus": Spec("4-line SPI", Confidence.CONFIRMED, "리스팅"),
    "panel_type": Spec("TN TFT", Confidence.CONFIRMED, "리스팅"),
    "native_resolution": Spec((320, 480), Confidence.CONFIRMED, "리스팅"),
    "wifi": Spec("802.11 b/g/n 2.4GHz", Confidence.CONFIRMED, "리스팅"),
    "bluetooth": Spec("BT 4.2 BR/EDR + BLE", Confidence.CONFIRMED, "리스팅"),
    # --- 정황상 유력하나 미확인 ---
    "touch_type": Spec(
        "resistive (XPT2046 추정)",
        Confidence.LIKELY,
        "터치펜 동봉 + TN 패널 = 저항막의 강한 정황. 정전식이면 FT6336U 등 I2C.",
    ),
    # --- 확인 안 됨: 임의로 채우지 않는다 ---
    "psram_bytes": Spec(
        None,
        Confidence.UNKNOWN,
        "리스팅에 PSRAM 언급 없음. 없다고 가정하고 설계하는 편이 안전하다.",
    ),
    "free_gpio": Spec(None, Confidence.UNKNOWN, "이 SKU의 핀맵 미공개"),
}


# ===========================================================================
#  화면
# ===========================================================================

#: 실제 사용 방향. 세로 320x480 패널을 가로로 돌려 쓴다.
SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320

#: 패널 대각 길이(인치). 리스팅에 명시된 값.
#: 실물 크기 미리보기(--true-size)의 기준이다.
#: 480x320을 4인치에 담으면 144 PPI가 된다.
DEVICE_DIAGONAL_INCHES = 4.0

#: RGB565 풀 프레임버퍼 크기 = 480 * 320 * 2 = 307,200 바이트 (300KB)
FULL_FRAMEBUFFER_BYTES = SCREEN_WIDTH * SCREEN_HEIGHT * 2


def framebuffer_feasible() -> tuple[bool, str]:
    """풀 프레임버퍼를 메모리에 올릴 수 있는지 판단한다.

    이 판단이 UI 설계를 좌우한다.
    전체 화면 버퍼를 못 잡으면 **부분 갱신(스트립 렌더링)** 으로 가야 하고,
    그러면 "화면 전체를 매 프레임 다시 그리는" PC식 렌더링을 쓸 수 없다.
    """
    sram = SPECS["sram_bytes"].value
    psram = SPECS["psram_bytes"]

    if psram.is_usable:
        return True, f"PSRAM {psram.value // 1024}KB 사용 가능"

    assert isinstance(sram, int)
    # WiFi 스택 + TLS + 앱 스택을 빼면 실제 가용 힙은 훨씬 적다.
    # 경험적으로 WiFi + HTTPS를 쓰면 여유 힙이 150~200KB 수준이다.
    usable_estimate = 180 * 1024

    return False, (
        f"PSRAM 미확인 → 없다고 가정. "
        f"SRAM {sram // 1024}KB 중 WiFi/TLS 제외 가용 힙 약 {usable_estimate // 1024}KB. "
        f"풀 프레임버퍼 {FULL_FRAMEBUFFER_BYTES // 1024}KB는 들어가지 않는다. "
        f"→ 부분 갱신(스트립 렌더링) 필요."
    )


# ===========================================================================
#  핀 배치 — 전부 미확인
# ===========================================================================
#
#  TODO(hardware): 실물을 받으면 아래를 채운다.
#
#    확인 방법:
#      1. 보드 뒷면 실크스크린과 동봉 문서 확인
#      2. 판매처에 데이터시트/예제 코드 요청
#      3. GitHub에서 "ESP32-3248S035" / "CYD" 보드 정의 검색 후 대조
#         (같은 계열이지만 4.0인치는 핀이 다를 수 있다)
#      4. I2C 스캐너를 돌려 터치 컨트롤러 주소 확인
#         (0x38/0x14/0x5D = 정전식, 응답 없으면 저항막 SPI)
#
#  ⚠️ 확인 전까지 값을 채우지 마라. 잘못된 핀은 하드웨어를 상하게 할 수 있다.
#


@dataclass(frozen=True)
class PinMap:
    """GPIO 핀 배치.

    None = 확인되지 않음. 코드가 이를 감지해 해당 기능을 비활성화한다.
    """

    # --- 디스플레이 (ST7796S, SPI) ---
    tft_mosi: int | None = None
    tft_miso: int | None = None
    tft_sclk: int | None = None
    tft_cs: int | None = None
    tft_dc: int | None = None
    tft_rst: int | None = None
    tft_backlight: int | None = None

    # --- 터치 ---
    touch_cs: int | None = None       # 저항막(XPT2046)인 경우
    touch_irq: int | None = None
    touch_sda: int | None = None      # 정전식(I2C)인 경우
    touch_scl: int | None = None

    # --- 물리 버튼 (외부 추가 예정) ---
    btn_previous: int | None = None
    btn_play_pause: int | None = None
    btn_next: int | None = None
    btn_shuffle: int | None = None
    btn_repeat: int | None = None
    btn_like: int | None = None

    # --- 로터리 엔코더 (외부 추가 예정) ---
    encoder_clk: int | None = None
    encoder_dt: int | None = None
    encoder_sw: int | None = None

    def unconfirmed(self) -> list[str]:
        """아직 채워지지 않은 핀 이름 목록."""
        return [name for name, value in vars(self).items() if value is None]

    def conflicts(self) -> list[str]:
        """같은 핀을 두 곳에 배정한 경우를 찾는다.

        실물 핀을 채워 넣을 때 실수로 중복 배정하면
        보드가 이상하게 동작하거나 손상될 수 있으므로 미리 잡는다.
        """
        seen: dict[int, str] = {}
        problems: list[str] = []
        for name, value in vars(self).items():
            if value is None:
                continue
            if value in seen:
                problems.append(f"GPIO{value}: {seen[value]} 와 {name} 이 충돌")
            else:
                seen[value] = name
        return problems


#: 현재 핀맵 — 전부 미확인 상태다.
PINS = PinMap()


def hardware_report() -> str:
    """사람이 읽는 하드웨어 현황 보고서.

    `python -m app.hardware.board` 로 출력한다.
    """
    lines: list[str] = []
    add = lines.append

    add("=" * 68)
    add(f"  대상 보드: {BOARD_NAME}")
    add(f"  {BOARD_SOURCE}")
    add("=" * 68)

    add("\n[확인된 사양]")
    for key, spec in SPECS.items():
        if spec.confidence is Confidence.CONFIRMED:
            add(f"  {key:<20} {spec.value}")

    add("\n[정황상 유력하나 미확인]")
    for key, spec in SPECS.items():
        if spec.confidence is Confidence.LIKELY:
            add(f"  {key:<20} {spec.value}")
            add(f"  {'':<20} └ {spec.source}")

    add("\n[확인 안 됨 - 임의로 채우지 않음]")
    for key, spec in SPECS.items():
        if spec.confidence is Confidence.UNKNOWN:
            add(f"  {key:<20} ? ({spec.source})")

    add(f"\n[화면] {SCREEN_WIDTH}x{SCREEN_HEIGHT} (가로 방향)")
    feasible, reason = framebuffer_feasible()
    add(f"  풀 프레임버퍼: {'가능' if feasible else '불가'}")
    add(f"  {reason}")

    missing = PINS.unconfirmed()
    add(f"\n[GPIO 핀] {len(missing)}개 전부 미확인")
    add("  실물 확인 후 app/hardware/board.py 의 PINS를 채우세요.")
    conflicts = PINS.conflicts()
    if conflicts:
        add("  ⚠️ 핀 충돌:")
        for c in conflicts:
            add(f"    {c}")

    add("\n" + "=" * 68)
    return "\n".join(lines)


if __name__ == "__main__":
    from app.core.console import enable_utf8_console

    enable_utf8_console()
    print(hardware_report())
