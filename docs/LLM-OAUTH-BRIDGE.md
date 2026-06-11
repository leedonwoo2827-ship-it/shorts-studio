# LLM / TTS OAuth 브리지

쇼츠공방은 **자체 API 키를 두지 않습니다.** 대신 이미 OAuth 로그인 백엔드를 가진
프로젝트(영상공방/VOD Studio)의 venv 파이썬을 **subprocess 로 호출**해 LLM·TTS 결과만 받아옵니다.

## 왜 브리지인가
- API 키 관리 불필요 — 사용자가 codex(ChatGPT) 또는 agy(Antigravity/Gemini)에 1회 로그인한 세션을 그대로 사용.
- 백엔드의 무거운 의존성(httpx, onnxruntime, pywinpty 등)을 이 앱 venv에 안 깔아도 됨.
- 이 앱은 **표준 라이브러리만**으로 동작(브리지 자체 의존성 0).

## 동작
```
shortsmaker/llm_kit.py  ──subprocess──▶  {LLM_BRIDGE_DIR}/venv/python
   (LLM 채팅/상태/공급자/로그인)              └ from services import llm_backend
                                                  active_client().chat(model, messages)

shortsmaker/tts.py      ──subprocess(PYTHONPATH=백엔드)──▶  voicewright.engine
   (음성 생성)                                              Engine.synth(text, voice_code, speed)
```
- 경로: 환경변수 `LLM_BRIDGE_DIR`(쇼츠공방에선 `SHORTS_VODSTUDIO_DIR`를 자동 매핑).
- 공급자(codex/agy)는 백엔드의 `data/llm_provider.json`(영상공방 화면 토글)이 결정 — 두 앱이 공유.
- 출력의 ANSI/OSC 제어문자(터미널 타이틀 등)는 키트가 걸러냄(비밀값 노출·깨짐 방지).

## llm_kit 공개 함수
`complete(prompt, max_tokens)` · `status()` · `available()` · `set_provider(name)` ·
`logout(provider)` · `launch_login(provider)` · `login_cmd(provider)`

## 백엔드가 만족해야 하는 인터페이스
영상공방 `services/llm_backend.py` 규약:
- `status_all()`, `get_provider()`, `set_provider()`, `login_cmd()`, `_modules()`
- `active_client().chat(model, [{"role":"user","content":...}], max_tokens=N).text`
- (TTS) `voicewright.engine.Engine.get()` + `engine.synth(text, voice_code, speed)` + `audio_io.write_wav`

## 재사용 키트 (다른 앱에도 드롭인)
이 브리지는 독립 키트로도 패키징되어 있습니다: **`oauth-llm-bridge`** (zip).
```
oauth-llm-bridge/
  llm_kit.py          핵심 모듈(복사해서 사용)
  fastapi_router.py   make_llm_router() → /api/llm/* 드롭인 라우터
  ui_snippet.html     공급자 토글·로그인·로그아웃 패널 예시
  README.md
```
새 프로젝트: `llm_kit.py` 복사 → 환경변수 `LLM_BRIDGE_DIR` 지정 → `import llm_kit; llm_kit.complete(...)`.

## 백엔드가 없을 때 (영상공방 미설치) — 자동 폴백
`shortsmaker/llm.py` 가 백엔드 유무를 보고 자동 분기합니다:
- **LLM** → 내장 `cli_llm.py` 가 **codex/agy CLI 를 직접 호출**(영상공방 코드 복사 X). CLI 설치+로그인만 하면 AI 작동.
- **TTS** → `tts.py` 가 **edge-tts**(무료·온라인) 로 폴백. 없으면 번들 기존 음성.

즉 영상공방 없이도 **codex/agy CLI(+로그인) + edge-tts** 만으로 풀 기능이 됩니다.
영상공방이 있으면(= `services/llm_backend.py` + `venv` 탐지) 그 OAuth 세션·SuperTonic 을 우선 사용합니다.
