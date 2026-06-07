from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .codex_session import Message, ToolCall, classify_tool_name, normalize_content, parse_jsonish


@dataclass(frozen=True)
class ClaudeSession:
    path: Path
    session_id: str | None
    ai_title: str | None
    cwd: str | None
    version: str | None
    model: str | None
    messages: list[Message]
    tool_calls: list[ToolCall]
    token_usages: list[dict[str, Any]] = field(default_factory=list)
    turn_durations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def user_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role == "user"]

    @property
    def assistant_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role == "assistant"]

    @property
    def started_at(self) -> str | None:
        for m in self.messages:
            if m.timestamp:
                return m.timestamp
        return None

    @property
    def ended_at(self) -> str | None:
        for m in reversed(self.messages):
            if m.timestamp:
                return m.timestamp
        return None


def load_claude_session(path: str | Path) -> ClaudeSession:
    session_path = Path(path).expanduser()

    session_id: str | None = None
    ai_title: str | None = None
    cwd: str | None = None
    version: str | None = None
    model: str | None = None
    messages: list[Message] = []
    token_usages: list[dict[str, Any]] = []
    turn_durations: list[dict[str, Any]] = []

    # tool_use_id → ToolCall (filled from assistant, updated with result from user)
    calls_by_id: dict[str, ToolCall] = {}
    call_order: list[str] = []
    seq = 0

    with session_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw: dict[str, Any] = json.loads(line)
            record_type = raw.get("type", "")

            if not session_id and raw.get("sessionId"):
                session_id = str(raw["sessionId"])

            if record_type == "ai-title":
                ai_title = raw.get("aiTitle") or ai_title
                continue

            if record_type == "assistant":
                msg_obj = raw.get("message") or {}
                if not model:
                    model = msg_obj.get("model") or None
                if not cwd:
                    cwd = raw.get("cwd") or None
                if not version:
                    version = raw.get("version") or None

                usage = msg_obj.get("usage")
                if isinstance(usage, dict):
                    token_usages.append(usage)

                content = msg_obj.get("content") or []
                timestamp = raw.get("timestamp") or None
                text_parts: list[str] = []

                for block in content if isinstance(content, list) else []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block.get("text") or "")
                    elif block.get("type") == "tool_use":
                        tool_id = str(block.get("id") or f"call-{seq}")
                        seq += 1
                        name = str(block.get("name") or "unknown_tool")
                        args = block.get("input") or {}
                        args_raw = json.dumps(args, ensure_ascii=False)
                        tc = ToolCall(
                            sequence_no=len(call_order) + 1,
                            call_id=tool_id,
                            name=name,
                            arguments=args,
                            arguments_raw=args_raw,
                            started_at=timestamp,
                        )
                        calls_by_id[tool_id] = tc
                        call_order.append(tool_id)

                if text_parts:
                    seq += 1
                    messages.append(
                        Message(
                            sequence_no=seq,
                            role="assistant",
                            content="\n".join(text_parts),
                            timestamp=timestamp,
                            source="claude_assistant",
                        )
                    )
                continue

            if record_type == "user":
                if not cwd:
                    cwd = raw.get("cwd") or None
                if not version:
                    version = raw.get("version") or None

                timestamp = raw.get("timestamp") or None
                content = raw.get("message", {}).get("content") or ""

                if isinstance(content, str) and content.strip():
                    seq += 1
                    messages.append(
                        Message(
                            sequence_no=seq,
                            role="user",
                            content=content,
                            timestamp=timestamp,
                            source="claude_user",
                        )
                    )
                elif isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_result":
                            tool_id = str(block.get("tool_use_id") or "")
                            result_content = block.get("content") or ""
                            output_raw = (
                                result_content
                                if isinstance(result_content, str)
                                else json.dumps(result_content, ensure_ascii=False)
                            )
                            existing = calls_by_id.get(tool_id)
                            if existing is not None:
                                calls_by_id[tool_id] = ToolCall(
                                    sequence_no=existing.sequence_no,
                                    call_id=existing.call_id,
                                    name=existing.name,
                                    arguments=existing.arguments,
                                    arguments_raw=existing.arguments_raw,
                                    output=parse_jsonish(output_raw),
                                    output_raw=output_raw,
                                    started_at=existing.started_at,
                                    ended_at=timestamp,
                                )
                        elif block.get("type") == "text":
                            text_parts.append(block.get("text") or "")

                    if text_parts:
                        seq += 1
                        messages.append(
                            Message(
                                sequence_no=seq,
                                role="user",
                                content="\n".join(text_parts),
                                timestamp=timestamp,
                                source="claude_user",
                            )
                        )
                continue

            if record_type == "system" and raw.get("subtype") == "turn_duration":
                turn_durations.append(
                    {
                        "durationMs": raw.get("durationMs"),
                        "messageCount": raw.get("messageCount"),
                        "timestamp": raw.get("timestamp"),
                    }
                )

    return ClaudeSession(
        path=session_path,
        session_id=session_id,
        ai_title=ai_title,
        cwd=cwd,
        version=version,
        model=model,
        messages=messages,
        tool_calls=[calls_by_id[cid] for cid in call_order if cid in calls_by_id],
        token_usages=token_usages,
        turn_durations=turn_durations,
    )


def find_latest_claude_session(sessions_dir: str | Path = "~/.claude/projects") -> Path:
    root = Path(sessions_dir).expanduser()
    candidates = [p for p in root.rglob("*.jsonl") if p.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No Claude Code session JSONL files found under {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)
