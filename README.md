# 쇼츠공방 (Shorts Studio)

장면 이미지 + 내레이션으로 된 **번들**에서 **세로 9:16 유튜브 쇼츠**를 만드는 웹앱.
씬마다 **상단 후크 / 중간 음성 자막 / 하단 해시태그**를 편집하고, AI로 문구를 뽑고
사실을 검증한 뒤, 한 번에 9:16 영상으로 합성한다.

> 화면: 상단 흰 띠(2색 후크 + 플레이어 아이콘) · 중간 영상/이미지(켄번스) · 하단 흰 띠(해시태그 2줄).
> 마지막 씬엔 "전체 영상 보기" CTA. 캔버스 크기는 설정값이라 가로(16:9)로도 확장 가능.

> **준비물 요약**:
> - **ffmpeg** — 영상 합성 필수
> - **OAuth LLM 로그인**(codex 또는 agy) — AI 후크·자막·검증·메타에 사용(**기본 전제**, API 키 불필요)
> - (선택) **SuperTonic3(VoiceWright)** — 새 목소리(F4 등) TTS 재생성용. 없으면 번들의 **기존 음성** 사용

---

## 0. 설치 전 준비물 (Prerequisites)

`setup.bat` 전에 **꼭 설치할 2가지**를 먼저 준비하세요.

### 꼭 설치할 2가지
1. **Python 3.10+** — 설치 시 *"Add Python to PATH"* 체크. (확인: `python --version`)
   > ※ 영상공방을 이미 셋업했다면 Python은 보통 설치돼 있습니다.
