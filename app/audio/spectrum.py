"""주파수 스펙트럼 분석.

오디오 샘플 블록 → 대역별 레벨(0.0~1.0) 변환.

이 모듈은 **오디오 장치와 무관한 순수 계산**이라 단독으로 검증할 수 있다.
(주파수를 아는 합성 신호를 넣어 해당 대역만 반응하는지 확인)

시각화가 자연스럽게 보이려면 두 가지가 핵심이다.

1. **로그 간격 대역** — 사람의 청각은 로그 스케일이다.
   선형으로 나누면 20~20000Hz에서 첫 막대 하나에 베이스가 전부 몰리고
   나머지 막대는 거의 움직이지 않는다.

2. **dB(로그) 진폭** — 음압도 로그다.
   선형 진폭을 그대로 쓰면 큰 소리에서만 막대가 튀고 평소엔 바닥에 붙어 있다.
"""

from __future__ import annotations

import numpy as np

#: 기본 대역 수
DEFAULT_BANDS = 28

#: 분석 주파수 범위 (Hz). 20Hz 미만은 들리지 않고, 16kHz 이상은 대부분 비어 있다.
MIN_FREQ = 30.0
MAX_FREQ = 16000.0

#: dB 정규화 범위 (가장 큰 대역을 0dB로 본 상대값).
#:
#: 천장을 -10dB로 두면 "가장 큰 대역보다 10dB 이내인 대역"이 전부 1.0이 된다.
#: 음악은 대부분의 대역이 그 안에 들어와서 막대가 죄다 천장에 붙고
#: 음악의 구조가 보이지 않는다 (실측으로 확인).
#: 천장을 0dB(= 최대 대역만 꽉 참)로 올리고 바닥을 -55dB로 넓혀
#: 대역 간 차이가 높이 차이로 드러나게 한다.
DB_FLOOR = -55.0
DB_CEIL = 0.0


