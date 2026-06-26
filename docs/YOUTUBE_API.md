# YouTube 조회수 연동 (Phase 3) — 경로 A / B

캠페인으로 발행한 쇼츠의 **조회수**를 모아 *어떤 MBTI/장/후크 스타일이 잘 맞는지* 인사이트를 얻기 위한
YouTube API 연동 절차. 두 경로가 있고, **목적이 조회수면 경로 A(API 키) 하나로 충분**하다.

| | 경로 A · API 키 | 경로 B · OAuth |
|---|---|---|
| 얻는 것 | **공개 통계**: 조회수·좋아요·댓글수 | + **비공개 분석**: 시청 지속시간·CTR·노출수·시청자 지역/연령 |
| API | YouTube **Data** API v3 | YouTube **Analytics** API (+ Data) |
| 인증 | API 키 1개 (사용자 동의 불필요) | OAuth 2.0 동의 흐름 |
| 난이도 | 쉬움 | 중간(동의 화면·토큰 관리) |
| 권장 | ✅ **여기서 시작** | 심화 분석이 필요할 때만 |

> **경로 A만으로도 인사이트가 나온다.** 영상별 조회수를 (장 × MBTI)에 매핑하면 **MBTI별·장별·후크스타일별
> 평균 조회수**를 집계할 수 있어 "이 책류 숏폼엔 어떤 유형 후크가 잘 먹히나"라는 1차 결론이 나온다.
> 경로 B는 *왜 잘됐나*(지속시간·CTR)를 더해주는 심화일 뿐, 없어도 된다.

---

## 현재 설정 (이 프로젝트)
| 항목 | 값 |
|---|---|
| Google 계정 | `ubionbooktv@gmail.com` |
| 채널 | https://www.youtube.com/@ubionbooktv/shorts |
| GCP 프로젝트 이름 | `short-studio` |
| GCP 프로젝트 ID | `short-studio-500623` |
| 사용 설정 API | **YouTube Data API v3** (경로 A) |
| API 키 | 발급 후 `.env`의 `YOUTUBE_API_KEY=` 에만 보관(레포에 커밋 안 함) |
| 결제 | 불필요(무료 쿼터, 카드 미등록) |

> 진행 체크: ① 프로젝트 생성 ✅ ② YouTube Data API v3 사용 설정 ✅ ③ API 키 발급 → `.env` (다음 단계)

## 경로 A — API 키 (권장)

### 발급 절차
1. **Google Cloud Console** (console.cloud.google.com) → **프로젝트 생성** (예: `shorts-studio`).
2. **API 및 서비스 → 라이브러리** → "**YouTube Data API v3**" → **사용 설정(Enable)**.
3. **사용자 인증 정보 → 사용자 인증 정보 만들기 → API 키**.
4. (권장) 생성된 키 → **키 제한 → API 제한 → "YouTube Data API v3"만** 선택(유출 대비).
5. `.env`에 `YOUTUBE_API_KEY=...` 추가.

> LLM에 쓰는 agy/Gemini의 Google 로그인과 **YouTube API 키는 별개**다. 위 절차로 키를 따로 만들어야 한다.

### 호출 예시
```
# 영상 ID들의 조회수 (한 번에 최대 50개, 비용 1 unit)
GET https://www.googleapis.com/youtube/v3/videos?part=statistics&id=ID1,ID2&key=KEY
 → items[].statistics.viewCount / likeCount / commentCount

# 채널(@ubionbooktv)의 업로드 목록
GET .../channels?part=contentDetails&forHandle=ubionbooktv&key=KEY
 → items[0].contentDetails.relatedPlaylists.uploads  (업로드 플레이리스트 ID)
GET .../playlistItems?part=contentDetails&playlistId=<uploads>&maxResults=50&key=KEY
 → items[].contentDetails.videoId   (페이지네이션: nextPageToken)
```
- 쇼츠도 일반 영상과 동일하게 잡힌다.
- **쿼터**: 기본 **10,000 units/일**. `videos.list`는 호출당 **1 unit**(50개 묶음) → 조회수 폴링엔 충분.
  ⚠️ `search.list`는 **100 units**라 가급적 쓰지 않는다(업로드 목록은 위 playlistItems 경로 사용).

---

## 경로 B — OAuth (심화, 선택)
시청 지속시간·평균 시청률·노출 클릭률(CTR)·시청자 통계는 **YouTube Analytics API + OAuth 2.0** 필요.
1. 경로 A의 1~2단계(프로젝트 + API 사용 설정)에 더해 **YouTube Analytics API**도 Enable.
2. **OAuth 동의 화면** 구성(내부/본인 채널용) → **OAuth 클라이언트 ID(데스크톱앱)** 발급.
3. 최초 1회 브라우저 동의 → refresh token 저장 → 이후 자동 갱신.
4. `reports.query`로 `estimatedMinutesWatched`, `averageViewPercentage`, `views`, `impressionsCtr` 등 조회.

본인 채널이라 가능하지만 토큰 관리가 늘어난다. **조회수 인사이트가 목적이면 A로 시작**하고, 더 깊게 볼 때 B를 추가.

---

## 앱 연동 (구현 시)
스키마에 자리는 이미 있음: `slot.youtube_video_id`, `view_stat(slot_id, fetched_at, view_count)`
([shortsmaker/campaign.py](../shortsmaker/campaign.py)).

1. `.env`에 `YOUTUBE_API_KEY` 설정.
2. 마스터 리스트의 **생산** 행에 **업로드한 쇼츠 URL/ID 입력** 칸 — 영상↔(장,MBTI) 셀 연결(업로드는 수동).
3. **[조회수 갱신]** → 모든 `youtube_video_id`를 50개씩 묶어 `videos.list` → `view_stat`에 일자별 적재.
4. **인사이트 집계**: MBTI별·장별 평균/중앙 조회수 → 표·차트. (경로 B 연동 시 지속시간·CTR 컬럼 추가)

관련: [SERIES.md](SERIES.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
