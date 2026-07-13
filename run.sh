#!/usr/bin/env bash
# DCInside 수집·분석 대시보드 실행 스크립트
#
# 사용법:
#   ./run.sh                 # 기본(포트 8000, DB=dcinside.db)로 대시보드 실행
#   ./run.sh --port 9000     # 포트 지정
#   PORT=9000 DB=my.db ./run.sh
#   ./run.sh --setup         # venv 생성 + 의존성 설치 후 실행
#
# 환경변수:
#   PORT  (기본 8000)         HOST (기본 127.0.0.1)
#   DB    (기본 dcinside.db)  RELOAD=1 이면 코드 변경 시 자동 리로드

set -euo pipefail
cd "$(dirname "$0")"

# .env 자동 로드 (있으면). API 키 등 로컬 환경변수를 export 한다 (.env 값이 적용됨).
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

VENV=".venv"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
DB="${DB:-dcinside.db}"
RELOAD="${RELOAD:-0}"
DO_SETUP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --setup) DO_SETUP=1; shift ;;
    --port)  PORT="$2"; shift 2 ;;
    --host)  HOST="$2"; shift 2 ;;
    --db)    DB="$2"; shift 2 ;;
    --reload) RELOAD=1; shift ;;
    -h|--help) awk 'NR>1 && /^#/{sub(/^# ?/,"");print;next} NR>1{exit}' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
  esac
done

# venv 준비
if [[ ! -d "$VENV" ]]; then
  echo "▶ 가상환경이 없어 생성합니다 ($VENV)"
  python3 -m venv "$VENV"
  DO_SETUP=1
fi
PY="$VENV/bin/python"

# 의존성 설치 (--setup 또는 핵심 패키지 미설치 시)
if [[ "$DO_SETUP" == "1" ]] || ! "$PY" -c "import fastapi, pandas, kiwipiepy, anthropic" 2>/dev/null; then
  echo "▶ 의존성 설치 중…"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -e ".[web,analysis,llm]"
fi

# DB 존재 확인 (경고만)
if [[ ! -f "$DB" ]]; then
  echo "⚠ DB 파일이 없습니다: $DB"
  echo "  먼저 수집을 실행하거나 대시보드의 '수집' 탭에서 데이터를 모으세요:"
  echo "    $PY -m dc_scraper --db-path $DB --verbose"
fi

# LLM 심층분석 키 안내 (선택 기능)
if [[ -z "${OPENROUTER_API_KEY:-}" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ℹ LLM 심층분석을 쓰려면 API 키를 설정하세요 (미설정 시 다른 분석은 정상 동작):"
  echo "    export OPENROUTER_API_KEY=sk-or-v1-...   # 권장. 모델: export DC_LLM_MODEL=anthropic/claude-sonnet-5"
  echo "    export ANTHROPIC_API_KEY=sk-ant-...      # 또는 Anthropic 직접"
fi

RELOAD_FLAG=""
[[ "$RELOAD" == "1" ]] && RELOAD_FLAG="--reload"

echo "▶ 대시보드 실행: http://$HOST:$PORT  (DB=$DB)"
echo "  종료: Ctrl+C"
exec env DC_DB_PATH="$DB" "$PY" -m uvicorn webapp.main:app \
  --host "$HOST" --port "$PORT" $RELOAD_FLAG