class SpectrumAnalyzer:
    """샘플 블록을 받아 대역별 레벨을 만든다.

    상태를 가진다(이전 값 기반 스무딩). 스레드 하나에서만 호출해야 한다.
    """

    def __init__(
        self,
        *,
        band_count: int = DEFAULT_BANDS,
        samplerate: int = 48000,
        fft_size: int = 4096,
        attack: float = 0.55,
        decay: float = 0.12,
    ) -> None:
        """
        Args:
            band_count: 만들 막대 개수.
            samplerate: 입력 샘플레이트.
            fft_size:   FFT 창 크기. 클수록 저음 해상도가 좋지만 반응이 느려진다.
                        4096 @ 48kHz = 빈 11.7Hz, 창 85ms. 시각화에는 충분히 즉각적이다.
            attack:     레벨이 올라갈 때의 추종 속도(0~1). 크면 즉각적.
            decay:      레벨이 내려갈 때의 추종 속도(0~1). 작으면 천천히 떨어진다.
                        attack > decay 여야 타악기가 '탁' 튀고 부드럽게 가라앉는다.
        """
        self.band_count = band_count
        self.samplerate = samplerate
        self.fft_size = fft_size
        self._attack = attack
        self._decay = decay

        self._window = np.hanning(fft_size).astype(np.float32)
        self._freqs = np.fft.rfftfreq(fft_size, 1.0 / samplerate)
        self._band_slices = self._build_bands()
        self._levels = np.zeros(band_count, dtype=np.float32)

        # 자동 게인용 최근 최대값. 조용한 곡에서도 막대가 살아 있게 한다.
        self._running_max = 1e-4

    # -- 대역 경계 ----------------------------------------------------------

    def _build_bands(self) -> list[np.ndarray]:
        """FFT 빈(bin)을 대역에 **겹치지 않게** 배정한다.

        로그 간격 경계를 기준으로 삼되, 대역끼리 같은 빈을 공유하지 않게 한다.

        왜 단순 로그 분할로는 안 되는가:
            48kHz / 2048샘플 = 빈 하나가 23.4Hz다.
            그런데 30Hz~16kHz를 28개 로그 대역으로 나누면
            맨 아래 대역의 폭은 1~2Hz에 불과하다.
            즉 저음 대역 여러 개가 **같은 빈 하나**를 읽게 되고,
            베이스 한 음에 막대 7개가 통째로 똑같이 치솟는다.

        해결:
            빈을 왼쪽부터 순서대로 나눠 주고, 각 대역이 최소 1개의 빈을
            독점하도록 보장한다. 결과적으로 저음부는 자연스럽게 선형에 가깝게,
            고음부는 로그 간격으로 배치된다. 실제 스펙트럼 애널라이저가
            쓰는 방식이며 막대가 서로 구분되어 움직인다.
        """
        edges = np.logspace(
            np.log10(MIN_FREQ), np.log10(MAX_FREQ), self.band_count + 1
        )
        bin_count = self._freqs.size
        slices: list[np.ndarray] = []

        # 0번 빈은 DC(0Hz) 성분이라 음악 정보가 없다. 1번부터 시작한다.
        cursor = 1

        for i in range(self.band_count):
            # 이 대역의 상한 주파수에 해당하는 빈까지 가져간다.
            end = int(np.searchsorted(self._freqs, edges[i + 1], side="left"))

            # 남은 대역 수만큼은 빈을 남겨 둬야 뒤쪽이 빈손이 되지 않는다.
            remaining_bands = self.band_count - i - 1
            end = min(end, bin_count - remaining_bands)

            # 최소 1개는 독점한다.
            end = max(end, cursor + 1)
            end = min(end, bin_count)

            start = min(cursor, bin_count - 1)
            if end <= start:
                end = start + 1

            slices.append(np.arange(start, end))
            cursor = end

        return slices

    def band_frequencies(self) -> list[float]:
        """각 대역의 중심 주파수(Hz). 디버깅/검증용."""
        return [float(self._freqs[idx].mean()) for idx in self._band_slices]

    # -- 분석 ---------------------------------------------------------------

    def analyze(self, samples: np.ndarray) -> np.ndarray:
        """샘플 블록에서 대역 레벨을 계산하고 스무딩해 반환한다.

        Args:
            samples: 모노 float 샘플 (-1.0 ~ 1.0). 길이는 무관.

        Returns:
            0.0~1.0 범위의 band_count 길이 배열. (내부 버퍼의 복사본이 아님에 주의)
        """
        raw = self._raw_bands(samples)
        return self._smooth(raw)

    def _raw_bands(self, samples: np.ndarray) -> np.ndarray:
        """스무딩 전의 대역 레벨."""
        samples = np.asarray(samples, dtype=np.float32).ravel()

        if samples.size == 0:
            return np.zeros(self.band_count, dtype=np.float32)

        # 창 크기에 맞춘다. 짧으면 0으로 채우고, 길면 가장 최근 구간을 쓴다.
        if samples.size < self.fft_size:
            block = np.zeros(self.fft_size, dtype=np.float32)
            block[-samples.size :] = samples
        else:
            block = samples[-self.fft_size :]

        # 완전 무음이면 계산을 건너뛴다 (log(0) 회피 + CPU 절약)
        peak = float(np.max(np.abs(block)))
        if peak < 1e-7:
            return np.zeros(self.band_count, dtype=np.float32)

        spectrum = np.abs(np.fft.rfft(block * self._window))

        # 대역별 대표값: 평균보다 최대값이 타악기 반응이 또렷하다.
        values = np.array(
            [float(spectrum[idx].max()) for idx in self._band_slices],
            dtype=np.float32,
        )

        # 자동 게인 — 최근 최대값을 천천히 따라가며 기준을 맞춘다.
        current_max = float(values.max())
        if current_max > self._running_max:
            self._running_max = current_max          # 커질 땐 즉시
        else:
            self._running_max *= 0.995               # 작아질 땐 서서히
        self._running_max = max(self._running_max, 1e-5)

        normalized = values / self._running_max

        # dB 변환 후 0~1로 정규화
        db = 20.0 * np.log10(np.maximum(normalized, 1e-6))
        level = (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)
        return np.clip(level, 0.0, 1.0).astype(np.float32)

    def _smooth(self, target: np.ndarray) -> np.ndarray:
        """올라갈 땐 빠르게, 내려갈 땐 천천히 따라간다."""
        rising = target > self._levels
        rate = np.where(rising, self._attack, self._decay).astype(np.float32)
        self._levels += (target - self._levels) * rate
        # 부동소수 잔차가 쌓여 아주 작은 값이 영원히 남는 것을 막는다.
        self._levels[self._levels < 0.001] = 0.0
        return self._levels

    def reset(self) -> None:
        """레벨과 게인을 초기화한다. 곡이 바뀌거나 정지했을 때 호출."""
        self._levels[:] = 0.0
        self._running_max = 1e-4

    def decay_to_silence(self) -> np.ndarray:
        """입력 없이 한 스텝 감쇠시킨다. 일시정지 시 부드럽게 가라앉히는 용도."""
        return self._smooth(np.zeros(self.band_count, dtype=np.float32))


def to_mono(frames: np.ndarray) -> np.ndarray:
    """다채널 프레임을 모노로 합친다.

    soundcard는 (프레임수, 채널수) 모양을 준다.
    """
    frames = np.asarray(frames, dtype=np.float32)
    if frames.ndim == 1:
        return frames
    return frames.mean(axis=1)
