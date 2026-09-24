"""재생 상태 공급자 인터페이스.

UI가 Spotify를 **직접 알지 못하게** 막는 경계다.

문제:
    이전에는 app/ui/worker.py가 SpotifyPlayer를 직접 import했다.
    UI 계층이 Spotify 구현에 묶여 있으면
      * 테스트할 때 진짜 Spotify 객체를 만들어야 하고
      * ESP32로 옮길 때 UI 코드가 Spotify 클라이언트를 끌고 간다.

해결:
    UI는 "재생 상태를 주는 무언가"만 알면 된다.
    그게 Spotify인지, 목업인지, 나중에 다른 음악 서비스인지는 관심 밖이다.

        [SpotifyPlayer]  ──구현──>  PlaybackSource  <──사용──  [PollWorker/UI]

Protocol을 쓰므로 SpotifyPlayer가 이 클래스를 상속할 필요가 없다.
메서드 모양만 맞으면 된다 (구조적 타이핑).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.spotify.models import PlaybackState


@runtime_checkable
class PlaybackSource(Protocol):
    """재생 상태를 읽어 오는 최소 인터페이스.

    폴링 워커가 필요로 하는 것만 담는다.
    제어(재생/정지/볼륨)는 DeckController를 거치므로 여기 없다.
    """

    def get_state(self, *, with_like: bool = True) -> PlaybackState:
        """현재 재생 상태 스냅샷.

        Raises:
            DeckError 계열만 던져야 한다.
        """
        ...

    def is_saved(self, track_id: str | None) -> bool | None:
        """곡이 보관함에 있는지. 확인 실패 시 None."""
        ...
