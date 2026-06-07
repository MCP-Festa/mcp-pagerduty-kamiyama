from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .claude_session import find_latest_claude_session, load_claude_session
from .codex_session import find_latest_session, load_session
from .tracer import MLflowUnavailableError, import_claude_session_to_mlflow, import_session_to_mlflow


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in ("import", "import-latest"):
        return _run_codex(args)
    if args.command in ("import-claude", "import-claude-latest"):
        return _run_claude(args)

    parser.print_help()
    return 2


def _run_codex(args: argparse.Namespace) -> int:
    if args.command == "import":
        session_path = Path(args.session_jsonl).expanduser()
    else:
        session_path = find_latest_session(args.sessions_dir)

    try:
        session = load_session(session_path)
        trace_id = import_session_to_mlflow(
            session,
            tracking_uri=args.tracking_uri,
            experiment_name=args.experiment,
            include_base_instructions=args.include_base_instructions,
            max_value_chars=args.max_value_chars,
        )
    except (FileNotFoundError, MLflowUnavailableError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"imported_session={session.path}")
    print(f"session_id={session.session_id or ''}")
    print(f"messages={len(session.messages)}")
    print(f"tool_calls={len(session.tool_calls)}")
    mcp_tool_calls = sum(
        1 for call in session.tool_calls if call.classification.get("kind") == "mcp"
    )
    print(f"mcp_tool_calls={mcp_tool_calls}")
    if trace_id:
        print(f"trace_id={trace_id}")
    return 0


def _run_claude(args: argparse.Namespace) -> int:
    if args.command == "import-claude":
        session_path = Path(args.session_jsonl).expanduser()
    else:
        session_path = find_latest_claude_session(args.sessions_dir)

    try:
        session = load_claude_session(session_path)
        trace_id = import_claude_session_to_mlflow(
            session,
            tracking_uri=args.tracking_uri,
            experiment_name=args.experiment,
            max_value_chars=args.max_value_chars,
        )
    except (FileNotFoundError, MLflowUnavailableError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"imported_session={session.path}")
    print(f"session_id={session.session_id or ''}")
    print(f"ai_title={session.ai_title or ''}")
    print(f"model={session.model or ''}")
    print(f"messages={len(session.messages)}")
    print(f"tool_calls={len(session.tool_calls)}")
    mcp_tool_calls = sum(
        1 for call in session.tool_calls if call.classification.get("kind") == "mcp"
    )
    print(f"mcp_tool_calls={mcp_tool_calls}")
    if trace_id:
        print(f"trace_id={trace_id}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mlflow-codex",
        description="Import Codex session JSONL files into MLflow traces.",
    )
    subparsers = parser.add_subparsers(dest="command")

    import_parser = subparsers.add_parser("import", help="Import a specific session JSONL file")
    import_parser.add_argument("session_jsonl", help="Path to a Codex session JSONL file")
    _add_common_options(import_parser)

    latest_parser = subparsers.add_parser(
        "import-latest", help="Import the most recently modified Codex session JSONL file"
    )
    latest_parser.add_argument(
        "--sessions-dir",
        default="~/.codex/sessions",
        help="Codex sessions root directory (default: ~/.codex/sessions)",
    )
    _add_common_options(latest_parser, default_experiment="codex-traces")

    claude_parser = subparsers.add_parser(
        "import-claude", help="Import a specific Claude Code session JSONL file"
    )
    claude_parser.add_argument("session_jsonl", help="Path to a Claude Code session JSONL file")
    _add_common_options(claude_parser, default_experiment="claude-traces")

    claude_latest_parser = subparsers.add_parser(
        "import-claude-latest",
        help="Import the most recently modified Claude Code session JSONL file",
    )
    claude_latest_parser.add_argument(
        "--sessions-dir",
        default="~/.claude/projects",
        help="Claude Code projects directory (default: ~/.claude/projects)",
    )
    _add_common_options(claude_latest_parser, default_experiment="claude-traces")

    return parser


def _add_common_options(
    parser: argparse.ArgumentParser, *, default_experiment: str = "codex-traces"
) -> None:
    parser.add_argument(
        "--tracking-uri",
        default=None,
        help="MLflow tracking URI, for example file:./mlruns or http://127.0.0.1:5000",
    )
    parser.add_argument(
        "--experiment",
        default=default_experiment,
        help=f"MLflow experiment name (default: {default_experiment})",
    )
    parser.add_argument(
        "--max-value-chars",
        type=int,
        default=20000,
        help="Maximum string length stored in span inputs/outputs (default: 20000)",
    )
    parser.add_argument(
        "--include-base-instructions",
        dest="include_base_instructions",
        action="store_true",
        default=True,
        help="Store Codex base instructions in the root span inputs (default)",
    )
    parser.add_argument(
        "--no-base-instructions",
        dest="include_base_instructions",
        action="store_false",
        help="Do not store Codex base instructions in MLflow",
    )


if __name__ == "__main__":
    raise SystemExit(main())
