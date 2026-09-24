"""PC ↔ ESP32 공유 계약을 C++ 헤더와 JSON으로 내보낸다.

실행:
    python tools/export_contract.py          생성
    python tools/export_contract.py --check  최신인지 확인만 (CI/테스트용)

생성물:
    contract/deck_contract.json       기계가 읽는 정의
    esp32/include/deck_contract.h     ESP32 펌웨어가 include

**생성물을 손으로 고치지 마라.** app/core/contract.py를 고치고 다시 실행한다.
tests/test_contract.py가 최신 여부를 검사하므로, 잊으면 테스트가 실패한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.contract import (  # noqa: E402
    CONTRACT_VERSION,
    contract_descriptor,
)

JSON_PATH = ROOT / "contract" / "deck_contract.json"
HEADER_PATH = ROOT / "esp32" / "include" / "deck_contract.h"

BANNER = "자동 생성 파일 - 직접 수정하지 마세요"


def build_json() -> str:
    return json.dumps(contract_descriptor(), indent=2, ensure_ascii=False) + "\n"


def build_header() -> str:
    """ESP32 펌웨어용 C++ 헤더를 만든다.

    Arduino/ESP-IDF 양쪽에서 쓸 수 있도록 표준 타입만 사용한다.
    """
    spec = contract_descriptor()
    lines: list[str] = []
    add = lines.append

    add("// " + "=" * 72)
    add(f"//  Spotify Deck - 공유 계약 v{CONTRACT_VERSION}")
    add(f"//  {BANNER}")
    add("//")
    add("//  생성: python tools/export_contract.py")
    add("//  원본: app/core/contract.py")
    add("//")
    add("//  이 파일은 PC(Python)와 ESP32(C++)가 같은 개념을")
    add("//  같은 이름·같은 값으로 쓰게 하기 위해 자동 생성된다.")
    add("// " + "=" * 72)
    add("")
    add("#pragma once")
    add("")
    add("#include <stdint.h>")
    add("")
    add(f"#define DECK_CONTRACT_VERSION {CONTRACT_VERSION}")
    add("")

    # --- 액션 ---
    add("// 사용자가 요청할 수 있는 동작.")
    add("// 물리 버튼, 로터리 엔코더, 터치, 키보드 모두 이 값을 내보낸다.")
    add("//")
    add("// ⚠️ 숫자를 바꾸지 마라. 펌웨어에 구워진 값과 어긋나면")
    add("//    버튼이 엉뚱한 동작을 한다. 새 액션은 끝에 추가한다.")
    add("enum class DeckAction : uint8_t {")
    for item in spec["actions"]:
        add(f"    {item['name']:<16} = {item['code']:>2},")
    add("};")
    add("")
    add(f"constexpr uint8_t DECK_ACTION_COUNT = {len(spec['actions'])};")
    add("")

    # --- 반복 모드 ---
    add("// 반복 모드. 토글 순서는 OFF -> CONTEXT -> TRACK -> OFF.")
    add("enum class RepeatMode : uint8_t {")
    for item in spec["repeat_modes"]:
        add(f"    {item['name']:<10} = {item['code']},")
    add("};")
    add("")

    # --- 상수 ---
    add("// 값을 알 수 없을 때 쓰는 표식 (C++에는 Python의 None이 없다)")
    for name, value in spec["constants"].items():
        ctype = "int8_t" if value < 0 else "uint8_t"
        add(f"constexpr {ctype} {name} = {value};")
    add("")

    # --- 재생 상태 ---
    add("// UI가 그리는 재생 상태.")
    add("// 화면은 이 구조체만 보고 그린다. Spotify API를 직접 알지 못한다.")
    add("//")
    add("// 문자열은 고정 길이 버퍼다. ESP32는 힙 단편화를 피해야 하므로")
    add("// 동적 할당 대신 정해진 크기를 쓰고, 넘치면 UI에서 말줄임 처리한다.")
    add("struct PlaybackState {")
    for field in spec["playback_fields"]:
        note = f"  // {field['note']}" if field["note"] else ""
        if field["ctype"] == "char[]":
            add(f"    char {field['name']}[{field['max_len']}];{note}")
        else:
            add(f"    {field['ctype']} {field['name']};{note}")
    add("};")
    add("")

    # --- 편의 함수 ---
    add("// 액션 이름 (로그/디버깅용)")
    add("inline const char* deckActionName(DeckAction action) {")
    add("    switch (action) {")
    for item in spec["actions"]:
        add(f"        case DeckAction::{item['name']}: return \"{item['value']}\";")
    add("        default: return \"unknown\";")
    add("    }")
    add("}")
    add("")

    return "\n".join(lines)


def write(path: Path, content: str) -> bool:
    """내용이 바뀐 경우에만 쓴다. 바뀌었으면 True."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="공유 계약 내보내기")
    parser.add_argument(
        "--check",
        action="store_true",
        help="생성하지 않고 최신 여부만 확인한다 (다르면 종료코드 1)",
    )
    args = parser.parse_args()

    targets = [(JSON_PATH, build_json()), (HEADER_PATH, build_header())]

    if args.check:
        stale = [
            path
            for path, content in targets
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            print("생성물이 오래되었습니다:")
            for path in stale:
                print(f"  {path.relative_to(ROOT)}")
            print("\n  python tools/export_contract.py  를 실행해 주세요.")
            return 1
        print(f"계약 v{CONTRACT_VERSION} - 생성물이 최신입니다.")
        return 0

    for path, content in targets:
        changed = write(path, content)
        mark = "갱신" if changed else "변경 없음"
        print(f"  [{mark}] {path.relative_to(ROOT)}")

    print(f"\n계약 v{CONTRACT_VERSION} 내보내기 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
