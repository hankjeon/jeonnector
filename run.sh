#!/usr/bin/env bash
# 전연결기(jeonnector) 실행 스크립트 (리눅스·macOS용, run.ps1 대응)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "가상환경(.venv)을 찾을 수 없습니다: $VENV_PYTHON" >&2
  echo "먼저 'python3 -m venv .venv' 및 패키지 설치를 수행해 주세요." >&2
  exit 1
fi

SRC_PATH="$PROJECT_ROOT/src"
if [[ -z "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="$SRC_PATH"
else
  case ":$PYTHONPATH:" in
    *":$SRC_PATH:"*) ;;
    *) export PYTHONPATH="$SRC_PATH:$PYTHONPATH" ;;
  esac
fi

exec "$VENV_PYTHON" -m jeonnector.main "$@"