2. **ffmpeg / ffprobe** — 영상 합성 필수, PATH 에 있어야 함.
   - Windows: `winget install Gyan.FFmpeg` (또는 [ffmpeg.org](https://ffmpeg.org) 받아 PATH 등록) · 확인: `ffmpeg -version`
   > ※ 영상공방도 ffmpeg를 사용하므로, 영상공방을 쓰고 있다면 이미 깔려 있을 수 있습니다.

### AI 기능용 — OAuth 로그인 (기본 전제)
3. **영상공방(VOD Studio) 백엔드 + codex/agy 로그인**
   - 영상공방에 `services/llm_backend.py` + `venv` + VoiceWright(TTS)가 있고, codex 또는 agy로 1회 로그인(ChatGPT/Google). API 키 불필요.
   - `.env` 의 `SHORTS_VODSTUDIO_DIR` 에 그 경로를 지정하면 LLM·메타·검증·TTS가 켜집니다.
   > ※ **영상공방을 쓰는 분은 이미 설치·로그인된 상태** — `.env` 경로만 맞추면 됩니다.

### 그 외 (대개 자동/기본)
- **한글 폰트**: Windows 기본 *맑은 고딕*이면 OK (Pretendard/나눔고딕 있으면 우선).
- **git**: 클론용(없으면 GitHub ZIP 다운로드).
- **SuperTonic3(VoiceWright) 음성 모델**: 새 목소리(F4 등) TTS용 — 영상공방에 포함. 없으면 번들 기존 음성으로 렌더.

---

## 1. 설치 (Setup)

```bat
git clone https://github.com/leedonwoo2827-ship-it/shorts-studio
cd shorts-studio

setup.bat          :: venv 생성 + 의존성 설치 + .env 준비
notepad .env       :: 본인 경로로 수정 (아래 "설정" 참고)
run.bat            :: 서버 실행 → 브라우저가 http://127.0.0.1:7010 자동 오픈
```
- `setup.bat` 이 venv 와 `.env`(=.env.example 복사본)를 만들어 줍니다.
- 끄려면 `run.bat` 창을 닫으면 됩니다.

> ⚠️ **`setup.bat`이 설치하는 것 vs 아닌 것**
> - **setup.bat이 설치**: venv + 가벼운 파이썬 의존성(`fastapi`·`uvicorn`·`python-dotenv`)뿐.
> - **setup.bat에 없음(직접 설치)**: 용량이 크거나 외부 도구라 포함하지 않습니다 →
>   **ffmpeg**, **영상공방 백엔드**(LLM `codex/agy` + `venv`), **VoiceWright(SuperTonic3) 음성 모델**.
>   → 위 **0번 준비물**에서 미리 설치/셋업하세요.

---

## 2. 설정 (.env)

| 항목 | 설명 |
|---|---|
| `SHORTS_VODSTUDIO_DIR` | **영상공방 프로젝트 경로**(LLM·TTS 백엔드 위치). AI/음성 기능 안 쓰면 비워도 됨 |
| `LLM_PROVIDER` | `codex`(ChatGPT 로그인) 또는 `agy`(Antigravity/Gemini 로그인) |
| `SHORTS_BUNDLE_ROOTS` | 번들(chNN_bundle)을 찾을 폴더들. 세미콜론(;)으로 여러 개 |

예시:
```
SHORTS_VODSTUDIO_DIR=C:\work\vodstudio
LLM_PROVIDER=codex
SHORTS_BUNDLE_ROOTS=C:\work\bundles\_assets;C:\work\vodstudio\data
```

---

## 3. 사용법 (워크플로우)

### ① 번들 선택
- 드롭다운에서 번들을 고르거나 폴더 경로를 직접 입력.
- **길이**(최대 초), **씬 개수**, **음성 속도**(쇼츠 권장 1.2), **목소리**(F1~F5/M1~M5) 선택.
- **`✨ 씬 자동 구성`** → 핵심 씬을 자동 선별하고, (LLM 연결 시) AI가 후크·자막·해시태그를
  채운 뒤 **전체 검토까지 자동 실행**해 각 자막 밑에 근거를 깔아줍니다.

### ② 씬 구성 · 문구 편집 (왼쪽)
- **상단 후크**: 1줄=검정, **Enter 후 2줄=주황**. (후크1/2 글자 크기·색 따로 조절)
- **음성 자막**(중간, 말로 읽힘): 이게 곧 **음성 대본**. 여기 문장이 그대로 음성이 됩니다.
- **`🔎 검토`**(자막칸): 그 씬만 원본과 대조해 사실 점검 → 밑에 평가 + **대안 문장**(클릭하면 교체).
- 버튼:
  - `🔁 AI 후크 다시` / `🔁 AI 자막 다시` — 새로 생성(내용 바뀜)
  - `✅ 흐름 검토` — 전체 이야기 흐름·연결·중복 평가만(**내용 안 바뀜**)
  - `🔎 전체 사실검증` — 모든 씬 사실 점검, 근거+대안 인라인(**대안 클릭해야 바뀜**)
  - `＋ 씬 추가`, `↑↓` 순서, `✕` 삭제, `💾` 후크 보관함
- 오른쪽 **📜 전체 음성 대본**에서 전체 흐름을 한눈에 보며 다듬기.

### ③ 쇼츠 생성 (오른쪽)
- **원본 영상 URL**(CTA·메타용), **하단 텍스트(해시태그)** 입력.
- **`🎙️ 음성 싱크 재생성`** (TTS 연결 시): 자막 그대로 **선택한 목소리·속도로 새 음성** 생성 →
  음성 길이에 맞춰 씬 길이 자동 싱크. (자막 없는 클린 롱폼이 있으면 그 영상 음소거 배치, 없으면 이미지)
- **`🎬 쇼츠 생성`** → 9:16 미리보기 + 다운로드.

### ④ 유튜브 쇼츠 메타 (LLM 연결 시)
- `📺 메타 생성` → 제목·설명(원본 링크)·태그·고정댓글 → 복사해서 업로드.

> **업로드 팁**: 영상은 쇼츠로 올리고, 설명/고정댓글에 원본 롱폼 링크를 걸어 트래픽을 유도하세요.

---

## 4. 번들이란? (입력 형식)

쇼츠공방의 입력은 **번들 폴더**(`chNN_bundle`)입니다. 보통 영상공방이 만들어 주며, 직접 만들 수도 있습니다.
```
chNN_bundle/
  script/chNN_script.json      ← 장면 목록(제목·내레이션·scene_type 등)
  images/chNN_XX_*.png|jpeg     ← 장면 이미지
  audio/chNN_XX_narration.wav   ← 장면 음성(있으면 사용, 없으면 무음/이미지)
  subtitles/chNN_XX_narration.srt
  draft/chNN_final_nosub.mp4     ← (선택) 자막 없는 롱폼이면 영상 배경으로 사용
```
자세한 스키마는 [docs/BUNDLE-FORMAT.md](docs/BUNDLE-FORMAT.md).

---

## 5. 문제 해결

- **화면이 안 바뀜** → `run.bat` 다시 시작(파이썬 변경 시) + 브라우저 새로고침(정적 파일은 자동 캐시버스팅).
- **렌더 실패 / ffmpeg 오류** → `ffmpeg -version` 으로 PATH 확인.
- **AI 기능이 회색/미작동** → 상단 `LLM` 칩 클릭 → 로그인 상태 확인. 백엔드 없으면 그 기능만 비활성, 나머지는 정상.
- **음성이 안 빨라짐** → 속도 선택 후 **`🎙️ 음성 싱크 재생성`을 다시 눌러야** 새 음성이 적용됨.
- **한글 깨짐(콘솔)** → 화면/영상엔 영향 없음(콘솔 표시 인코딩 문제).

---

## 6. 더 자세히 (docs/)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 파이프라인·모듈·렌더 방식
- [docs/LLM-OAUTH-BRIDGE.md](docs/LLM-OAUTH-BRIDGE.md) — OAuth LLM/TTS 브리지 원리, 재사용 키트
- [docs/BUNDLE-FORMAT.md](docs/BUNDLE-FORMAT.md) — 번들 폴더·스크립트 JSON 형식

## 의존
ffmpeg, FastAPI, uvicorn. LLM·TTS는 외부 백엔드(영상공방의 codex/agy·VoiceWright)에 의존(설치 시 활성화).
