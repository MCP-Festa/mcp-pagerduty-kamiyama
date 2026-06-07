#!/usr/bin/env bash
# Import Codex or Claude Code sessions into the MLflow container.
#
# Usage:
#   ./scripts/import.sh claude-latest
#   ./scripts/import.sh codex-latest
#   ./scripts/import.sh claude  /path/to/session.jsonl
#   ./scripts/import.sh codex   /path/to/session.jsonl
#
# Environment variables:
#   CLAUDE_SESSIONS_DIR   host path for Claude projects  (default: ~/.claude/projects)
#   CODEX_SESSIONS_DIR    host path for Codex sessions   (default: ~/.codex/sessions)
#   EXPERIMENT            MLflow experiment name override

set -euo pipefail

TRACKING_URI="sqlite:////data/mlflow.db"
COMPOSE_FILE="$(cd "$(dirname "$0")/.." && pwd)/docker-compose.yml"

run_import() {
  docker compose -f "$COMPOSE_FILE" run --rm "$@"
}

usage() {
  echo "Usage: $0 <command> [session_file]"
  echo "Commands:"
  echo "  claude-latest   Import the most recent Claude Code session"
  echo "  codex-latest    Import the most recent Codex session"
  echo "  claude <file>   Import a specific Claude Code session JSONL"
  echo "  codex  <file>   Import a specific Codex session JSONL"
  exit 1
}

[[ $# -lt 1 ]] && usage

CMD=$1
shift

case "$CMD" in
  claude-latest)
    HOST_DIR="${CLAUDE_SESSIONS_DIR:-$HOME/.claude/projects}"
    run_import \
      -v "$HOST_DIR:/sessions/claude:ro" \
      mlflow mlflow-codex import-claude-latest \
        --sessions-dir /sessions/claude \
        --tracking-uri "$TRACKING_URI" \
        --experiment "${EXPERIMENT:-claude-traces}"
    ;;

  codex-latest)
    HOST_DIR="${CODEX_SESSIONS_DIR:-$HOME/.codex/sessions}"
    run_import \
      -v "$HOST_DIR:/sessions/codex:ro" \
      mlflow mlflow-codex import-latest \
        --sessions-dir /sessions/codex \
        --tracking-uri "$TRACKING_URI" \
        --experiment "${EXPERIMENT:-codex-traces}"
    ;;

  claude)
    [[ $# -lt 1 ]] && { echo "error: session file path required"; usage; }
    SESSION_FILE=$(realpath "$1")
    run_import \
      -v "$SESSION_FILE:/sessions/session.jsonl:ro" \
      mlflow mlflow-codex import-claude /sessions/session.jsonl \
        --tracking-uri "$TRACKING_URI" \
        --experiment "${EXPERIMENT:-claude-traces}"
    ;;

  codex)
    [[ $# -lt 1 ]] && { echo "error: session file path required"; usage; }
    SESSION_FILE=$(realpath "$1")
    run_import \
      -v "$SESSION_FILE:/sessions/session.jsonl:ro" \
      mlflow mlflow-codex import /sessions/session.jsonl \
        --tracking-uri "$TRACKING_URI" \
        --experiment "${EXPERIMENT:-codex-traces}"
    ;;

  *)
    usage
    ;;
esac
