# 🎧 Spotify Deck

Windows PC에서 실행하는 **Spotify 물리 덱 프로토타입**.
최종 목표는 `RK3399 + LCD + 물리 버튼 + 로터리 엔코더` 기반의 실제 하드웨어 제품이며,
이 저장소는 그 UI와 Spotify 제어 로직을 PC에서 먼저 완성하기 위한 단계다.

가짜 데이터를 쓰지 않는다. 실제 Spotify 계정에 연결해 실제로 음악을 제어한다.

---

## 목차

1. [현재 진행 상황](#현재-진행-상황)
2. [빠른 시작](#빠른-시작)
3. [STEP 1 · 개발 환경 설정](#step-1--개발-환경-설정)
4. [STEP 2 · Spotify Developer 설정](#step-2--spotify-developer-설정) ← **사용자가 직접 해야 하는 작업**
5. [STEP 3 · 로그인](#step-3--spotify-oauth-로그인-pkce)
6. [STEP 4~6 · 재생 정보와 제어](#step-46--재생-정보와-제어)
7. [STEP 7~10 · UI와 오류 처리](#step-710--ui와-오류-처리)
8. [STEP 11 · 하드웨어 이식](#step-11--하드웨어-이식-구조)
9. [웨이브 바](#웨이브-바-실시간-오디오-스펙트럼)
9. [조작법](#조작법)
10. [프로젝트 구조](#프로젝트-구조)
11. [문제 해결](#문제-해결)

---

## 현재 진행 상황

| STEP | 내용 | 상태 |
|:---:|---|:---:|
| 1 | 프로젝트 초기화 및 개발 환경 설정 | ✅ 완료 |
| 2 | Spotify Developer 설정 문서화 | ✅ 완료 |
| 3 | Spotify OAuth 로그인 (PKCE) | ✅ 완료 |
| 4 | 현재 재생 정보 가져오기 | ✅ 완료 |
| 5 | 재생 / 일시정지 / 이전 / 다음 | ✅ 완료 |
| 6 | 볼륨 / Shuffle / Repeat / Like | ✅ 완료 |
| 7 | 앨범 아트 및 진행률 UI | ✅ 완료 |
| 8 | 키보드 단축키 | ✅ 완료 |
| 9 | 오류 처리 | ✅ 완료 |
| 10 | UI 개선 | ✅ 완료 |
| 11 | 하드웨어 이식 구조 | ✅ 완료 |
| + | 웨이브 바 (실시간 오디오 스펙트럼) | ✅ 완료 |

---

## 빠른 시작

```powershell
# 1. 가상환경 생성 및 패키지 설치
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 2. 환경변수 파일 생성
copy .env.example .env
#    -> .env 를 열어 SPOTIFY_CLIENT_ID 를 채운다 (STEP 2 참고)

# 3. 환경 점검
python -m app.doctor

# 4. 실행  (STEP 3 이후 사용 가능)
python main.py
```

---

## STEP 1 · 개발 환경 설정

### 요구사항

| 항목 | 버전 | 비고 |
|---|---|---|
| Python | **3.11 권장** (3.10 ~ 3.13) | [python.org](https://www.python.org/downloads/) |
| OS | Windows 10 / 11 | 추후 RK3399(ARM64 Linux) 이식 예정 |
| Spotify 계정 | **Premium 필수** | 아래 설명 참고 |

> ### ⚠️ Spotify Premium이 반드시 필요한 이유
>
> 1. **Web API의 재생 제어(Player) 엔드포인트는 Premium 전용**이다.
>    무료 계정은 재생/일시정지/다음곡 등이 `403`으로 거부된다.
> 2. **2026년 2월부터 Development Mode 앱은 앱 소유자가 Premium이어야 동작한다.**
>
> 무료 계정이어도 앱은 실행되며 *현재 재생 중인 곡 정보 표시*는 정상 작동한다.
> 다만 제어 버튼을 누르면 "Premium 계정에서만 사용할 수 있습니다" 안내가 표시된다.

### 설치

PowerShell을 프로젝트 폴더에서 열고:

```powershell
# 파이썬 3.11 설치 확인
py --list

# 가상환경 생성
py -3.11 -m venv .venv

# 가상환경 활성화
.\.venv\Scripts\Activate.ps1
```

> **`Activate.ps1` 실행이 차단된다면** (`UnauthorizedAccess` 오류)
> PowerShell에서 한 번만 아래를 실행한다:
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
>
> 그래도 안 되면 `cmd` 기준 `.\.venv\Scripts\activate.bat` 를 쓰면 된다.

프롬프트 앞에 `(.venv)` 가 보이면 성공. 이어서:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

설치되는 패키지:

| 패키지 | 용도 |
|---|---|
| `PySide6` | Qt 6 기반 UI. ARM64 Linux 지원이 좋아 RK3399 이식에 유리 |
| `requests` | Spotify Web API HTTP 호출 |
| `python-dotenv` | `.env` 에서 비밀키 로딩 |
| `keyring` | 토큰을 Windows 자격 증명 관리자에 안전하게 저장 |

### ✅ STEP 1 테스트 방법

```powershell
python -m app.doctor
```

**기대 결과** — `[3] .env 설정` 만 `[FAIL]`이고 나머지는 `[ OK ]`:

```
[1] Python 버전
  [ OK ]  Python 3.11.3
  [ OK ]  가상환경(venv) 활성화됨
[2] 필수 패키지
  [ OK ]  PySide6 6.11.2
  [ OK ]  requests 2.34.2
  [ OK ]  dotenv
  [ OK ]  keyring
[3] .env 설정
  [FAIL]  .env 파일 없음        <- STEP 2에서 해결
[5] 네트워크
  [ OK ]  api.spotify.com 도달 가능 (401 = 정상, 토큰 없음)
```

`[5] 네트워크`가 `401`을 반환하면 정상이다. 토큰 없이 호출했으니 거부되는 게 맞고,
**응답이 돌아왔다는 것 자체가 Spotify 서버에 도달했다는 뜻**이다.

---

## STEP 2 · Spotify Developer 설정

> 🙋 **이 단계는 사용자가 직접 해야 한다.** Claude Code는 사용자의 Spotify 계정에
> 로그인할 수 없으므로 앱 등록과 Client ID 발급을 대신 해 줄 수 없다.
> 아래 5분이면 끝난다.

### 1) 앱 만들기

1. <https://developer.spotify.com/dashboard> 접속 → 본인 Spotify 계정으로 로그인
2. **Create app** 클릭
3. 아래와 같이 입력한다:

| 입력란 | 값 |
|---|---|
| **App name** | `Spotify Deck` (자유) |
| **App description** | `Personal hardware deck prototype` (자유) |
| **Redirect URI** | `http://127.0.0.1:8888/callback` ← **정확히 이 값** |
| **Which API/SDKs are you planning to use?** | ☑ **Web API** |

4. Redirect URI 입력 후 반드시 오른쪽 **Add** 버튼을 눌러 목록에 추가한다.
   (입력만 하고 Add를 안 누르면 저장되지 않는다 — 가장 흔한 실수)
5. 약관에 동의하고 **Save**

> ### 🚨 `localhost` 를 쓰면 안 된다
>
> Spotify는 2025년 4월부터 Redirect URI 규칙을 강화했고 2025년 11월에 마이그레이션이 끝났다.
> 공식 문서의 규칙은 다음과 같다:
>
> - 루프백 주소가 아니면 **HTTPS** 를 써야 한다.
> - 루프백은 **명시적 IP** 를 써야 한다 — `http://127.0.0.1:PORT` 또는 `http://[::1]:PORT`
> - **`localhost` 는 Redirect URI로 허용되지 않는다.**
>
> | ❌ 잘못된 값 | ✅ 올바른 값 |
> |---|---|
> | `http://localhost:8888/callback` | `http://127.0.0.1:8888/callback` |
> | `http://127.0.0.1/callback` (포트 없음) | `http://127.0.0.1:8888/callback` |
>
> 오래된 블로그 튜토리얼은 대부분 `localhost`를 쓰고 있으니 그대로 따라 하면 실패한다.

### 2) Client ID 복사

1. 만든 앱 클릭 → 우측 상단 **Settings**
2. **Client ID** 값을 복사한다 (32자 16진수 문자열)
3. **Client secret 은 필요 없다.** 이 앱은 **PKCE** 방식을 쓴다.

> #### 왜 Client Secret을 안 쓰나?
>
> 데스크톱 앱은 사용자 PC에서 실행되므로 Secret을 안전하게 숨길 수 없다.
> 누구나 파일을 열어보면 훔칠 수 있다. 그래서 Spotify는 네이티브 앱에
> **PKCE(Proof Key for Code Exchange)** 를 권장한다.
> PKCE는 요청마다 일회용 `code_verifier`를 생성하므로 Secret 없이도 안전하다.
> 덕분에 `.env` 에 넣을 비밀값이 하나 줄어든다.

### 3) `.env` 파일 만들기

```powershell
copy .env.example .env
notepad .env
```

`SPOTIFY_CLIENT_ID` 한 줄만 본인 값으로 바꾼다:

```dotenv
SPOTIFY_CLIENT_ID=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

> `.env` 는 `.gitignore` 에 등록되어 있어 Git에 올라가지 않는다.
> 혹시 실수로 커밋했다면 Dashboard에서 Client ID를 즉시 재발급해야 한다.

### 4) 본인 계정을 허용 목록에 추가 (Development Mode)

새로 만든 앱은 **Development Mode** 상태이고, **허용 목록(allowlist)에 등록된 계정만**
API를 쓸 수 있다. 등록하지 않으면 로그인은 되지만 모든 요청이 `403` 으로 거부된다.

1. 앱 → **Settings** → **User Management** 탭
2. **Add new user** 클릭
3. 본인 **이름**과 Spotify 계정 **이메일 주소** 입력 → 저장

> Development Mode 제약 (2026년 기준)
>
> - 앱 소유자가 **Spotify Premium** 이어야 앱이 동작한다.
> - 허용 목록은 최대 **5명**.
> - 개발자 계정당 Client ID 25개, 할당량은 계정 단위로 공유된다.
> - 할당량 초과 시 `429` 응답에 `"reason": "QUOTA_EXCEEDED"` 가 포함된다.
>
> 개인 프로젝트는 Development Mode로 충분하다. Extended Quota Mode는
> 2025년 5월부터 법인 + 월 활성 사용자 25만 명 이상만 신청할 수 있다.

### ✅ STEP 2 테스트 방법

```powershell
python -m app.doctor
```

**기대 결과** — 모든 항목 `[ OK ]`, `[6]`만 "저장된 로그인 정보 없음" 경고:

```
[3] .env 설정
  [ OK ]  .env 파일 존재
  [ OK ]  Client ID 확인됨: a1b2****************************o5p6
  [ OK ]  Redirect URI 형식 정상: http://127.0.0.1:8888/callback
  [ OK ]  인증 방식: PKCE (Client Secret 불필요)
[4] OAuth 콜백 포트
  [ OK ]  127.0.0.1:8888 사용 가능
[6] 저장된 로그인 정보
  [WARN]  저장된 로그인 정보 없음      <- STEP 3에서 해결
```

`doctor`는 Dashboard에 등록하기 *전에* Redirect URI 형식을 검사한다.
`localhost`를 넣었다면 여기서 바로 잡아 준다:

```
[FAIL]  Redirect URI에 'localhost'는 사용할 수 없습니다.
        Spotify 정책에 따라 명시적 IP를 써야 합니다.
```

---

## STEP 3 · Spotify OAuth 로그인 (PKCE)

**Authorization Code with PKCE** 방식을 사용한다. Implicit Grant는 쓰지 않는다
(Spotify가 권장을 철회했고, 리프레시 토큰을 받을 수 없어 매번 재로그인해야 한다).

### 동작 순서

```
1. code_verifier  = 96자 난수                        (앱 내부에만 보관)
2. code_challenge = BASE64URL(SHA256(verifier))      (인증 요청에 실어 보냄)
3. 브라우저에서 사용자가 로그인 + 권한 승인
4. Spotify -> http://127.0.0.1:8888/callback?code=...  (앱이 띄운 임시 서버가 수신)
5. code + code_verifier(원본) -> 토큰 엔드포인트 -> 액세스/리프레시 토큰
```

중간에서 `code`를 가로채도 `code_verifier`가 없으면 토큰으로 바꿀 수 없다.
그래서 Client Secret 없이도 안전하다.

`state` 값으로 CSRF도 검증한다 (`secrets.compare_digest`로 타이밍 공격까지 차단).

### 토큰 저장

| 환경 | 저장 위치 |
|---|---|
| Windows (현재) | **자격 증명 관리자** (`WinVaultKeyring`) |
| 헤드리스 RK3399 | `~/.spotify_deck/tokens.json` (POSIX 권한 `0600`) |

`keyring`을 실제로 써 보고(쓰기→읽기→삭제 검증) 실패하면 자동으로 파일 저장으로 넘어간다.
RK3399를 데스크톱 환경 없이 부팅하면 SecretService(dbus)가 없어 keyring이 실패하는데,
그때 코드 수정 없이 동작한다.

> **리프레시 토큰 수명 (2026년 변경)**
> 최초 인증 시점부터 **6개월**이다. 액세스 토큰을 갱신해도 이 시계는 초기화되지 않는다.
> 만료되면 앱이 자동으로 감지해 다시 로그인 창을 띄운다.

### ✅ STEP 3 테스트 방법

```powershell
python -m app.spotify.auth
```

브라우저가 열리고 Spotify 로그인 화면이 나타난다. 권한을 허용하면:

```
로그인 성공
  액세스 토큰   : BQDx7K2mN9pQ8rT1vW3y... (283자)
  만료까지      : 3600초
  리프레시 토큰 : 있음
  승인된 권한   :
      - user-library-modify
      - user-library-read
      - user-modify-playback-state
      - user-read-currently-playing
      - user-read-playback-state

  /v1/me 호출로 토큰 검증 중...
  계정          : 홍길동 (hong@example.com)
  요금제        : premium
```

**두 번째 실행부터는 브라우저가 열리지 않는다** (저장된 토큰 재사용).

| 옵션 | 동작 |
|---|---|
| `python -m app.spotify.auth` | 로그인 (또는 저장된 토큰 확인) |
| `python -m app.spotify.auth --force` | 저장된 토큰 무시하고 다시 로그인 |
| `python -m app.spotify.auth --logout` | 저장된 로그인 정보 삭제 |

> **요금제가 "확인 안 함"으로 나오는 것은 정상이다.**
> `/me` 응답의 `product` 필드는 `user-read-private` 권한이 있어야 내려오는데,
> 덱 기능에 쓰이지 않으므로 요청하지 않는다(최소 권한 원칙).
> Premium 여부는 실제 재생 제어가 되는지로 확인하면 된다.

---

## STEP 4~6 · 재생 정보와 제어

### 사용하는 엔드포인트

모두 2026년 현재 공식 문서 기준으로 확인했다.

| 기능 | 엔드포인트 |
|---|---|
| 재생 상태 조회 | `GET /me/player?additional_types=track,episode` |
| 기기 목록 | `GET /me/player/devices` |
| 재생 / 일시정지 | `PUT /me/player/play` · `PUT /me/player/pause` |
| 다음 / 이전 | `POST /me/player/next` · `POST /me/player/previous` |
| 위치 이동 | `PUT /me/player/seek?position_ms=` |
| 볼륨 | `PUT /me/player/volume?volume_percent=` |
| 셔플 | `PUT /me/player/shuffle?state=` |
| 반복 | `PUT /me/player/repeat?state=off\|context\|track` |
| **좋아요 확인** | `GET /me/library/contains?uris=` |
| **좋아요 추가** | `PUT /me/library?uris=` |
| **좋아요 해제** | `DELETE /me/library?uris=` |

> ### ⚠️ 좋아요 엔드포인트가 2026년 2월에 교체되었다
>
> | 삭제됨 (구버전 튜토리얼) | 현재 사용해야 하는 것 |
> |---|---|
> | `PUT /me/tracks?ids=` | `PUT /me/library?uris=` |
> | `DELETE /me/tracks?ids=` | `DELETE /me/library?uris=` |
> | `GET /me/tracks/contains?ids=` | `GET /me/library/contains?uris=` |
>
> 새 엔드포인트는 **ID가 아니라 Spotify URI**를 받는다: `spotify:track:7a3LWj...`
> 응답은 boolean 배열이다: `[true]`
>
> #### ⚠️ URI를 직접 URL 인코딩하면 안 된다
>
> 공식 문서에는 `uris=spotify%3Atrack%3A...` 처럼 인코딩된 예시가 나오는데,
> 그건 **최종 HTTP 요청 줄의 모습**을 보여 주는 것이다.
> `requests`가 쿼리 파라미터를 이미 인코딩하므로 여기서 또 인코딩하면
> `%`가 `%25`로 한 번 더 바뀌어 다음과 같이 실패한다:
>
> ```
> 보낸 값    spotify%3Atrack%3Aabc
> 실제 전송  uris=spotify%253Atrack%253Aabc
> 서버 해석  spotify%3Atrack%3Aabc
> 결과       400 {"message": "Invalid Spotify URI: spotify%3Atrack%3Aabc"}
> ```
>
> 원본 URI를 그대로 넘기고 인코딩은 HTTP 라이브러리에 맡겨야 한다.
> (`app/spotify/client.py`의 `join_uris()` 참고 — 실제 API 응답으로 확인함)
>
> 이 마이그레이션은 Development Mode 앱에만 적용된다.

### 설계 포인트

**진행률 보간** — 1초마다 폴링하면 진행 바가 1초씩 뚝뚝 끊긴다.
`PlaybackState.estimated_progress_ms()`가 마지막 응답 이후 흐른 실제 시간을 더해
UI가 100ms마다 부드럽게 갱신한다. 일시정지 중에는 보간하지 않는다.

**좋아요 캐싱** — 매 폴링마다 확인하면 API 호출이 2배가 된다.
곡이 바뀔 때만 조회하고, 사용자가 토글하면 캐시를 무효화한다.

**낡은 상태 자동 보정** — 폴링 주기(1초) 안에 `Space`를 두 번 누르면
아직 갱신되지 않은 상태로 판단해 "이미 멈춘 것을 또 멈추려" 하게 되고,
Spotify가 `403 Player command failed: Restriction violated`로 거부한다.
거부당하면 반대 명령을 한 번 더 보내 사용자 의도대로 동작시킨다.

**일시적 연결 끊김 재시도** — Wi-Fi 전환이나 TLS 핸드셰이크 리셋은 드물지 않다.
한 번 실패했다고 오류를 띄우면 앱이 불안정해 보이므로 1회 재시도한다.
단 **`POST`는 재시도하지 않는다** — `POST /me/player/next`가 두 번 나가면
곡을 두 개 건너뛰기 때문이다. `GET`/`PUT`/`DELETE`는 멱등이라 안전하다.

**팟캐스트 지원** — `additional_types=track,episode`를 빠뜨리면
팟캐스트 재생 중에 `item`이 `null`로 와서 "재생 없음"으로 잘못 표시된다.
에피소드는 `artists`가 없어 쇼 이름을 그 자리에 넣어 UI가 구분 없이 처리한다.

### ✅ STEP 4~6 테스트 방법

1. 휴대폰이나 PC의 **Spotify 앱에서 아무 곡이나 재생**한다.
2. `python main.py` 실행.
3. 확인할 항목:

| 확인 | 기대 동작 |
|---|---|
| 곡 정보 | 제목 · 아티스트 · 앨범명 · 앨범 아트가 표시된다 |
| 자동 갱신 | Spotify 앱에서 곡을 넘기면 1초 내에 덱에도 반영된다 |
| 진행률 | 시간이 부드럽게 흐른다 (1초씩 끊기지 않음) |
| 재생/일시정지 | 버튼을 누르면 실제 음악이 멈추고 재생된다 |
| 이전/다음 | 곡이 바뀐다 |
| 진행 바 드래그 | 놓은 지점부터 재생된다 |
| 볼륨 슬라이더 | 실제 볼륨이 바뀐다 |
| 셔플 / 반복 | 버튼이 초록색으로 켜지고 Spotify 앱에도 반영된다 |
| 좋아요 | 하트가 채워지고 Spotify 보관함에 실제로 추가된다 |

---

## STEP 7~10 · UI와 오류 처리

### 레이아웃

창 너비 **700px**를 기준으로 자동 전환된다.

```
 넓을 때 (16:9 데스크톱, 800x480 LCD)     좁을 때 (세로 화면, 480x320)
 ┌────────────┬──────────────────┐        ┌──────────────┐
 │            │  Song Title      │        │  [앨범 아트]  │
 │ [앨범 아트] │  Artist / Album  │        ├──────────────┤
 │            │  ──────●───────  │        │  Song Title  │
 │            │  [◀] [▶] [▶▶]   │        │  ──●───────  │
 │            │  [S][R][♥]  🔊── │        │  [◀][▶][▶▶] │
 └────────────┴──────────────────┘        └──────────────┘
```

좁아지면 제목 폰트도 26pt → 18pt로 줄어 3줄로 넘치지 않는다.

**아이콘은 PNG가 아니라 벡터로 그린다** (`app/ui/icons.py`).
27인치 모니터에서도 3.5인치 LCD에서도 선명하고, 좋아요 on/off 같은 색 변화에
이미지를 2벌 준비할 필요가 없다. 저장소에 바이너리도 남지 않는다.

### 오류 처리

**사용자에게 traceback을 절대 보여주지 않는다.** 모든 하위 오류는
`app/core/errors.py`의 예외로 번역되어 한국어 안내 + 조치 방법으로 표시된다.

| 상황 | 화면에 표시되는 내용 | 앱 동작 |
|---|---|---|
| 인터넷 끊김 | "인터넷에 연결할 수 없습니다" | 지수 백오프(최대 30초)로 재시도, 복구되면 자동 연결 |
| Premium 아님 | "이 기능은 Spotify Premium 계정에서만 사용할 수 있습니다" | 재생 정보 표시는 계속 동작 |
| 활성 기기 없음 | "재생 중인 Spotify 기기가 없습니다" | 사용 가능한 기기를 자동으로 깨워 1회 재시도 |
| 토큰 만료 | (표시 안 됨) | 자동 갱신 후 요청 재시도 |
| 리프레시 토큰 만료 | "다시 로그인이 필요합니다" | 재로그인 안내 |
| Client ID 오류 | "Client ID가 올바르지 않습니다" | `.env` 확인 안내 |
| Redirect URI 불일치 | 정확한 값과 Add 버튼 안내 | — |
| 허용 목록 미등록 (403) | "User Management에 이메일을 추가해 주세요" | — |
| Rate Limit (429) | "N초 후 재시도합니다" | 5초 이하면 조용히 대기 후 재시도 |
| 할당량 초과 | "API 사용량 한도를 초과했습니다" | 최소 60초 요청 중단 |
| 재생 중 음악 없음 | "재생 중인 음악이 없습니다" | 오류가 아닌 정상 상태로 처리 |
| 광고 재생 중 | 스킵 버튼이 흐려짐 | Spotify의 `actions.disallows` 반영 |

### ✅ STEP 7~10 테스트 방법

오류 처리는 일부러 실패를 만들어 확인한다.

```powershell
# 1) 인터넷 끊김 - 실행 중 Wi-Fi를 껐다가 다시 켠다
#    -> "인터넷에 연결할 수 없습니다" 표시 후, 켜면 "다시 연결되었습니다"

# 2) 활성 기기 없음 - Spotify 앱을 모두 종료한 뒤 재생 버튼을 누른다
#    -> "재생 중인 Spotify 기기가 없습니다" + 조치 안내

# 3) 잘못된 Client ID
notepad .env       # SPOTIFY_CLIENT_ID 끝 글자를 바꾼다
python main.py     # -> "Client ID가 올바르지 않습니다" 대화상자

# 4) localhost 사용 금지 검증
notepad .env       # SPOTIFY_REDIRECT_URI를 http://localhost:8888/callback 로
python -m app.doctor   # -> [FAIL] 'localhost'는 사용할 수 없습니다

# 5) 반응형 레이아웃 - 창을 좌우로 줄였다 늘렸다 한다
#    -> 700px 부근에서 가로/세로 배치가 전환된다
```

어느 경우에도 **콘솔에 Python traceback이 뜨면 안 된다.**

---

## STEP 11 · 하드웨어 이식 구조

### 핵심 아이디어

입력 장치는 "어떤 키가 눌렸는지"가 아니라 **"무슨 동작을 원하는지"** 만 전달한다.

```
 [KeyboardController]  ─┐
 [GPIOController]      ─┼─→  DeckAction  ─→  [DeckController]  ─→  [SpotifyPlayer]
 [EncoderController]   ─┘      (유일한 경계)
 [TouchController]     ─┘
```

`DeckAction`(`app/core/actions.py`)이 유일한 계약이다.
따라서 **새 하드웨어를 붙일 때 작성할 코드는 `DeckAction`을 내보내는 클래스 하나뿐**이고,
`app/spotify/`와 `app/ui/`는 전혀 수정하지 않는다.

### 실제로 추가하는 코드

`app/input/gpio_template.py`에 동작하는 뼈대가 이미 들어 있다.
RK3399에서는 `main.py`에 **한 줄**만 추가하면 된다:

```python
inputs = InputManager(on_action=window.handle_action)
inputs.register(KeyboardController(window))            # 디버깅용으로 남겨 둬도 된다
inputs.register(GPIOButtonController(PIN_MAP))         # ← 물리 버튼 추가
inputs.register(RotaryEncoderController(clk=17, dt=18, sw=27))   # ← 엔코더 추가
```

### 템플릿에 이미 반영된 하드웨어 고려사항

| 항목 | 처리 |
|---|---|
| **버튼 채터링** | 180ms 디바운스. 없으면 한 번 눌러도 "다음 곡"이 5번 실행된다 |
| **엔코더 Rate Limit** | 스텝을 150ms 동안 모아 **한 번**만 API 호출. 빠르게 돌려도 429에 걸리지 않는다 |
| **터치 LCD** | Qt가 터치를 마우스 이벤트로 변환하므로 별도 컨트롤러 불필요 |
| **전체화면 / 커서 숨김** | 템플릿 하단에 코드 주석으로 포함 |
| **프레임버퍼 직접 출력** | `QT_QPA_PLATFORM=linuxfb` 또는 `eglfs`(Mali GPU 가속) |
| **토큰 저장** | 헤드리스라 keyring이 없으면 자동으로 파일 저장으로 폴백 |

### 화면 크기 대응

| 패널 | 동작 |
|---|---|
| 800×480 (5인치) | 가로 배치 그대로 사용 |
| 480×320 (3.5인치) | 세로 배치로 자동 전환, 폰트 축소 |

터치용으로 버튼을 키우려면 `app/ui/window.py`의 `IconButton(size=...)` 값만 올리면 된다.
아이콘이 벡터라 확대해도 깨지지 않는다.

---

## 웨이브 바 (실시간 오디오 스펙트럼)

앨범 정보와 진행 바 사이에 **실제 소리에 반응하는 주파수 막대**가 표시된다.

```
  베이스        중음        고음
   ▄█████▄      ▁▄█▄▁      ·▄▁·
  ─────────────────────────────────
```

### 왜 시스템 오디오를 캡처하는가

Spotify Web API로는 실시간 오디오 데이터를 받을 수 없다.
비트 정보를 주던 `audio-analysis` / `audio-features` 엔드포인트는
**2024년 11월부터 신규 앱에 차단**되어 지금은 `403`을 반환한다
(이 프로젝트에서 실제로 확인함).

그래서 Windows의 **WASAPI 루프백**으로 스피커로 나가는 소리를 직접 읽는다.
마이크가 아니라서 주변 소음이 섞이지 않고, 재생 중인 소리만 정확히 잡힌다.

```
[Spotify] -> [Windows 오디오 믹서] -> [스피커]
                     |
                     +-- 루프백 캡처 -> FFT -> 대역별 레벨 -> 막대
```

### 자동 폴백

이 PC로 재생할 때만 소리를 잡을 수 있으므로, 상황에 따라 자동 전환된다.

| 상황 | 동작 | 화면 표시 |
|---|---|---|
| 이 PC로 재생 중 | 실제 소리에 반응 | 실시간 오디오 |
| 폰/스피커로 재생 중 | 시뮬레이션 애니메이션 | 다른 기기에서 재생 중 |
| 일시정지 | 막대가 서서히 가라앉음 | 대기 중 |
| soundcard 미설치 / 루프백 미지원 | 시뮬레이션 | 시뮬레이션 |

전환은 1.5초 무음 감지 후 **서서히 혼합**되므로 화면이 튀지 않는다.

### 설정

`.env`의 `DECK_WAVE_MODE`로 바꿀 수 있다.

| 값 | 동작 |
|---|---|
| `auto` | 실시간 캡처 + 자동 폴백 (기본값) |
| `live` | 실시간 캡처 강제 (불가하면 폴백 + 경고) |
| `simulated` | 시뮬레이션만 사용 (`soundcard` 불필요) |
| `off` | 웨이브 바 숨김 |

### 구현 메모

**로그 간격 대역 + dB 진폭** — 사람의 청각은 둘 다 로그 스케일이다.
선형으로 만들면 베이스가 첫 막대에 전부 몰리고 나머지는 거의 안 움직인다.

**빈(bin) 독점 배정** — 이게 가장 까다로운 부분이었다.
48kHz / 4096샘플 = FFT 빈 하나가 11.7Hz인데,
30Hz~16kHz를 28개 로그 대역으로 나누면 맨 아래 대역 폭은 1~2Hz에 불과하다.
그대로 두면 저음 대역 여러 개가 **같은 빈 하나**를 읽어
베이스 한 음에 막대 7개가 똑같은 높이로 치솟는다.
그래서 빈을 왼쪽부터 순서대로 나눠 주고 각 대역이 최소 1개를 독점하게 했다.
결과적으로 저음부는 선형에 가깝게, 고음부는 로그 간격으로 배치된다.

> 60Hz 순음을 넣으면 여전히 5~6개 막대가 완만하게 부풀어 오르는데,
> 이건 결함이 아니라 Hann 창의 주 로브 폭(약 47Hz)에 따른 자연스러운 모양이다.
> 실제 음악의 베이스는 원래 40~120Hz에 걸쳐 있어 이렇게 보이는 게 맞다.

**attack > decay** — 올라갈 땐 빠르게(0.55), 내려갈 땐 천천히(0.12).
타악기가 '탁' 튀고 부드럽게 가라앉는 실제 오디오 기기의 느낌을 낸다.

**자동 게인** — 최근 최대값을 천천히 따라가 조용한 곡에서도 막대가 살아 있다.

**출력 장치 교체 추적** — 실행 중에 헤드폰을 꽂으면 소리는 헤드폰으로 가는데
캡처는 이전 장치(이제 무음)를 계속 읽는다. 그러면 "소리가 없다"고 판단해
시뮬레이션으로 넘어가고, 화면에는 막대가 음악과 무관하게 움직이는 것으로 보인다.
1초마다 기본 출력 장치를 확인해 바뀌면 새 장치로 다시 연다.

**dB 범위는 넓게** — 천장을 `-10dB`로 두면 "가장 큰 대역보다 10dB 이내"인 대역이
전부 1.0이 된다. 음악은 대부분의 대역이 그 안에 들어와서 막대가 죄다 천장에 붙고
음악 구조가 보이지 않는다. 실측 결과 28개 중 24개가 포화였다.
천장을 `0dB`(최대 대역만 꽉 참), 바닥을 `-55dB`로 넓히니 포화가 0.5개로 줄고
대역 간 편차가 0.213까지 올라 음악의 모양이 드러났다.

**성능** — 60fps 렌더링이 프레임당 0.71ms로 측정되었다 (여유 16ms).
캡처와 FFT는 별도 스레드에서 돌아 UI를 막지 않는다.

### 디자인 미리보기 도구

앱을 띄우지 않고 웨이브 바만 PNG로 그려 수정 전후를 비교할 수 있다.

```powershell
python tools/render_wave.py wave_preview.png
```

고정 레벨을 쓰므로 매번 같은 그림이 나오고, 피크가 떠 있는 상태와
막대에 붙은 상태를 위아래로 함께 그려 준다.

### RK3399 이식

`WaveSource` 추상 클래스를 구현한 클래스 하나만 추가하면 된다.
ALSA의 `snd-aloop` 모듈이나 PulseAudio monitor 소스를 읽으면 되고,
UI와 Spotify 로직은 수정하지 않는다.

```
WaveSource (app/audio/base.py)
├── SystemAudioWaveSource   WASAPI 루프백 (Windows, 구현됨)
├── SimulatedWaveSource     대체 애니메이션 (구현됨)
├── AutoWaveSource          자동 전환 (구현됨)
└── AlsaWaveSource          RK3399용 (향후)
```

---

## 테스트

```powershell
python -m pytest
```

140개의 단위 테스트가 약 1초에 돈다. 네트워크나 오디오 장치, Spotify 계정이 필요 없다.

| 파일 | 검증 내용 |
|---|---|
| `test_auth_pkce.py` | RFC 7636 공식 테스트 벡터, 인증 URL 구조(Implicit 금지), 인증 코드 로그 마스킹, 토큰 재시도 |
| `test_settings.py` | Redirect URI 규칙(`localhost` 거부, 포트 필수), 자리표시자 감지, 폴링 하한 |
| `test_models.py` | 트랙/에피소드/광고/204 파싱, 진행률 보간, 결측 필드 내성 |
| `test_client.py` | 403 원인 3가지 구분, 429 vs 할당량, POST 재시도 금지, URI 이중 인코딩 방지 |
| `test_spectrum.py` | FFT 빈 독점 배정, 주파수→대역 대응, 포화 방지, attack>decay |
| `test_input_and_tokens.py` | 키 매핑 계약, 입력 계층 격리, 토큰 저장소 원자성 |

테스트는 **실제로 겪은 버그를 고정**한다. 예를 들어 `test_uris_are_not_pre_encoded`는
URI 이중 인코딩으로 좋아요 기능이 통째로 죽었던 문제를,
`test_bands_do_not_share_fft_bins`는 베이스 한 음에 막대 7개가 똑같이 치솟던 문제를 막는다.

---

## 조작법

### 키보드

| 키 | 동작 |
|---|---|
| `Space` | 재생 / 일시정지 |
| `←` `→` | 이전 곡 / 다음 곡 |
| `↑` `↓` | 볼륨 +5 / -5 |
| `,` `.` | 10초 뒤로 / 앞으로 |
| `S` | 셔플 |
| `R` | 반복 (끔 → 전체 → 한 곡) |
| `L` | 좋아요 |
| `F5` | 즉시 새로고침 |
| `Esc` | 종료 |

키를 **길게 눌러도 반복 입력되지 않는다** (자동 반복 차단).
Rate Limit 보호를 위한 의도적 설계이며, 연속 조절은 슬라이더를 쓴다.

매핑은 `app/config/keymap.py`에서 바꿀 수 있다.

### 마우스

- 진행 바 클릭/드래그 → 해당 위치로 이동 (드래그 중에는 서버 값이 덮어쓰지 않는다)
- 진행 바/볼륨 **휠 스크롤** → 조절 (로터리 엔코더와 같은 조작감)
- 스피커 아이콘 클릭 → 음소거 / 해제

### 실행 옵션

```powershell
python main.py             # 일반 실행
python main.py --debug     # 상세 로그
python main.py --logout    # 로그인 정보 삭제 후 종료
python -m app.doctor       # 환경 점검
```

---

## 프로젝트 구조

```
Spotify_Deck/
├── main.py                       # 진입점 - 모든 계층을 조립
├── app/
│   ├── doctor.py                 # 환경 점검 스크립트
│   │
│   ├── core/                     # ═══ 계층 간 공통 계약 ═══
│   │   ├── actions.py            #   DeckAction - 입력↔제어 경계 (가장 중요)
│   │   ├── deck_controller.py    #   액션 → Spotify 호출 디스패처
│   │   ├── errors.py             #   사용자 친화적 예외 계층
│   │   └── console.py            #   Windows UTF-8 콘솔 보정
│   │
│   ├── config/
│   │   ├── settings.py           #   .env 로딩 + Redirect URI 검증 + 스코프
│   │   └── keymap.py             #   키보드 → DeckAction 매핑 테이블
│   │
│   ├── spotify/                  # ═══ Spotify 제어 계층 ═══
│   │   ├── auth.py               #   PKCE OAuth + 콜백 서버 + 토큰 갱신
│   │   ├── tokens.py             #   토큰 저장 (keyring / 파일 폴백)
│   │   ├── client.py             #   HTTP + 모든 오류를 DeckError로 번역
│   │   ├── models.py             #   PlaybackState (진행률 보간 포함)
│   │   └── player.py             #   고수준 재생 제어
│   │
│   ├── audio/                    # ═══ 웨이브 바 오디오 계층 ═══
│   │   ├── base.py               #   WaveSource 추상 클래스
│   │   ├── spectrum.py           #   FFT -> 대역 레벨 (장치 무관, 단독 검증 가능)
│   │   ├── loopback.py           #   WASAPI 루프백 실시간 캡처
│   │   ├── simulated.py          #   캡처 불가 시 대체 애니메이션
│   │   └── factory.py            #   자동 선택 및 전환
│   │
│   ├── input/                    # ═══ 입력 장치 계층 ═══
│   │   ├── base.py               #   InputController 추상 클래스 + Manager
│   │   ├── keyboard.py           #   KeyboardController (현재 사용)
│   │   └── gpio_template.py      #   GPIO/엔코더 템플릿 (RK3399 이식용)
│   │
│   └── ui/                       # ═══ UI 계층 ═══
│       ├── window.py             #   메인 윈도우 (반응형 레이아웃)
│       ├── worker.py             #   폴링 스레드 + 액션 실행기
│       ├── theme.py              #   다크 팔레트 + QSS
│       ├── icons.py              #   벡터 아이콘 (PNG 불필요)
│       └── widgets/
│           ├── album_art.py      #     비동기 로딩 + 페이드 전환 + LRU 캐시
│           ├── wave_bar.py       #     스펙트럼 막대 (60fps)
│           ├── buttons.py        #     아이콘 버튼 / 재생 버튼
│           └── slider.py         #     진행률 · 볼륨 슬라이더
│
├── assets/
├── .env                          # 비밀값 (Git 제외)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

### 설계 원칙 — 왜 이렇게 나눴나

목표는 **나중에 키보드를 GPIO로 바꿀 때 Spotify 로직과 UI를 수정하지 않는 것**이다.
이를 위해 `app/core/actions.py` 의 `DeckAction` 열거형이 유일한 경계 역할을 한다.

```
 [KeyboardController]  ─┐
 [GPIOController]      ─┼─→  DeckAction  ─→  [DeckController]  ─→  [SpotifyPlayer]
 [EncoderController]   ─┘    (공통 계약)
```

입력 장치는 "Space 키가 눌렸다"가 아니라 **"PLAY_PAUSE를 원한다"** 만 전달한다.
따라서 새 하드웨어를 붙일 때 작성해야 하는 코드는
`DeckAction`을 내보내는 컨트롤러 하나뿐이다.

---

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `Activate.ps1 ... 실행할 수 없습니다` | PowerShell 실행 정책 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| doctor에서 한글이 깨짐 | 콘솔 코드페이지 cp949 | `app/core/console.py`가 자동 보정. 그래도 깨지면 `chcp 65001` |
| `INVALID_CLIENT: Invalid redirect URI` | Dashboard와 `.env` 값 불일치 | 양쪽 모두 `http://127.0.0.1:8888/callback` 인지, **Add** 버튼을 눌렀는지 확인 |
| 포트 8888 사용 중 | 다른 프로그램이 점유 | `.env`와 Dashboard를 `8889`로 함께 변경 |
| 모든 API 요청이 `403` | 허용 목록 미등록 | Dashboard → Settings → User Management에 본인 이메일 추가 |
| 제어 버튼만 `403` | Premium 계정 아님 | Player API는 Premium 전용 |

---

## 참고 문서

- [Spotify Web API 문서](https://developer.spotify.com/documentation/web-api)
- [Redirect URI 규칙](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
- [Quota Modes (Development Mode 제약)](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [2026년 2월 Web API 마이그레이션 가이드](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
