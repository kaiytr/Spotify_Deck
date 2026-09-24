"""시스템 오디오 루프백 캡처 (실제 소리 반응).

Windows의 WASAPI 루프백을 이용해 **스피커로 나가는 소리를 그대로 읽는다.**
마이크가 아니므로 주변 소음이 섞이지 않고, Spotify가 내는 소리만 정확히 잡힌다.

    [Spotify] -> [Windows 오디오 믹서] -> [스피커]
                          |
                          +-- 루프백 캡처 -> FFT -> 막대

주의할 점:
  * 캡처는 **이 PC에서 재생 중일 때만** 동작한다.
    폰이나 스마트 스피커로 재생하면 이 PC에는 소리가 없으므로 무음이 잡힌다.
    그 경우를 감지해 상위(AutoWaveSource)가 시뮬레이션으로 전환한다.
  * soundcard의 레코더는 **생성한 스레드에서만** 써야 한다 (Windows COM 제약).
    그래서 캡처 스레드 안에서 열고 닫는다.

RK3399(Linux) 이식:
  ALSA의 `snd-aloop` 모듈이나 PulseAudio의 monitor 소스를 쓰면 된다.
  이 클래스와 같은 인터페이스로 구현체 하나만 추가하면 UI는 그대로다.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from app.audio.base import WaveSource
from app.audio.spectrum import SpectrumAnalyzer, to_mono

logger = logging.getLogger(__name__)

#: 한 번에 읽는 프레임 수. 작을수록 반응이 빠르지만 CPU를 더 쓴다.
BLOCK_FRAMES = 1024

#: 캡처 샘플레이트
SAMPLERATE = 48000

#: 이 시간(초) 이상 무음이면 "이 PC에서 재생 중이 아님"으로 판단한다.
SILENCE_TIMEOUT = 1.5

#: 무음 판정 임계값 (피크 진폭)
SILENCE_THRESHOLD = 1e-5

#: 기본 출력 장치가 바뀌었는지 확인하는 주기(초).
#: 헤드폰을 꽂았을 때 1초 안에 새 장치로 따라간다.
DEVICE_CHECK_INTERVAL = 1.0


def _silence_discontinuity_warning(sc) -> None:
    """soundcard의 'data discontinuity in recording' 경고를 끈다.

    무음 구간에서는 Windows가 오디오 버퍼를 채우지 않아
    soundcard가 매 블록마다 이 경고를 낸다.
    초당 수십 줄이 쏟아져 콘솔이 도배되고 정작 필요한 로그가 묻힌다.

    시각화에는 아무 영향이 없는 정보성 경고이므로 이것만 정확히 끈다.
    (warnings.simplefilter("ignore")로 전부 끄면 다른 중요한 경고까지 놓친다)
    """
    import warnings

    warning_type = getattr(sc, "SoundcardRuntimeWarning", None)
    if warning_type is not None:
        warnings.filterwarnings("ignore", category=warning_type)
    else:
        # 버전에 따라 클래스 이름이 노출되지 않을 수 있다. 메시지로 거른다.
        warnings.filterwarnings("ignore", message=".*data discontinuity.*")


def is_available() -> bool:
    """루프백 캡처를 쓸 수 있는 환경인지 빠르게 확인한다."""
    try:
        import soundcard  # noqa: F401
    except ImportError:
        return False
    try:
        import soundcard as sc

        speaker = sc.default_speaker()
        sc.get_microphone(id=str(speaker.name), include_loopback=True)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("루프백 장치를 찾을 수 없습니다: %s", exc)
        return False


class SystemAudioWaveSource(WaveSource):
    """PC 출력 소리를 캡처해 주파수 대역 레벨을 만든다."""

    name = "loopback"

    def __init__(self, band_count: int = 28) -> None:
        super().__init__(band_count)
        self._analyzer = SpectrumAnalyzer(band_count=band_count, samplerate=SAMPLERATE)

        self._levels = np.zeros(band_count, dtype=np.float32)
        self._lock = threading.Lock()

        self._thread: threading.Thread | None = None
        self._running = False

        #: 마지막으로 소리가 있었던 시각 (monotonic)
        self._last_sound = 0.0
        #: 캡처 자체가 동작 중인지 (장치 오류 시 False)
        self._capturing = False

    # -- 수명 주기 ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="audio-loopback"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    # -- 데이터 -------------------------------------------------------------

    def levels(self) -> np.ndarray:
        with self._lock:
            return self._levels.copy()

    @property
    def is_live(self) -> bool:
        """실제 소리를 잡고 있는지.

        캡처는 되지만 무음이 길게 이어지면(= 다른 기기에서 재생 중) False.
        """
        if not self._capturing:
            return False
        return (time.monotonic() - self._last_sound) < SILENCE_TIMEOUT

    @property
    def is_capturing(self) -> bool:
        """오디오 장치를 열고 읽는 중인지 (소리 유무와 무관)."""
        return self._capturing

    # -- 캡처 루프 ----------------------------------------------------------

    def _capture_loop(self) -> None:
        try:
            import soundcard as sc
        except ImportError:
            logger.info("soundcard 패키지가 없어 실시간 오디오를 사용할 수 없습니다.")
            return

        # soundcard는 장치가 사라지면 예외를 던진다. 재연결을 시도한다.
        while self._running:
            try:
                self._capture_once(sc)
            except Exception as exc:  # noqa: BLE001 - 오디오 실패가 앱을 죽이면 안 된다
                self._capturing = False
                logger.debug("오디오 캡처 중단 - 재시도합니다: %s", exc)
                # 장치 전환(이어폰 연결 등) 중일 수 있으니 잠시 후 다시 연다.
                for _ in range(20):
                    if not self._running:
                        return
                    time.sleep(0.1)
            else:
                # 장치 교체로 정상 반환된 경우. 곧바로 새 장치를 연다.
                if self._running:
                    self._analyzer.reset()
                    time.sleep(0.2)

        self._capturing = False

    def _capture_once(self, sc) -> None:
        """장치를 열고 루프백을 읽는다. 오류가 나면 예외를 던져 재연결시킨다.

        기본 출력 장치가 바뀌면(헤드폰 연결/해제, 블루투스 전환 등)
        조용히 반환해 바깥 루프가 새 장치로 다시 열게 한다.
        """
        _silence_discontinuity_warning(sc)

        speaker = sc.default_speaker()
        device_name = str(speaker.name)
        mic = sc.get_microphone(id=device_name, include_loopback=True)

        logger.info("실시간 오디오 캡처 시작: %s", device_name)

        # 롤링 버퍼 — FFT 창 크기만큼 최근 샘플을 유지한다.
        buffer = np.zeros(self._analyzer.fft_size, dtype=np.float32)
        next_device_check = time.monotonic() + DEVICE_CHECK_INTERVAL

        with mic.recorder(samplerate=SAMPLERATE, channels=1, blocksize=BLOCK_FRAMES) as rec:
            self._capturing = True
            self._last_sound = time.monotonic()

            while self._running:
                frames = rec.record(numframes=BLOCK_FRAMES)
                mono = to_mono(frames)

                now = time.monotonic()

                # 기본 출력 장치가 바뀌었는지 주기적으로 확인한다.
                #
                # 실행 중에 헤드폰을 꽂으면 소리는 헤드폰으로 가는데
                # 캡처는 이전 장치(이제 무음)를 계속 읽는다.
                # 그러면 "소리가 없다"고 판단해 시뮬레이션으로 넘어가고,
                # 사용자에게는 막대가 음악과 무관하게 움직이는 것으로 보인다.
                if now >= next_device_check:
                    next_device_check = now + DEVICE_CHECK_INTERVAL
                    try:
                        current = str(sc.default_speaker().name)
                    except Exception:  # noqa: BLE001 - 장치 전환 중이면 다음 주기에 다시 본다
                        current = device_name
                    if current != device_name:
                        logger.info(
                            "출력 장치가 바뀌어 캡처를 다시 엽니다: %s -> %s",
                            device_name,
                            current,
                        )
                        return  # 바깥 루프가 새 장치로 재시작한다

                if mono.size == 0:
                    continue

                # 버퍼를 왼쪽으로 밀고 새 샘플을 뒤에 붙인다.
                n = min(mono.size, buffer.size)
                buffer = np.roll(buffer, -n)
                buffer[-n:] = mono[-n:]

                peak = float(np.max(np.abs(mono)))

                if peak >= SILENCE_THRESHOLD:
                    self._last_sound = now
                    levels = self._analyzer.analyze(buffer)
                else:
                    # 무음이면 계산을 아끼고 부드럽게 가라앉힌다.
                    levels = self._analyzer.decay_to_silence()

                with self._lock:
                    self._levels[:] = levels
