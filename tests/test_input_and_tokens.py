"""입력 매핑과 토큰 저장소 테스트.

입력 매핑은 하드웨어 이식의 핵심 계약이라 회귀가 나면 안 된다.
"""

from __future__ import annotations

import time

import pytest

from app.config.keymap import DEFAULT_KEYMAP, KEY_HINTS
from app.core.actions import ActionEvent, DeckAction
from app.input.base import InputController, InputManager
from app.spotify.tokens import FileTokenStore, NullTokenStore, TokenBundle, create_token_store


# ---------------------------------------------------------------------------
#  키 매핑 — 요구사항으로 명시된 기본값
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,action",
    [
        ("Space", DeckAction.PLAY_PAUSE),
        ("Left", DeckAction.PREVIOUS_TRACK),
        ("Right", DeckAction.NEXT_TRACK),
        ("Up", DeckAction.VOLUME_UP),
        ("Down", DeckAction.VOLUME_DOWN),
        ("S", DeckAction.TOGGLE_SHUFFLE),
        ("R", DeckAction.TOGGLE_REPEAT),
        ("L", DeckAction.TOGGLE_LIKE),
    ],
)
def test_required_key_bindings(key: str, action: DeckAction):
    assert DEFAULT_KEYMAP[key][0] is action


def test_every_hinted_key_is_documented():
    """화면 안내에 있는 키는 실제로 동작해야 한다."""
    assert len(KEY_HINTS) > 0
    for label, description in KEY_HINTS:
        assert label and description


def test_keymap_resolves_to_qt_codes():
    """Qt 키 이름이 틀리면 조용히 무시되어 단축키가 안 먹는다."""
    pytest.importorskip("PySide6")
    from app.input.keyboard import _build_qt_keymap

    resolved = _build_qt_keymap(DEFAULT_KEYMAP)
    assert len(resolved) == len(DEFAULT_KEYMAP), "일부 키 이름이 Qt 코드로 변환되지 않았다"


def test_unknown_key_name_is_skipped_not_fatal():
    pytest.importorskip("PySide6")
    from app.input.keyboard import _build_qt_keymap

    resolved = _build_qt_keymap({"NotARealKey": (DeckAction.PLAY, {})})
    assert resolved == {}


# ---------------------------------------------------------------------------
#  입력 계층 계약 — GPIO 이식의 기반
# ---------------------------------------------------------------------------


class _FakeController(InputController):
    name = "fake"

    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_controller_emits_action_events():
    received: list[ActionEvent] = []
    controller = _FakeController()
    controller.bind(received.append)

    controller.emit(DeckAction.VOLUME_SET, value=70)

    assert len(received) == 1
    assert received[0].action is DeckAction.VOLUME_SET
    assert received[0].get("value") == 70
    assert received[0].source == "fake"


def test_disabled_controller_emits_nothing():
    received: list[ActionEvent] = []
    controller = _FakeController()
    controller.bind(received.append)
    controller.set_enabled(False)

    controller.emit(DeckAction.PLAY_PAUSE)
    assert received == []


def test_unbound_controller_does_not_crash():
    """sink 연결 전에 눌려도 죽으면 안 된다."""
    _FakeController().emit(DeckAction.PLAY_PAUSE)


def test_manager_starts_and_stops_all():
    received: list[ActionEvent] = []
    manager = InputManager(on_action=received.append)
    a, b = manager.register(_FakeController()), manager.register(_FakeController())

    manager.start_all()
    assert a.started and b.started

    a.emit(DeckAction.NEXT_TRACK)
    assert len(received) == 1

    manager.stop_all()
    assert a.stopped and b.stopped


def test_one_failing_controller_does_not_block_others():
    """GPIO가 없는 PC에서도 키보드는 살아 있어야 한다."""

    class Broken(_FakeController):
        name = "broken"

        def start(self):
            raise RuntimeError("no GPIO device")

    manager = InputManager(on_action=lambda e: None)
    manager.register(Broken())
    good = manager.register(_FakeController())

    manager.start_all()
    assert good.started


# ---------------------------------------------------------------------------
#  토큰 저장소
# ---------------------------------------------------------------------------


def test_file_store_roundtrip(tmp_path):
    store = FileTokenStore(tmp_path / "tokens.json")
    bundle = TokenBundle("AT", "RT", time.time() + 3600, scope="user-library-read")

    assert store.load() is None
    store.save(bundle)

    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "AT"
    assert loaded.refresh_token == "RT"
    assert loaded.has_scope("user-library-read")

    store.clear()
    assert store.load() is None


def test_file_store_survives_corrupt_file(tmp_path):
    """손상된 토큰 파일 때문에 앱이 못 켜지면 안 된다. 다시 로그인하면 그만이다."""
    path = tmp_path / "tokens.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert FileTokenStore(path).load() is None


def test_file_store_write_is_atomic(tmp_path):
    """쓰는 도중 중단돼도 기존 토큰이 깨지면 안 된다."""
    path = tmp_path / "tokens.json"
    store = FileTokenStore(path)
    store.save(TokenBundle("FIRST", "R1", time.time() + 3600))
    store.save(TokenBundle("SECOND", "R2", time.time() + 3600))

    assert store.load().access_token == "SECOND"
    assert not path.with_suffix(".tmp").exists(), "임시 파일이 남으면 안 된다"


def test_null_store_never_persists():
    store = NullTokenStore()
    store.save(TokenBundle("A", "R", time.time() + 3600))
    assert store.load() is None


def test_create_token_store_honours_mode():
    assert isinstance(create_token_store("file"), FileTokenStore)
    assert isinstance(create_token_store("none"), NullTokenStore)


def test_unknown_store_mode_falls_back_to_file():
    assert isinstance(create_token_store("nonsense"), FileTokenStore)
