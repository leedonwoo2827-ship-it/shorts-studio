# 쇼츠공방 (Shorts Studio)

영상공방(VOD Studio) 번들에서 **세로 9:16 쇼츠**를 만드는 독립 웹앱.
씬마다 **상단 후크 / 하단 자막을 직접 편집**한 뒤 렌더한다. 엔진은 이 폴더에 자립(self-contained),
LLM은 영상공방의 **OAuth 로그인 기반 백엔드(codex/agy)** 를 그대로 재사용한다(별도 API 키 없음).

## 스타일
3분할이 구간마다 변동 — 상단 후크(노랑) · 중앙 장면 이미지(켄번스) · 하단 자막(흰색),
마지막에 "▶ 전체 영상" CTA. 캔버스 크기는 설정값(`ShortsConfig.width/height`)이라 가로(16:9)로도 전환 가능.

## 빠른 시작
```
setup.bat      # venv 생성 + 의존성 설치 + .env 준비
run.bat        # http://127.0.0.1:7010
```
- ffmpeg/ffprobe 는 PATH 에 필요 (`winget install Gyan.FFmpeg`)
- LLM 제안/메타를 쓰려면 codex(또는 agy) CLI 에 1회 로그인되어 있어야 함

## 워크플로우
1. **번들 선택** → `✨ 씬 자동 구성` (핵심 씬 자동 선별 + 문구 초안)
2. **씬 편집** — 씬마다 후크/자막 수정, `✨`로 AI 제안, ↑↓ 순서, ✕ 삭제, ＋ 씬 추가
3. **쇼츠 생성** — 원본 URL·CTA 입력 → 렌더 → 9:16 미리보기/다운로드
4. **메타 생성** — 제목·설명(원본 링크)·태그·고정댓글

## 구조
- `app.py` — FastAPI 서버 + API
- `shortsmaker/` — 자립 엔진: `bundle.py` `ffmpeg_runner.py` `fonts.py` `kenburns.py` `shorts.py`(편집형 spec 컴포지터) `llm.py`(OAuth 백엔드 재사용)
- `static/` — SPA (index.html / app.js / style.css)
- `data/` — 렌더 출력(.gitignore)

## 설정(.env)
- `SHORTS_VODSTUDIO_DIR` — 영상공방 경로(LLM 백엔드 위치)
- `LLM_PROVIDER` — codex | agy
- `SHORTS_BUNDLE_ROOTS` — 번들 검색 폴더(세미콜론 구분)
