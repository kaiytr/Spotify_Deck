// ========================================================================
//  Spotify Deck - 공유 계약 v1
//  자동 생성 파일 - 직접 수정하지 마세요
//
//  생성: python tools/export_contract.py
//  원본: app/core/contract.py
//
//  이 파일은 PC(Python)와 ESP32(C++)가 같은 개념을
//  같은 이름·같은 값으로 쓰게 하기 위해 자동 생성된다.
// ========================================================================

#pragma once

#include <stdint.h>

#define DECK_CONTRACT_VERSION 1

// 사용자가 요청할 수 있는 동작.
// 물리 버튼, 로터리 엔코더, 터치, 키보드 모두 이 값을 내보낸다.
//
// ⚠️ 숫자를 바꾸지 마라. 펌웨어에 구워진 값과 어긋나면
//    버튼이 엉뚱한 동작을 한다. 새 액션은 끝에 추가한다.
enum class DeckAction : uint8_t {
    PLAY_PAUSE       =  0,
    PLAY             =  1,
    PAUSE            =  2,
    NEXT_TRACK       =  3,
    PREVIOUS_TRACK   =  4,
    VOLUME_UP        =  5,
    VOLUME_DOWN      =  6,
    VOLUME_SET       =  7,
    SEEK_SET         =  8,
    SEEK_FORWARD     =  9,
    SEEK_BACKWARD    = 10,
    TOGGLE_SHUFFLE   = 11,
    TOGGLE_REPEAT    = 12,
    TOGGLE_LIKE      = 13,
    REFRESH          = 14,
    QUIT             = 15,
};

constexpr uint8_t DECK_ACTION_COUNT = 16;

// 반복 모드. 토글 순서는 OFF -> CONTEXT -> TRACK -> OFF.
enum class RepeatMode : uint8_t {
    OFF        = 0,
    CONTEXT    = 1,
    TRACK      = 2,
};

// 값을 알 수 없을 때 쓰는 표식 (C++에는 Python의 None이 없다)
constexpr uint8_t VOLUME_UNKNOWN = 255;
constexpr int8_t LIKED_UNKNOWN = -1;

// UI가 그리는 재생 상태.
// 화면은 이 구조체만 보고 그린다. Spotify API를 직접 알지 못한다.
//
// 문자열은 고정 길이 버퍼다. ESP32는 힙 단편화를 피해야 하므로
// 동적 할당 대신 정해진 크기를 쓰고, 넘치면 UI에서 말줄임 처리한다.
struct PlaybackState {
    bool connected;  // Spotify API 연결 상태
    bool has_track;  // 재생 중인 콘텐츠가 있는지
    char title[128];  // 곡 제목
    char artist[128];  // 아티스트 (여러 명이면 ', '로 연결)
    char album[128];  // 앨범명
    char album_art_url[256];  // 앨범 아트 URL (이미지 자체가 아님)
    bool is_playing;  // 재생 중이면 true
    uint32_t progress_ms;  // 현재 재생 위치 (밀리초)
    uint32_t duration_ms;  // 곡 전체 길이 (밀리초)
    uint8_t volume;  // 0~100. 기기가 미지원이면 255
    bool shuffle;
    uint8_t repeat;  // RepeatMode 값 (0=off, 1=context, 2=track)
    int8_t liked;  // 1=좋아요, 0=아님, -1=확인 안 됨
    char device_name[64];  // 재생 중인 기기 이름
    bool supports_volume;  // 기기가 볼륨 조절을 지원하는지
};

// 액션 이름 (로그/디버깅용)
inline const char* deckActionName(DeckAction action) {
    switch (action) {
        case DeckAction::PLAY_PAUSE: return "play_pause";
        case DeckAction::PLAY: return "play";
        case DeckAction::PAUSE: return "pause";
        case DeckAction::NEXT_TRACK: return "next_track";
        case DeckAction::PREVIOUS_TRACK: return "previous_track";
        case DeckAction::VOLUME_UP: return "volume_up";
        case DeckAction::VOLUME_DOWN: return "volume_down";
        case DeckAction::VOLUME_SET: return "volume_set";
        case DeckAction::SEEK_SET: return "seek_set";
        case DeckAction::SEEK_FORWARD: return "seek_forward";
        case DeckAction::SEEK_BACKWARD: return "seek_backward";
        case DeckAction::TOGGLE_SHUFFLE: return "toggle_shuffle";
        case DeckAction::TOGGLE_REPEAT: return "toggle_repeat";
        case DeckAction::TOGGLE_LIKE: return "toggle_like";
        case DeckAction::REFRESH: return "refresh";
        case DeckAction::QUIT: return "quit";
        default: return "unknown";
    }
}
