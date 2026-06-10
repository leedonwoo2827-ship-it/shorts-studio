# 아키텍처

## 전체 흐름
```
번들(chNN_bundle)
  → build_default_spec   : 핵심 씬 선별 + 초안(후크/자막/길이/오디오) 채움
  → AI 채움(gen_fill)     : (B) LLM이 후크·해시태그·구어체 자막 생성
  → 검증(verify/flow)     : (B) 사실/흐름 점검, 인라인 근거+대안 (내용 안 바꿈)
  → 음성 싱크(tts)        : (B) 자막→선택 목소리/속도 TTS → 길이에 맞춰 싱크
  → build_shorts          : 9:16 합성(비트 렌더 → concat → ASS 오버레이 → 오디오 mux)
```

## 모듈
| 파일 | 역할 |
|---|---|
| `app.py` | FastAPI 서버 + 모든 API + 인메모리 잡 + 정적 SPA 서빙(캐시버스팅) |
| `shortsmaker/bundle.py` | 번들 로더(스크립트 JSON 파싱, 이미지·오디오·자막 경로 매칭) |
| `shortsmaker/ffmpeg_runner.py` | ffmpeg/ffprobe 래퍼(실행·길이측정·로그) |
| `shortsmaker/fonts.py` | 한글 폰트 탐색(Pretendard→나눔→맑은고딕) |
| `shortsmaker/kenburns.py` | 장면 인덱스 기반 결정론적 줌/팬 식 |
| `shortsmaker/shorts.py` | **편집형 spec 컴포지터**(레이아웃·렌더 핵심) |
| `shortsmaker/llm.py` | 쇼츠 전용 프롬프트(후크/자막/검증/흐름/메타) — `llm_kit` 위 얇은 래퍼 |
| `shortsmaker/llm_kit.py` | OAuth LLM 브리지(드롭인 키트) → [LLM-OAUTH-BRIDGE](LLM-OAUTH-BRIDGE.md) |
| `shortsmaker/tts.py` | VoiceWright(SuperTonic3) 음성 생성 브리지 |
| `static/` | SPA(index.html / app.js / style.css) |

## 렌더 방식 (shorts.py)
1. **비트(beat) 단위 세그먼트 렌더**: 1080×1920 흰 캔버스 위에
   - 중앙 영역에 장면 **이미지**(켄번스) 또는 **롱폼 영상 구간**(음소거, cover-crop) 배치.
   - 좌/우 2분할 콜라주 변형(이미지 모드).
2. **concat**: 세그먼트들을 이어 붙임(무음 영상 트랙).
3. **ASS 오버레이**(libass 번인):
   - 상단 흰 띠: 플레이어 아이콘(벡터) + **2색 후크**(1줄/2줄 색·크기 개별).
   - 중간 하단: **음성 자막**(반투명 박스).
   - 하단 흰 띠: **해시태그 2줄**(초과분은 잘림).
4. **오디오 mux**: 음성 베드 결합. 속도는 TTS 엔진(`speed`)에서 적용하거나, 기존 음성이면 `atempo`로 가속(이중 적용 방지).

레이아웃 밴드(상/중/하)는 캔버스 높이 비율 기반 → `ShortsConfig.width/height`만 바꾸면 가로(16:9) 등으로 확장 가능.

## 비주얼 소스 선택 규칙
- 번들 `draft/chNN_final_nosub.mp4`(**자막 없는 클린 롱폼**)가 있으면 → 그 영상 구간을 음소거해 사용.
- 없으면(자막이 박힌 `_final.mp4`만 있거나 영상 없음) → **번들 이미지 + 켄번스**로 폴백
  (옛 자막이 겹치는 사고 방지).

## 주요 API (FastAPI)
| 메서드·경로 | 설명 |
|---|---|
| `GET /api/health` | 폰트·LLM 상태·번들 루트 |
| `GET /api/bundles` | 번들 목록 |
| `POST /api/spec` | 번들 → 편집용 spec 초안 |
| `POST /api/scenes` | 번들 전체 씬(추가용) |
| `GET /api/image?path=` | 번들 이미지 미리보기 |
| `POST /api/ai-fill` | 후크·해시태그·자막 생성(only=hook|captions) |
| `POST /api/verify` | 씬별 사실 검증(평가+대안) |
| `POST /api/flow-review` | 전체 흐름 평가(읽기 전용) |
| `POST /api/tts-sync` | 자막→음성 생성·concat + 비주얼 정보(잡) |
| `POST /api/render` | 9:16 합성(잡) |
| `GET /api/video/{job}` / `shorts 미리보기` | 결과 서빙 |
| `POST /api/meta` | 유튜브 쇼츠 메타 |
| `GET/POST /api/hooks` | 후크 보관함(data/hooks.json) |
| `GET/POST /api/llm/{status,provider,login,logout}` | LLM 계정 관리 |
