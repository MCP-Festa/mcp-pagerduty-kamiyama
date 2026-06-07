from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodexEvent:
    sequence_no: int
    record_type: str
    payload_type: str | None
    timestamp: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class Message:
    sequence_no: int
    role: str
    content: Any
    timestamp: str | None
    source: str

    @property
    def text(self) -> str:
        return normalize_content(self.content)


@dataclass(frozen=True)
class ToolCall:
    sequence_no: int
    call_id: str
    name: str
    arguments: Any
    arguments_raw: str
    output: Any | None = None
    output_raw: str | None = None
    started_at: str | None = None
    ended_at: str | None = None

    @property
    def latency_ms(self) -> int | None:
        return None

    @property
    def classification(self) -> dict[str, str]:
        return classify_tool_name(self.name)


@dataclass(frozen=True)
class CodexSession:
    path: Path
    session_id: str | None
    session_meta: dict[str, Any]
    turn_contexts: list[dict[str, Any]]
    events: list[CodexEvent]
    messages: list[Message]
    tool_calls: list[ToolCall]
    token_counts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def user_messages(self) -> list[Message]:
        return [message for message in self.messages if message.role == "user"]

    @property
    def assistant_messages(self) -> list[Message]:
        return [message for message in self.messages if message.role == "assistant"]

    @property
    def started_at(self) -> str | None:
        for event in self.events:
            if event.timestamp:
                return event.timestamp
        return self.session_meta.get("timestamp")

    @property
    def ended_at(self) -> str | None:
        for event in reversed(self.events):
            if event.timestamp:
                return event.timestamp
        return None

    @property
    def model(self) -> str | None:
        for context in reversed(self.turn_contexts):
            model = context.get("model")
            if isinstance(model, str) and model:
                return model
        return None

    @property
    def cwd(self) -> str | None:
        for context in reversed(self.turn_contexts):
            cwd = context.get("cwd")
            if isinstance(cwd, str) and cwd:
                return cwd
        cwd = self.session_meta.get("cwd")
        return cwd if isinstance(cwd, str) else None


def load_session(path: str | Path) -> CodexSession:
    session_path = Path(path).expanduser()
    records: list[CodexEvent] = []
    session_meta: dict[str, Any] = {}
    turn_contexts: list[dict[str, Any]] = []
    messages: list[Message] = []
    token_counts: list[dict[str, Any]] = []
    calls_by_id: dict[str, ToolCall] = {}
    call_order: list[str] = []

    with session_path.open(encoding="utf-8") as handle:
        for sequence_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            payload = raw.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {"value": payload}

            event = CodexEvent(
                sequence_no=sequence_no,
                record_type=str(raw.get("type") or ""),
                payload_type=payload.get("type") if isinstance(payload.get("type"), str) else None,
                timestamp=raw.get("timestamp") if isinstance(raw.get("timestamp"), str) else None,
                payload=payload,
            )
            records.append(event)

            if event.record_type == "session_meta":
                session_meta = payload
            elif event.record_type == "turn_context":
                turn_contexts.append(payload)
            elif event.payload_type == "user_message":
                messages.append(
                    Message(
                        sequence_no=sequence_no,
                        role="user",
                        content=payload.get("message") or payload.get("text_elements") or "",
                        timestamp=event.timestamp,
                        source="event_msg",
                    )
                )
            elif event.payload_type == "agent_message":
                messages.append(
                    Message(
                        sequence_no=sequence_no,
                        role="assistant",
                        content=payload.get("message") or "",
                        timestamp=event.timestamp,
                        source="event_msg",
                    )
                )
            elif event.payload_type == "message":
                role = payload.get("role")
                if role in {"user", "assistant", "system", "developer"}:
                    messages.append(
                        Message(
                            sequence_no=sequence_no,
                            role=role,
                            content=payload.get("content") or "",
                            timestamp=event.timestamp,
                            source="response_item",
                        )
                    )
            elif event.payload_type == "function_call":
                call_id = str(payload.get("call_id") or f"call-{sequence_no}")
                arguments_raw = payload.get("arguments")
                if not isinstance(arguments_raw, str):
                    arguments_raw = json.dumps(arguments_raw, ensure_ascii=False)
                tool_call = ToolCall(
                    sequence_no=len(call_order) + 1,
                    call_id=call_id,
                    name=str(payload.get("name") or "unknown_tool"),
                    arguments=parse_jsonish(arguments_raw),
                    arguments_raw=arguments_raw,
                    started_at=event.timestamp,
                )
                calls_by_id[call_id] = tool_call
                call_order.append(call_id)
            elif event.payload_type == "function_call_output":
                call_id = str(payload.get("call_id") or "")
                existing = calls_by_id.get(call_id)
                if existing is not None:
                    output_raw = payload.get("output")
                    if not isinstance(output_raw, str):
                        output_raw = json.dumps(output_raw, ensure_ascii=False)
                    calls_by_id[call_id] = ToolCall(
                        sequence_no=existing.sequence_no,
                        call_id=existing.call_id,
                        name=existing.name,
                        arguments=existing.arguments,
                        arguments_raw=existing.arguments_raw,
                        output=parse_jsonish(output_raw),
                        output_raw=output_raw,
                        started_at=existing.started_at,
                        ended_at=event.timestamp,
                    )
            elif event.payload_type == "token_count":
                token_counts.append(payload)

    session_id = session_meta.get("id")
    if not isinstance(session_id, str):
        session_id = None

    return CodexSession(
        path=session_path,
        session_id=session_id,
        session_meta=session_meta,
        turn_contexts=turn_contexts,
        events=records,
        messages=messages,
        tool_calls=[calls_by_id[call_id] for call_id in call_order if call_id in calls_by_id],
        token_counts=token_counts,
    )


def parse_jsonish(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    if isinstance(content, dict):
        for key in ("text", "content", "message"):
            if isinstance(content.get(key), str):
                return content[key]
    return json.dumps(content, ensure_ascii=False)


def classify_tool_name(name: str) -> dict[str, str]:
    if name.startswith("mcp__"):
        parts = name.split("__")
        server = parts[1] if len(parts) > 1 else ""
        tool = "__".join(parts[2:]) if len(parts) > 2 else ""
        return {"kind": "mcp", "mcp_server": server, "mcp_tool": tool}

    known_mcp_tools = {
        "zabbix": {
            "acknowledge_event",
            "create_maintenance",
            "get_active_problems",
            "get_item_history",
            "get_recent_events",
            "get_zabbix_api_version",
            "list_host_groups",
            "list_hosts",
            "list_items",
            "list_maintenances",
            "list_triggers",
        }
    }
    for server, tool_names in known_mcp_tools.items():
        if name in tool_names:
            return {"kind": "mcp", "mcp_server": server, "mcp_tool": name}

    builtin_tool_names = {
        "exec_command",
        "write_stdin",
        "apply_patch",
        "update_plan",
        "view_image",
        "web.run",
        "imagegen",
    }
    if name in builtin_tool_names:
        return {"kind": "codex_builtin"}

    return {"kind": "tool"}


def find_latest_session(sessions_dir: str | Path) -> Path:
    root = Path(sessions_dir).expanduser()
    candidates = [path for path in root.rglob("*.jsonl") if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No Codex session JSONL files found under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)
