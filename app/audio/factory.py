"""웨이브 소스 선택 및 자동 전환.

토큰 저장소(keyring → 파일 폴백)와 같은 패턴이다.
쓸 수 있으면 좋은 쪽을 쓰고, 안 되면 조용히 대체 구현으로 넘어간다.
앱 코드는 어느 쪽이 쓰이는지 신경 쓰지 않는다.
"""

from __future__ import annotations

import logging

import numpy as np

from app.audio.base import WaveSource
from app.audio.simulated import SimulatedWaveSource
from app.audio.spectrum import DEFAULT_BANDS

logger = logging.getLogger(__name__)

#: 실시간↔시뮬레이션 전환에 걸리는 시간(프레임 단위 혼합 비율).
#: 급격히 바뀌면 화면이 튀므로 서서히 섞는다.
BLEND_RATE = 0.06


class AutoWaveSource(WaveSource):
    """실시간 캡처를 우선하되, 소리가 없으면 시뮬레이션으로 넘어간다.

    전환이 필요한 실제 상황:
        * 폰으로 재생 중 -> 이 PC는 무음 -> 시뮬레이션
        * PC로 재생 전환 -> 소리 감지 -> 실시간으로 복귀
        * 이어폰 연결/해제로 장치가 바뀜 -> 재연결하는 동안 시뮬레이션

    두 소스를 동시에 돌려 두고 출력만 섞는다.
    시뮬레이션은 계산이 매우 가벼워(사인파 몇 개) 부담이 없다.
    """

    name = "auto"

    def __init__(self, live: WaveSource, fallback: WaveSource) -> None:
        super().__init__(live.band_count)
        self._live = live
        self._fallback = fallback
        #: 0.0 = 시뮬레이션, 1.0 = 실시간. 그 사이는 혼합.
        self._blend = 0.0
        self._playing = False

    def start(self) -> None:
        self._live.start()
        self._fallback.start()

    def stop(self) -> None:
        self._live.stop()
        self._fallback.stop()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self._live.set_playing(playing)
        self._fallback.set_playing(playing)

    def levels(self) -> np.ndarray:
        live_ok = self._live.is_live

        target = 1.0 if live_ok else 0.0
        self._blend += (target - self._blend) * BLEND_RATE

        if self._blend > 0.995:
            return self._live.levels()
        if self._blend < 0.005:
            return self._fallback.levels()

        # 전환 구간: 두 결과를 섞어 부드럽게 넘어간다.
        return (
            self._live.levels() * self._blend
            + self._fallback.levels() * (1.0 - self._blend)
        ).astype(np.float32)

    @property
    def is_live(self) -> bool:
        return self._blend > 0.5

    @property
    def status_text(self) -> str:
        """지금 막대가 무엇을 근거로 움직이는지 설명한다.

        '소리가 없다'는 사실만으로는 원인을 알 수 없다 — 일시정지일 수도,
        볼륨 0일 수도, 다른 기기에서 재생 중일 수도 있다.
        그래서 Spotify의 재생 상태를 함께 보고 판단한다.
        (둘 다 모르면 단정하지 않고 '시뮬레이션'이라고만 한다)
        """
        if self.is_live:
            return "실시간 오디오"

        if not getattr(self._live, "is_capturing", False):
            # 오디오 장치를 열지 못했다. 캡처 자체가 불가능한 환경.
            return "시뮬레이션"

        if self._playing:
            # Spotify는 재생 중인데 이 PC에서는 소리가 안 난다.
            return "다른 기기에서 재생 중"

        return "대기 중"


def create_wave_source(
    band_count: int = DEFAULT_BANDS,
    *,
    mode: str = "auto",
) -> WaveSource:
    """설정에 맞는 웨이브 소스를 만든다.

    Args:
        band_count: 막대 개수.
        mode: "auto"   - 실시간 캡처를 시도하고 안 되면 시뮬레이션 (기본)
              "live"   - 실시간 캡처 강제 (불가하면 시뮬레이션으로 폴백 + 경고)
              "simulated" - 시뮬레이션 강제
              "off"    - 비활성 (웨이브 바 숨김)
    """
    mode = (mode or "auto").lower()

    if mode == "off":
        return None  # type: ignore[return-value]

    if mode == "simulated":
        logger.debug("웨이브: 시뮬레이션 모드")
        return SimulatedWaveSource(band_count)

    # --- 실시간 시도 ---
    from app.audio.loopback import SystemAudioWaveSource, is_available

    if not is_available():
        if mode == "live":
            logger.warning(
                "실시간 오디오 캡처를 사용할 수 없어 시뮬레이션으로 전환합니다. "
                "(soundcard 미설치이거나 루프백 미지원 장치)"
            )
        else:
            logger.info("루프백 캡처 불가 - 시뮬레이션 웨이브를 사용합니다.")
        return SimulatedWaveSource(band_count)

    logger.debug("웨이브: 실시간 캡처 + 시뮬레이션 자동 전환")
    return AutoWaveSource(
        live=SystemAudioWaveSource(band_count),
        fallback=SimulatedWaveSource(band_count),
    )
