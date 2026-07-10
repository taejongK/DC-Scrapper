#!/usr/bin/env bash
# DCInside 대시보드 종료 스크립트
#
# 사용법:
#   ./stop.sh                # 실행 중인 대시보드(uvicorn webapp.main:app) 전부 종료
#   ./stop.sh --port 8000    # 특정 포트에서 도는 프로세스만 종료
#   ./stop.sh --force        # TERM 후에도 남아있으면 KILL로 강제 종료

set -uo pipefail
cd "$(dirname "$0")"

PORT=""
FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)  PORT="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) awk 'NR>1 && /^#/{sub(/^# ?/,"");print;next} NR>1{exit}' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
  esac
done

# 대상 PID 수집
if [[ -n "$PORT" ]]; then
  PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  LABEL="포트 $PORT"
else
  PIDS=$(pgrep -f "uvicorn webapp.main:app" 2>/dev/null || true)
  LABEL="uvicorn webapp.main:app"
fi

if [[ -z "$PIDS" ]]; then
  echo "실행 중인 대시보드가 없습니다 ($LABEL)."
  exit 0
fi

echo "▶ 종료 대상($LABEL): $(echo "$PIDS" | tr '\n' ' ')"
kill $PIDS 2>/dev/null || true

# 정상 종료 대기
for i in $(seq 1 10); do
  sleep 0.3
  REMAIN=$(for p in $PIDS; do kill -0 "$p" 2>/dev/null && echo "$p"; done)
  [[ -z "$REMAIN" ]] && break
done

if [[ -n "${REMAIN:-}" ]]; then
  if [[ "$FORCE" == "1" ]]; then
    echo "⚠ 남은 프로세스 강제 종료(KILL): $REMAIN"
    kill -9 $REMAIN 2>/dev/null || true
  else
    echo "⚠ 아직 종료되지 않은 프로세스: $REMAIN"
    echo "  강제 종료하려면: ./stop.sh --force"
    exit 1
  fi
fi

echo "✅ 대시보드를 종료했습니다."
