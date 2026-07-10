# DCInside 커뮤니티 수집·분석 도구

특정 커뮤니티(DCInside 갤러리)의 여론을 주기적으로 수집해 DB화하고, 웹 대시보드에서
조회·분석하는 도구입니다.

---

## 1. 프로젝트 개요

DCInside 마이너 갤러리의 글을 **수집 → 저장 → 분석**하는 세 층으로 구성된 도구입니다.

- **수집기(`dc_scraper`)** — 지정한 날짜/기간의 글을 목록 + 본문 + 댓글까지 긁어 SQLite에 저장
- **분석 엔진(`analysis`)** — 수집된 데이터를 통계·시계열·키워드·감성·연관어로 분석
- **웹 대시보드(`webapp`)** — 브라우저에서 수집 실행·글 조회·분석 차트를 확인

기본 대상: [AI 채팅 마이너 갤러리](https://gall.dcinside.com/mgallery/board/lists?id=aichatting) (`id=aichatting`)

```
dc_scraper/   수집기 (CLI: python -m dc_scraper)
analysis/     분석 엔진 (stats·timeseries·keywords·sentiment)
webapp/       FastAPI 웹 대시보드 (webapp/static = 프론트엔드)
run.sh        대시보드 실행 스크립트
stop.sh       대시보드 종료 스크립트
dcinside.db   수집 데이터 (SQLite, 자동 생성)
```

---

## 2. 목적

- 특정 커뮤니티의 **여론·반응을 주기적으로 수집**해 시간이 지나도 사라지지 않는 데이터로 축적한다.
- 축적된 데이터에서 **무엇이 화제인지(키워드), 분위기가 어떤지(감성), 언제 활발한지(시계열)**,
  특정 주제에 어떤 이야기가 엮이는지(연관어)를 **한눈에 파악**한다.
- 수집·조회·분석을 **코드를 몰라도 웹 UI에서** 다룰 수 있게 한다.

---

## 3. 기능 및 각 기능이 하고싶은 것

### 🗂️ 수집 (dc_scraper)
| 기능 | 하고싶은 것 |
|---|---|
| 날짜/기간 지정 수집 | 오늘·특정일·기간(`--date-from ~ --date-to`)의 글을 빠짐없이 모은다 |
| 목록 + 본문 + 댓글 | 제목/작성자/조회/추천뿐 아니라 본문 텍스트와 댓글(대댓글 계층)까지 수집한다 |
| 멱등 저장 | `post_no`·`(post_no, comment_no)` 기준 upsert로 재실행해도 중복이 안 쌓인다 |
| 공지 제외 | 말머리가 "공지"인 행은 자동 제외하고 실제 글만 수집한다 |
| 성인글 플래그 | 로그인 필요한 NSFW 글은 메타만 저장하고 `is_adult=1`로 구분한다 |
| 매너 수집 | 요청 간 딜레이·백오프로 차단(403/429)을 피하고, 개별 글 실패가 전체를 멈추지 않는다 |

### 📊 분석 (analysis)
| 기능 | 하고싶은 것 |
|---|---|
| 인기글 랭킹/통계 | 추천·조회·댓글 기준 상위 글과 전체 통계(글/댓글/작성자/평균)를 본다 |
| 시계열 활동 추이 | 날짜별·시간대별·요일별로 언제 글이 활발한지 파악한다 |
| 키워드 빈도 | 형태소 분석으로 제목/본문/댓글에서 자주 나온 단어를 뽑는다 |
| ☁️ 워드클라우드 | 키워드 빈도를 시각적으로 보여준다 (단어 클릭 → 연관어 분석) |
| 🔗 연관어 분석 | 특정 키워드가 나오는 글에서 **함께 등장하는 단어**(공기 분석)를 찾는다 |
| 💬 감성/여론 분석 | 글·댓글의 긍정/부정/중립 분포로 여론 분위기를 가늠한다 |
| 🔎 키워드 필터 | 특정 단어가 포함된 글(+댓글)만 대상으로 위 분석을 다시 계산한다 |

### 🖥️ 대시보드 (webapp)
| 탭 | 하고싶은 것 |
|---|---|
| 📥 수집 | 갤러리·날짜/기간·옵션을 지정해 수집을 실행하고 진행 상태·이력을 본다 |
| 📋 글 목록 | 검색·정렬·말머리 필터로 글을 찾고, 클릭 시 본문+댓글 상세를 본다 |
| 📊 분석 | 위 분석 기능들을 차트로 확인한다 (상단 필터바로 갤러리·날짜·키워드 범위 지정) |

> **감성 분석**은 한국어 감성 사전(lexicon) 기반 baseline입니다. 슬랭이 많은 글은 중립으로
> 분류될 수 있으며 `analysis/data/sentiment_ko.json` 보강 또는 모델 교체로 개선할 수 있습니다.

---

## 4. 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 언어 | Python 3.10+ (개발·검증: 3.14) |
| 수집 | `requests` (세션·재시도), `beautifulsoup4` + `lxml` (HTML 파싱), 댓글은 JSON AJAX |
| 저장 | SQLite (표준 `sqlite3`, WAL) — 3테이블(posts / comments / scrape_runs) |
| 분석 | `pandas` (집계), `kiwipiepy` (한국어 형태소 분석, Java 불필요), 사전 기반 감성 |
| 백엔드 | `FastAPI` + `uvicorn` (REST API, 백그라운드 수집 잡) |
| 프론트 | 순수 HTML/CSS/JS + `Chart.js` + `wordcloud2.js` (빌드 스텝 없음, CDN) |
| 테스트 | `pytest` + `httpx`(FastAPI TestClient) — 파서·분석·API 오프라인 테스트 |

---

## 5. 실행 방법

### 5-1. 빠른 시작 (대시보드)

```bash
./run.sh --setup     # 최초: venv 생성 + 의존성 설치 후 실행
./run.sh             # 이후: 대시보드 실행 → http://127.0.0.1:8000
./stop.sh            # 종료
```

`run.sh` 옵션: `--port 9000`(포트) · `--reload`(자동 리로드) · `DB=archive.db ./run.sh`(다른 DB)
`stop.sh` 옵션: `--port 8000`(특정 포트만) · `--force`(강제 종료)

### 5-2. 설치 (수동)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web,analysis,dev]"    # 대시보드+분석+테스트 / 수집만이면: pip install -e .
```

### 5-3. 수집 (CLI)

```bash
python -m dc_scraper --verbose                                   # 오늘자 전부
python -m dc_scraper --date 2026-07-08                           # 특정 날짜
python -m dc_scraper --date-from 2026-07-01 --date-to 2026-07-08 # 기간
python -m dc_scraper --dry-run --verbose                         # 건수만 미리보기(DB 미기록)
python -m dc_scraper --gallery baseball --db-path baseball.db    # 다른 갤러리/DB
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--gallery` | `aichatting` | 갤러리 id |
| `--date` | 오늘(로컬) | 단일 대상 날짜 `YYYY-MM-DD` |
| `--date-from` / `--date-to` | — | 기간 수집(양끝 포함). `--date`와 동시 사용 불가 |
| `--db-path` | `dcinside.db` | SQLite 파일 경로 |
| `--max-pages` | `100` | 리스트 순회 안전 상한 |
| `--delay-min` / `--delay-max` | `1.0` / `2.5` | 요청 간 랜덤 딜레이(초) |
| `--no-comments` | off | 댓글 수집 생략 |
| `--dry-run` | off | 집계만, DB 미기록 |
| `-v, --verbose` | off | 진행 로그 출력 |

### 5-4. 분석 API 직접 호출

대시보드를 실행한 상태에서 `/api/*`를 직접 호출할 수 있습니다 (모두 `q=키워드`로 필터 가능):

```
/api/stats/overview            개요 통계        /api/stats/top?by=recommend    인기글 랭킹
/api/analysis/timeseries?kind=date|hour|weekday  활동 추이
/api/analysis/keywords?source=all&top_n=120      키워드 빈도(워드클라우드용)
/api/analysis/related?word=출력&source=all        연관어(공기) 분석
/api/analysis/sentiment?source=comment           감성 분포
예) /api/stats/overview?q=에덴  → "에덴" 포함 글만 통계
```

### 5-5. 주기적 자동 수집 (선택)

**macOS(launchd)** — `~/Library/LaunchAgents/com.user.dcscraper.plist` 생성 후 매일 정해진 시각 실행:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.user.dcscraper</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/taejongkim/workspace/github/cummunity_scrap/.venv/bin/python</string>
    <string>-m</string><string>dc_scraper</string>
    <string>--db-path</string><string>/Users/taejongkim/workspace/github/cummunity_scrap/dcinside.db</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/taejongkim/workspace/github/cummunity_scrap</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>50</integer></dict>
  <key>StandardOutPath</key><string>/tmp/dcscraper.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/dcscraper.err.log</string>
</dict></plist>
```
```bash
launchctl load   ~/Library/LaunchAgents/com.user.dcscraper.plist   # 등록
launchctl unload ~/Library/LaunchAgents/com.user.dcscraper.plist   # 해제
```

**cron(Linux/macOS)**:
```bash
50 23 * * * cd /Users/taejongkim/workspace/github/cummunity_scrap && .venv/bin/python -m dc_scraper --db-path dcinside.db >> /tmp/dcscraper.log 2>&1
```

> 하루에 여러 번 돌려도 멱등이라 중복이 쌓이지 않습니다.

### 5-6. 테스트

```bash
pytest       # 수집(파싱)·분석·웹 API 오프라인 테스트
```

---

## 참고 / 주의사항

- **성인(NSFW) 글**은 비로그인 상태에서 본문·댓글을 볼 수 없어 메타만 저장되고 `is_adult=1`로 표시됩니다.
  로그인 세션(쿠키) 주입 기능을 추가하면 수집 가능합니다.
- 개인·연구 목적 수집을 전제로 하며, 요청 간 딜레이(기본 1.0~2.5초)로 과도한 트래픽을 피합니다.
- 사이트 HTML 구조가 바뀌면 `dc_scraper/config.py`의 셀렉터/파라미터만 수정하면 됩니다.
- 현재 코드는 **마이너 갤러리(mgallery)** 기준입니다. 일반 갤러리는 `config.py`의
  `GALLERY_KIND`/`GALLTYPE`도 함께 바꿔야 합니다.
- 조회 예시:
  ```bash
  sqlite3 dcinside.db "SELECT title, recommend, comment_cnt FROM posts ORDER BY recommend DESC LIMIT 10;"
  ```
