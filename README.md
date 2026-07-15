# DCInside 커뮤니티 수집·분석 도구

특정 커뮤니티(DCInside 갤러리)의 여론을 주기적으로 수집해 DB화하고, 웹 대시보드에서
조회·분석하는 도구입니다.

---

## 1. 프로젝트 개요

DCInside 마이너 갤러리의 글을 **수집 → 저장 → 분석**하는 세 층으로 구성된 도구입니다.

- **수집기(`dc_scraper`)** — 지정한 날짜/기간의 글을 목록 + 본문 + 댓글까지 긁어 SQLite에 저장
- **분석 엔진(`analysis`)** — 수집된 데이터를 통계·이슈 버스트·요일×시간 히트맵·키워드 빈도로 집계하고,
  **LLM 에이전트**가 자연어 질문에 대해 코퍼스를 탐색해 구조화 리포트로 답한다
- **웹 대시보드(`webapp`)** — 브라우저에서 수집 실행·글 조회·분석 차트·심층 리포트를 확인

기본 대상: [AI 채팅 마이너 갤러리](https://gall.dcinside.com/mgallery/board/lists?id=aichatting) (`id=aichatting`)

> 📐 내부 구조·데이터 흐름·LLM 플로우는 [docs/architecture.md](docs/architecture.md) 참고.

```
dc_scraper/   수집기 (CLI: python -m dc_scraper)
analysis/     분석 엔진 (stats·keywords·trends·timeseries + llm/llm_report/llm_agent)
webapp/       FastAPI 웹 대시보드 (webapp/static = 프론트엔드)
run.sh        대시보드 실행 스크립트
stop.sh       대시보드 종료 스크립트
dcinside.db   수집 데이터 (SQLite, 자동 생성)
```

---

## 2. 목적

- 특정 커뮤니티의 **여론·반응을 주기적으로 수집**해 시간이 지나도 사라지지 않는 데이터로 축적한다.
- 축적된 데이터에서 **무엇이 화제인지(키워드·워드클라우드), 언제 활발한지(요일×시간 히트맵),
  오늘 뭐가 터졌는지(이슈 버스트)**를 한눈에 파악한다.
- **자연어로 질문하면** LLM 에이전트가 커뮤니티 은어까지 찾아가며 관련 글·댓글을 전수 분석해
  근거 링크가 달린 **구조화 리포트**로 답한다.
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
| 삭제 감지 | 재수집 시 원본에서 사라진 글·댓글은 삭제하지 않고 `is_deleted=1`/`deleted_at`로 표시해 보존한다(아카이브 목적) |
| 매너 수집 | 요청 간 딜레이·백오프로 차단(403/429)을 피하고, 개별 글 실패가 전체를 멈추지 않는다 |

### 📊 분석 (analysis)
| 기능 | 하고싶은 것 |
|---|---|
| 인기글 랭킹/통계 | 추천·조회·댓글 기준 상위 글과 전체 통계(글/댓글/작성자/평균)를 본다 |
| 🗓️ 요일×시간 히트맵 | 요일과 시간대를 교차해 활동 피크 구간을 한눈에 본다 |
| 🔥 이슈 버스트 | 과거 대비 **급상승·신규 등장 키워드**로 "오늘의 떡밥"을 잡는다 |
| ☁️ 워드클라우드 | 형태소 분석으로 제목/본문/댓글에서 자주 나온 단어를 크기로 보여준다 (단어 클릭 → 심층 리포트 질문창에 채움) |
| 🔎 키워드 필터 | 특정 단어가 포함된 글(+댓글)만 대상으로 위 분석을 다시 계산한다 |
| 🧠 심층 리포트 | 자연어 질문을 받으면 에이전트가 **커뮤니티 은어·동의어까지 검색어를 발굴**하고 관련 글·댓글을 전수 map-reduce로 읽어 **개요·분위기·주제·긍정·부정·쟁점·대표 인용**을 근거 링크와 함께 정리한다. 질문·답변은 이력으로 로깅된다 |

### 🖥️ 대시보드 (webapp)
| 탭 | 하고싶은 것 |
|---|---|
| 📥 수집 | 갤러리·날짜/기간·옵션을 지정해 수집을 실행하고 진행 상태·이력을 본다 |
| 📋 글 목록 | 검색·정렬·말머리 필터로 글을 찾고, 클릭 시 본문+댓글 상세를 본다 |
| 📊 분석 | 위 통계·버스트·히트맵·워드클라우드를 차트로 확인한다 (상단 필터바로 갤러리·날짜·키워드 범위 지정) |
| 🧠 리포트 | 자연어 질문을 입력해 심층 리포트를 생성한다 (상단 필터바의 갤러리·기간 범위 안에서 검색) |

> 사전 기반 감성 분석·연관어(PMI)·특징어(TF-IDF)·시계열 추이 API는 신뢰도·중복 문제로
> 제거되었습니다 — 현재는 🧠 심층 리포트(LLM)가 그 역할을 대체합니다. 배경은
> [docs/analysis-improvement-proposal.md §7~§8](docs/analysis-improvement-proposal.md) 참고.

---

## 4. 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 언어 | Python 3.10+ (개발·검증: 3.14) |
| 수집 | `requests` (세션·재시도), `beautifulsoup4` + `lxml` (HTML 파싱), 댓글은 JSON AJAX |
| 저장 | SQLite (표준 `sqlite3`, WAL) — 수집 3테이블(posts / comments / scrape_runs) + 분석 캐시/로그 2테이블(llm_reports / qa_log) |
| 분석 | `pandas` (집계), `kiwipiepy` (한국어 형태소 분석, Java 불필요) — 통계·이슈 버스트·히트맵·워드 빈도 |
| LLM | Claude Sonnet via **OpenRouter**(`requests`) 또는 Anthropic(`anthropic`) — 에이전틱 검색어 발굴(tool-calling) + 글·댓글 map-reduce 심층 리포트, 결과 DB 캐시 |
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
pip install -e ".[llm]"                 # (선택) Anthropic 직접 백엔드 사용 시. OpenRouter는 불필요(requests만 사용)
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

대시보드를 실행한 상태에서 `/api/*`를 직접 호출할 수 있습니다:

```
/api/stats/overview?q=에덴        개요 통계 (q로 키워드 필터)   /api/stats/top?by=recommend   인기글 랭킹
/api/stats/categories             말머리 분포
/api/analysis/heatmap             요일×시간 활동 히트맵
/api/analysis/bursts?date=YYYY-MM-DD&min_count=2   이슈 버스트(급상승·신규 키워드)
/api/analysis/keywords?source=all&top_n=120        키워드 빈도(워드클라우드)
/api/analysis/llm_status                           LLM 사용 가능 여부(키 설정)
POST /api/analysis/ask {"question":"요즘 젬이오 업데이트 반응 어때?"}   🧠 심층 리포트
/api/analysis/ask_history?limit=20                 심층 리포트 질문 이력 목록
/api/analysis/ask_history/{id}                     이력 1건 상세(원본 근거 포함) · DELETE로 삭제
/api/meta/galleries                                갤러리별 글 수·날짜 범위(필터 UI용)
```

**🧠 심층 리포트 설정** — 자연어 질문을 받아 LLM 에이전트가 코퍼스에서 검색어(커뮤니티
은어·동의어 포함)를 먼저 발굴한 뒤, 관련 글·댓글을 전수 map-reduce로 읽어 개요·분위기·주제·
긍정·부정·쟁점·대표 인용을 근거 링크와 함께 정리합니다.
API 키가 있어야 동작하며, 키는 환경변수로만 주입되어 코드에 저장·기록되지 않습니다.
두 백엔드를 지원하며, **키가 설정된 쪽을 자동 감지**합니다(둘 다면 OpenRouter 우선).

가장 간편한 방법은 프로젝트 루트에 `.env`를 두는 것입니다. `run.sh`가 실행 시 **자동으로 읽어**
export 합니다(`.env`는 `.gitignore`로 커밋 제외됨). 템플릿은 `.env.example` 참고:

```bash
cp .env.example .env      # 후 .env 를 열어 실제 키를 채움
./run.sh                  # .env 자동 로드 → 🧠 리포트 탭에서 질문 입력
```

`.env` 내용 예시 (둘 중 하나):

```bash
# 방법 A) OpenRouter (권장 — OpenAI 호환, 추가 SDK 불필요)
OPENROUTER_API_KEY=sk-or-v1-...
DC_LLM_MODEL=anthropic/claude-sonnet-5    # 선택(기본값). 저비용: anthropic/claude-haiku-4.5

# 방법 B) Anthropic 직접 (anthropic SDK 사용, pip install -e ".[llm]" 필요)
ANTHROPIC_API_KEY=sk-ant-...
DC_LLM_MODEL=claude-sonnet-5              # 선택(기본값)
```

`.env` 없이 `export OPENROUTER_API_KEY=...`로 직접 환경변수를 넣어도 동일하게 동작합니다.

내부적으로는 발굴된 검색어로 키워드 심층 리포트 엔진(`llm_report.keyword_report`)을 호출하며,
그 결과는 `dcinside.db`의 `llm_reports` 테이블에 캐시되어 같은 검색어 조합 재조회는
무료·즉시입니다(`새로 분석` 체크 시 재생성). 큰 결과는 map-reduce로 여러 번 나눠 호출하며,
응답 JSON이 깨지면 1회 자동 복구를 시도합니다. 질문·답변·근거·검색어는 `qa_log` 테이블에
로깅되어 `/api/analysis/ask_history`로 조회할 수 있습니다.

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
