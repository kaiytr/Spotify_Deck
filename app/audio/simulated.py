"""시뮬레이션 웨이브 소스.

실제 오디오를 캡처할 수 없을 때 쓰는 대체 구현이다.

  * 폰이나 스마트 스피커로 재생 중 (이 PC에는 소리가 없음)
  * 오디오 장치가 루프백을 지원하지 않음
  * soundcard 패키지 미설치

음악과 동기화되지는 않지만, 재생/일시정지는 정확히 반영하므로
화면이 "죽어 있지 않다"는 느낌을 준다.

여러 개의 서로 다른 주기를 가진 사인파를 겹쳐 규칙성이 눈에 띄지 않게 한다.
(단일 사인파를 쓰면 막대가 좌우로 물결치는 게 티가 나서 금방 질린다)
"""

from __future__ import annotations

import time

import numpy as np

from app.audio.base import WaveSource


class SimulatedWaveSource(WaveSource):
    """재생 상태에 반응하는 가짜 스펙트럼."""

    name = "simulated"

    def __init__(self, band_count: int = 28, *, seed: int = 7) -> None:
        super().__init__(band_count)
        self._playing = False
        self._energy = 0.0          # 0=정지, 1=재생. 부드럽게 전환된다.
        self._levels = np.zeros(band_count, dtype=np.float32)
        self._last_tick = time.monotonic()

        rng = np.random.default_rng(seed)
        # 대역마다 고유한 위상/속도를 줘서 물결이 규칙적으로 보이지 않게 한다.
        self._phase = rng.uniform(0, 2 * np.pi, band_count).astype(np.float32)
        self._speed = rng.uniform(0.7, 2.3, band_count).astype(np.float32)
        self._phase2 = rng.uniform(0, 2 * np.pi, band_count).astype(np.float32)
        self._speed2 = rng.uniform(2.5, 5.5, band_count).astype(np.float32)

        # 저음이 크고 고음이 작은 실제 음악의 평균 스펙트럼 기울기를 흉내 낸다.
        tilt = np.linspace(1.0, 0.35, band_count).astype(np.float32)
        self._tilt = tilt

    def start(self) -> None:
        self._last_tick = time.monotonic()

    def stop(self) -> None:
        pass

    def set_playing(self, playing: bool) -> None:
        self._playing = playing

    def levels(self) -> np.ndarray:
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.1)   # 창 최소화 후 복귀 시 튐 방지
        self._last_tick = now

        # 재생/정지 전환을 0.4초에 걸쳐 부드럽게
        target = 1.0 if self._playing else 0.0
        self._energy += (target - self._energy) * min(1.0, dt * 2.5)

        if self._energy < 0.005:
            self._levels[:] = 0.0
            return self._levels

        t = now
        wave = (
            0.55 + 0.45 * np.sin(self._phase + t * self._speed)
        ) * (
            0.7 + 0.3 * np.sin(self._phase2 + t * self._speed2)
        )

        target_levels = np.clip(wave * self._tilt * self._energy, 0.0, 1.0)

        # 실제 캡처 소스와 비슷한 감쇠감을 준다.
        rising = target_levels > self._levels
        rate = np.where(rising, 0.35, 0.12).astype(np.float32)
        self._levels += (target_levels - self._levels).astype(np.float32) * rate
        return self._levels

    @property
    def is_live(self) -> bool:
        return False
