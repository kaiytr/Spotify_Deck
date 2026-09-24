"""앨범 아트 관리 — UI 상태와 분리.

왜 분리하는가:
    PlaybackState는 **URL만** 들고 있고 이미지 자체는 들고 있지 않다.
    이미지는 크고, 비동기로 오고, 플랫폼마다 표현이 완전히 다르다.

        PC     : QPixmap (수 MB, 힙 여유 충분)
        ESP32  : RGB565 바이트 배열 (수십 KB, 힙이 빠듯)

    상태와 이미지를 한 덩어리로 묶으면 ESP32에서 상태를 복사할 때마다
    이미지까지 복사하게 되고, 520KB SRAM에서는 바로 터진다.

    그래서 상태는 가볍게 URL만, 이미지는 별도 저장소가 관리한다.

        PlaybackState.album_art_url  ──요청──>  ArtworkSource  ──>  이미지
             (문자열 256B)                      (플랫폼별 구현)

ESP32 파이프라인 (향후):
    URL → HTTPS GET → JPEG 스트리밍 디코드 → 축소 → RGB565 → 화면
    PC처럼 원본을 통째로 메모리에 올릴 수 없으므로 스트리밍이 필수다.
    아래 ArtworkSpec이 "얼마나 줄여야 하는지"를 계산한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Spotify가 주는 앨범 아트 원본 크기 (가장 큰 것)
SPOTIFY_MAX_EDGE = 640

#: RGB565 = 픽셀당 2바이트
BYTES_PER_PIXEL_RGB565 = 2


@dataclass(frozen=True)
class ArtworkSpec:
    """앨범 아트를 어느 크기로 준비할지.

    화면 크기에서 계산한다. 화면에 150px로 그릴 것을 640px로 받아 두면
    ESP32에서는 메모리 낭비가 아니라 **아예 불가능**하다.
    """

    edge: int
    """정사각형 한 변 (픽셀)."""

    @property
    def pixel_count(self) -> int:
        return self.edge * self.edge

    @property
    def rgb565_bytes(self) -> int:
        """디코딩된 이미지를 담는 데 필요한 바이트 (ESP32 기준)."""
        return self.pixel_count * BYTES_PER_PIXEL_RGB565

    @property
    def scale_from_source(self) -> float:
        """Spotify 원본 대비 축소 비율."""
        return self.edge / SPOTIFY_MAX_EDGE

    def describe(self) -> str:
        return (
            f"{self.edge}x{self.edge} "
            f"({self.rgb565_bytes // 1024}KB RGB565, "
            f"원본의 {self.scale_from_source:.0%})"
        )


def spec_for_display(art_widget_edge: int, *, oversample: float = 1.0) -> ArtworkSpec:
    """화면에 그릴 크기에서 준비할 이미지 크기를 정한다.

    Args:
        art_widget_edge: 앨범 아트를 그릴 정사각형 한 변 (논리 픽셀).
        oversample: 고해상도 화면 대비 배율. PC는 1.5~2.0이 보기 좋고,
            ESP32는 메모리가 없으므로 1.0을 쓴다.

    Returns:
        요청할 이미지 크기. Spotify 원본(640)을 넘지 않는다.
    """
    edge = int(art_widget_edge * oversample)
    return ArtworkSpec(edge=max(64, min(edge, SPOTIFY_MAX_EDGE)))


@runtime_checkable
class ArtworkSource(Protocol):
    """앨범 아트 공급자.

    UI는 "이 URL의 이미지를 이 크기로 달라"고만 요청한다.
    다운로드 · 디코딩 · 캐싱 · 축소를 어떻게 하는지는 구현이 정한다.

    PC   : app/ui/widgets/album_art.py 가 QPixmap으로 구현 (스레드풀 + LRU 캐시)
    ESP32: 향후 JPEG 스트리밍 디코더로 구현 (한 장만 보관, 캐시 없음)
    """

    def request(self, url: str | None, spec: ArtworkSpec) -> None:
        """이미지를 준비하라고 알린다. 즉시 반환해야 한다(블로킹 금지).

        준비가 끝나면 구현이 정한 방식으로 알린다 (PC는 Qt 시그널).
        같은 URL을 다시 요청하면 아무 일도 하지 않아야 한다.
        """
        ...

    def clear(self) -> None:
        """현재 이미지를 버린다 (재생 중지 등)."""
        ...


# ---------------------------------------------------------------------------
#  ESP32 메모리 견적
# ---------------------------------------------------------------------------


def esp32_memory_report(
    art_edge: int,
    *,
    screen: tuple[int, int] = (480, 320),
    usable_heap_bytes: int = 180 * 1024,
) -> str:
    """앨범 아트가 ESP32 메모리에 들어가는지 따져 본다.

    이 계산이 "앨범 아트를 몇 픽셀로 받을지"를 결정한다.
    실물 없이도 설계 단계에서 판단할 수 있어야 한다.

    Args:
        art_edge: 앨범 아트를 그릴 한 변.
        screen: 화면 크기.
        usable_heap_bytes: WiFi/TLS 스택을 제외하고 남는 힙 추정치.
    """
    spec = ArtworkSpec(art_edge)
    lines: list[str] = []
    add = lines.append

    full_fb = screen[0] * screen[1] * BYTES_PER_PIXEL_RGB565
    # JPEG 디코더 작업 메모리 (tjpgd 기준 경험값) + HTTPS 수신 버퍼
    decoder_work = 4 * 1024
    tls_buffer = 16 * 1024

    add(f"  앨범 아트 {spec.describe()}")
    add(f"  {'':2}디코딩 결과 보관   {spec.rgb565_bytes // 1024:>4}KB")
    add(f"  {'':2}JPEG 디코더 작업   {decoder_work // 1024:>4}KB")
    add(f"  {'':2}TLS 수신 버퍼      {tls_buffer // 1024:>4}KB")
    total = spec.rgb565_bytes + decoder_work + tls_buffer
    add(f"  {'':2}{'합계':<16} {total // 1024:>4}KB  / 가용 {usable_heap_bytes // 1024}KB")

    if total > usable_heap_bytes:
        add(f"  → 불가. 한 변을 줄이거나 스트립 단위로 디코드해 바로 화면에 밀어야 한다.")
    else:
        margin = usable_heap_bytes - total
        add(f"  → 가능 (여유 {margin // 1024}KB)")

    add("")
    add(f"  참고: 풀 프레임버퍼 {screen[0]}x{screen[1]} = {full_fb // 1024}KB")
    if full_fb > usable_heap_bytes:
        add("        → 전체 화면 버퍼는 불가. 부분 갱신 필수.")

    return "\n".join(lines)


if __name__ == "__main__":
    from app.core.console import enable_utf8_console

    enable_utf8_console()

    print("=" * 62)
    print("  ESP32 앨범 아트 메모리 견적 (480x320 화면)")
    print("=" * 62)
    for edge in (240, 175, 128, 96):
        print()
        print(esp32_memory_report(edge))
