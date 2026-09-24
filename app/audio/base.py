"""웨이브 소스 추상 인터페이스.

입력 장치 계층(app/input/base.py)과 같은 철학이다.
UI는 "소리 레벨이 어디서 왔는지" 알 필요가 없고,
`levels()`가 돌려주는 0.0~1.0 배열만 그린다.

    WaveSource (이 파일)
    ├── SystemAudioWaveSource   실제 PC 출력 캡처 (WASAPI 루프백)
    ├── SimulatedWaveSource     캡처 불가 시 대체 애니메이션
    └── AutoWaveSource          둘을 자동 전환

RK3399로 옮길 때는 ALSA 루프백을 읽는 구현 하나만 추가하면 된다.
UI와 Spotify 로직은 수정하지 않는다.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)


class WaveSource(ABC):
    """대역별 소리 레벨 공급자."""

    #: 로그/디버깅용 식별자
    name: str = "wave"

    def __init__(self, band_count: int) -> None:
        self.band_count = band_count

    # -- 수명 주기 ----------------------------------------------------------

    @abstractmethod
    def start(self) -> None:
        """캡처/애니메이션을 시작한다."""

    @abstractmethod
    def stop(self) -> None:
        """자원을 정리한다."""

    # -- 데이터 -------------------------------------------------------------

    @abstractmethod
    def levels(self) -> np.ndarray:
        """현재 대역 레벨 (길이 band_count, 값 0.0~1.0).

        UI 스레드에서 매 프레임 호출되므로 **블로킹하면 안 된다.**
        """

    # -- 힌트 ---------------------------------------------------------------

    def set_playing(self, playing: bool) -> None:
        """Spotify 재생 상태를 알려 준다.

        실제 캡처 소스는 무시해도 되지만(소리로 판단 가능),
        시뮬레이션 소스는 이 값으로 움직임을 켜고 끈다.
        """

    @property
    def is_live(self) -> bool:
        """True면 실제 오디오에 반응 중, False면 시뮬레이션."""
        return False

    @property
    def status_text(self) -> str:
        """UI에 표시할 짧은 상태 문구."""
        return "실시간 오디오" if self.is_live else "시뮬레이션"


def silent(band_count: int) -> np.ndarray:
    """무음 레벨 배열."""
    return np.zeros(band_count, dtype=np.float32)
