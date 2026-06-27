# prompts/ — 스킬 프롬프트 모음

쇼츠공방의 LLM "스킬"별 프롬프트를 **코드 밖 텍스트 파일**로 둔 곳. 코드를 안 건드리고 프롬프트만
수정/실험할 수 있다. `shortsmaker/llm.py`가 `_prompt(name, **vars)`로 로드해 `{토큰}`을 치환한다.

## 치환 규칙
- 템플릿의 `{key}` 가 `_prompt(name, key=값)`의 값으로 **단순 치환**된다(`str.replace`).
- 공통 규칙은 자동 주입: `{indep}`(독립 완결 문장), `{ground}`(단어 그라운딩). 정의는 `llm.py`의 `_INDEP`,`_GROUND` 상수.
- 프롬프트 안에 `{` `}` 리터럴을 쓰지 말 것(치환과 충돌). 출력 예시는 중괄호 없이.

## 스킬 목록
| 파일 | 함수(llm.py) | 용도 | 주요 토큰 |
|---|---|---|---|
| `hook.md` | suggest_hook | 단일 후크 | current, narration |
| `caption.md` | suggest_caption | 단일 자막 | indep, current, narration |
| `fill.md` | gen_fill | 후크+해시태그+자막 일괄(일반) | indep, fmt, title, briefs, review |
| `verify.md` | verify_captions | 사실 검증(평가+대안) | indep, items |
| `tidy.md` | tidy_all | 전체 자막 1회 재작성 | indep, items |
| `meta.md` | shorts_meta | 유튜브 메타 | link, title_hint_block, content |
| `mbti_hooks.md` | gen_mbti_hooks | **MBTI 16유형 후크 일괄** | mood_rule, indep, ground, mbti_list, title, briefs |
| `mbti_hook_one.md` | gen_one_mbti_hook | **MBTI 단일 후크 재생성** | mbti, mood_line, indep, ground, title, briefs |
| `mbti_captions.md` | gen_mbti_captions | **MBTI 무드 자막 재생성** | mbti, mood_line, indep, last_idx, title, items |

## 새 스킬 추가 (예: MBTI 분석)
1. `prompts/<name>.md` 작성(`{토큰}` 사용).
2. `llm.py`에 `def <fn>(...): raw = complete(_prompt("<name>", ...)); return _parse(raw)`.
3. 필요 시 `app.py` 라우트 + UI 버튼 연결.

> 원칙은 `knowledges/` 참고: 그라운딩·독립 완결 문장·형식 강제·검증 분리(5단계 방어망).
> 무드/페르소나는 **어조로만**, 단어는 **원본에서**(`{ground}`).
