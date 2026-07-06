# 시리즈 자산 위치 (현재 활성 시리즈)

> 쇼츠 시리즈의 **물리적 input/output 위치**를 한 곳에서 관리한다. 시리즈를 바꾸면 이 문서의 경로만 갱신.
> (실제 자산 폴더 `_series\`와 `data\`는 깃에 올리지 않음 — `.gitignore` 처리.)

## 활성 시리즈: `baeum` (배움을 설계하는 기술의 역사)

| 구분 | 경로 | 내용 |
|---|---|---|
| **입력 input** | `D:\00work\_series\baeum\input` | `chNN_bundle\` (각 `script\` + `images\` [+ `subtitles\`]) |
| **출력 output** | `D:\00work\_series\baeum\output` | 렌더된 쇼츠 `<chapter>_<id>_shorts.mp4` |
| 캠페인 DB (공유) | `D:\00work\260607-youtube\data\campaign.db` | 후크 뱅크·스케줄·생산 로그 (모든 시리즈 통합) |
| 활성 플래그 | `D:\00work\260607-youtube\data\active_series.txt` | 현재 활성 시리즈명 (캠페인 탭에서 전환) |

- 입력은 `script`(chNN_script.json) + `images`만 필수. **오디오·영상 불필요**(쇼츠가 자막으로 TTS 재생성).
- 루트 설정: `.env`의 `SHORTS_SERIES_ROOT=D:\00work\_series`.

## 등록된 시리즈
| 시리즈 | input | 상태 |
|---|---|---|
| `baeum` | `D:\00work\_series\baeum\input` | 활성 |
| `worldhistory` | `D:\00work\_series\worldhistory\input` | 보관(세계사) |

## 폴더 배치 & 인식 규칙
```
<SHORTS_SERIES_ROOT>\
   ├─ <시리즈>\
   │   ├─ input\   ch01_bundle\(script\ + images\ [+ subtitles\]) · ch02_bundle\ · …
   │   └─ output\  (렌더 결과 자동 저장, 비워둠)
   └─ …
```
- `SHORTS_SERIES_ROOT`가 설정되면 **이게 우선**(레거시 `SHORTS_BUNDLE_ROOTS`는 무시).
- 번들 드롭다운엔 **활성 시리즈의 `input`** 안 `chNN_bundle`만 표시.
- **활성 시리즈** = `data/active_series.txt`. 캠페인 탭 상단 **시리즈 드롭다운**에서 전환(파일 자동 갱신).
- 폴더명은 반드시 **`chNN_bundle`**(2자리, 예 `ch01_bundle`). `01장-<hash>` 같은 편집 세션 폴더는 **인식 안 됨**.
- 각 번들은 **`script/chNN_script.json` + `images/`만 있으면 인식**(오디오·자막·영상 선택).

## 새 시리즈 추가 시
1. `D:\00work\_series\<새시리즈>\{input,output}` 폴더 생성
2. `<새시리즈>\input`에 `chNN_bundle` 배치(`script`+`images`)
3. 캠페인 탭에서 시리즈 전환(또는 `data\active_series.txt` 갱신)
4. **이 문서의 "활성 시리즈" 표를 갱신**
