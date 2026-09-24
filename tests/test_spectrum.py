"""스펙트럼 분석 테스트.

오디오 장치 없이 검증한다. 주파수를 아는 합성 신호를 넣고
해당 대역만 반응하는지 확인하는 방식이라 결과가 결정적이다.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.audio.spectrum import DEFAULT_BANDS, SpectrumAnalyzer, to_mono

SR = 48_000


def tone(freq: float, n: int = 4096, amp: float = 0.5) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * freq * np.arange(n) / SR)).astype(np.float32)


def settle(analyzer: SpectrumAnalyzer, signal: np.ndarray, iterations: int = 40) -> np.ndarray:
    """스무딩이 정상 상태에 도달할 때까지 반복 입력한다."""
    levels = analyzer.analyze(signal)
    for _ in range(iterations - 1):
        levels = analyzer.analyze(signal)
    return levels.copy()


@pytest.fixture
def analyzer() -> SpectrumAnalyzer:
    return SpectrumAnalyzer(samplerate=SR)


# ---------------------------------------------------------------------------
#  대역 배정 — 핵심 회귀 방지
# ---------------------------------------------------------------------------


def test_bands_do_not_share_fft_bins(analyzer):
    """대역이 같은 빈을 공유하면 베이스 한 음에 막대 여러 개가
    **똑같은 높이로** 치솟는다. 실제로 겪은 버그다.
    """
    used: list[int] = []
    for indices in analyzer._band_slices:
        assert set(indices.tolist()).isdisjoint(used), "대역끼리 빈을 공유하면 안 된다"
        used += indices.tolist()


def test_every_band_owns_at_least_one_bin(analyzer):
    assert all(len(idx) >= 1 for idx in analyzer._band_slices)


def test_band_center_frequencies_ascend(analyzer):
    freqs = analyzer.band_frequencies()
    assert all(freqs[i] < freqs[i + 1] for i in range(len(freqs) - 1))


@pytest.mark.parametrize("band_count", [8, 16, 28, 48, 64])
def test_band_allocation_holds_for_any_count(band_count):
    a = SpectrumAnalyzer(band_count=band_count, samplerate=SR)
    used = [b for idx in a._band_slices for b in idx.tolist()]
    assert len(used) == len(set(used))
    assert a.analyze(tone(1000)).shape == (band_count,)


# ---------------------------------------------------------------------------
#  주파수 → 대역 대응
# ---------------------------------------------------------------------------


def test_tones_map_to_ascending_bands():
    """높은 음일수록 오른쪽 막대가 반응해야 한다."""
    peaks = []
    for freq in (60, 250, 1000, 4000, 11000):
        levels = settle(SpectrumAnalyzer(samplerate=SR), tone(freq))
        peaks.append(int(np.argmax(levels)))
    assert peaks == sorted(peaks), f"주파수 순서와 막대 위치가 어긋난다: {peaks}"


@pytest.mark.parametrize("freq", [1000, 4000, 11000])
def test_mid_and_high_tones_are_narrow(freq):
    """중고음은 FFT 해상도가 충분하므로 막대 1~2개만 반응해야 한다."""
    levels = settle(SpectrumAnalyzer(samplerate=SR), tone(freq))
    assert int((levels > 0.3).sum()) <= 3


def test_broadband_signal_lights_all_regions():
    """킥 + 보컬 + 하이햇을 동시에 넣으면 세 구역이 모두 반응한다."""
    a = SpectrumAnalyzer(samplerate=SR)
    levels = settle(a, tone(60, amp=0.6) + tone(800, amp=0.4) + tone(9000, amp=0.3))
    third = DEFAULT_BANDS // 3
    assert levels[:third].max() > 0.3
    assert levels[third : 2 * third].max() > 0.3
    assert levels[2 * third :].max() > 0.3


def test_music_like_input_does_not_saturate():
    """천장에 다 붙으면 음악 구조가 안 보인다. 실제로 겪은 버그다.

    (이전 dB 범위 -70~-10에서는 28개 중 24개가 포화됐고,
     실제 음악에서도 막대가 모두 천장에 붙어 뭉개졌다)

    신호는 **음조가 뚜렷한** 소리여야 한다.
    광대역 잡음은 원래 모든 대역의 에너지가 비슷해서
    막대가 고르게 나오는 것이 정상이므로 이 검사에 쓸 수 없다.
    """
    # 베이스 음 + 그 배음 + 중음대 코드 + 약한 고음 (실제 음악의 구조)
    signal = (
        tone(55, amp=0.90)      # 베이스 기음
        + tone(110, amp=0.55)   # 2배음
        + tone(220, amp=0.30)   # 4배음
        + tone(440, amp=0.35)   # 코드 근음
        + tone(554, amp=0.28)   # 3도
        + tone(659, amp=0.25)   # 5도
        + tone(2_600, amp=0.10)  # 존재감(presence)
        + tone(9_000, amp=0.04)  # 하이햇 영역
    )
    signal = (signal / np.max(np.abs(signal))).astype(np.float32)

    levels = settle(SpectrumAnalyzer(samplerate=SR), signal * 0.5)

    assert int((levels > 0.95).sum()) <= 6, "대부분의 막대가 천장에 붙으면 안 된다"
    assert float(levels.std()) > 0.15, "대역 간 높이 차이가 있어야 음악 구조가 보인다"
    assert levels[:6].mean() > levels[-6:].mean(), "저음이 고음보다 커야 자연스럽다"


# ---------------------------------------------------------------------------
#  무음과 감쇠
# ---------------------------------------------------------------------------


def test_silence_gives_zero(analyzer):
    assert float(settle(analyzer, np.zeros(4096, dtype=np.float32)).max()) == 0.0


def test_decays_gradually_not_instantly(analyzer):
    """일시정지 시 막대가 뚝 꺼지면 어색하다."""
    settle(analyzer, tone(1000))
    steps = 0
    while float(analyzer._levels.max()) > 0.01 and steps < 500:
        analyzer.decay_to_silence()
        steps += 1
    assert 5 < steps < 300, f"감쇠가 너무 빠르거나 느리다: {steps}스텝"


def test_attack_is_faster_than_decay():
    """타악기가 '탁' 튀고 부드럽게 가라앉는 느낌의 근거."""
    rising = SpectrumAnalyzer(samplerate=SR)
    rising.analyze(np.zeros(4096, dtype=np.float32))
    up = float(rising.analyze(tone(1000)).max())

    falling = SpectrumAnalyzer(samplerate=SR)
    settle(falling, tone(1000))
    before = float(falling._levels.max())
    down = before - float(falling.decay_to_silence().max())

    assert up > down


def test_reset_clears_state(analyzer):
    settle(analyzer, tone(1000))
    analyzer.reset()
    assert float(analyzer._levels.max()) == 0.0


def test_quiet_input_still_registers():
    """자동 게인 덕분에 조용한 곡에서도 막대가 살아 있어야 한다."""
    levels = settle(SpectrumAnalyzer(samplerate=SR), tone(1000, amp=0.02))
    assert float(levels.max()) > 0.5


# ---------------------------------------------------------------------------
#  입력 내성
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signal",
    [
        np.array([], dtype=np.float32),
        tone(440, 100),        # FFT 창보다 짧음
        tone(440, 20_000),     # 창보다 김
        np.zeros(4096, dtype=np.float32),
    ],
)
def test_handles_any_input_length(analyzer, signal):
    levels = analyzer.analyze(signal)
    assert levels.shape == (DEFAULT_BANDS,)
    assert np.isfinite(levels).all()
    assert 0.0 <= float(levels.min()) and float(levels.max()) <= 1.0


def test_stereo_is_downmixed():
    stereo = np.stack([tone(440), tone(880)], axis=1)
    mono = to_mono(stereo)
    assert mono.ndim == 1
    assert mono.size == 4096


def test_mono_passthrough():
    mono = tone(440)
    assert to_mono(mono) is mono or np.array_equal(to_mono(mono), mono)
