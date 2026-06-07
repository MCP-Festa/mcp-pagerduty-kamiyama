from __future__ import annotations

from pathlib import Path
from typing import Any

from .claude_session import ClaudeSession
from .codex_session import CodexSession, Message, ToolCall
from .redaction import redact


class MLflowUnavailableError(RuntimeError):
    pass


def import_session_to_mlflow(
    session: CodexSession,
    *,
    tracking_uri: str | None = None,
    experiment_name: str = "codex-traces",
    include_base_instructions: bool = True,
    max_value_chars: int | None = 20000,
) -> str | None:
    """Create one MLflow trace for a Codex session and return the trace id if exposed."""
    try:
        import mlflow
    except ModuleNotFoundError as exc:
        raise MLflowUnavailableError(
            "mlflow is not installed. Run `uv sync` or install this project first."
        ) from exc

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    if experiment_name:
        mlflow.set_experiment(experiment_name)

    root_inputs = _root_inputs(
        session,
        include_base_instructions=include_base_instructions,
        max_value_chars=max_value_chars,
    )
    root_outputs = _root_outputs(session, max_value_chars=max_value_chars)

    attributes = _root_attributes(session)
    with mlflow.start_span(name="codex.session", span_type="CHAIN") as root_span:
        root_span.set_attributes(attributes)
        root_span.set_inputs(root_inputs)

        _update_trace_preview(mlflow, session)

        for message in session.messages:
            _trace_message(mlflow, message, max_value_chars=max_value_chars)

        for tool_call in session.tool_calls:
            _trace_tool_call(mlflow, tool_call, max_value_chars=max_value_chars)

        if session.token_counts:
            _trace_token_counts(mlflow, session.token_counts, max_value_chars=max_value_chars)

        root_span.set_outputs(root_outputs)
        return _extract_trace_id(root_span)


def _root_inputs(
    session: CodexSession,
    *,
    include_base_instructions: bool,
    max_value_chars: int | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "user_messages": [_message_payload(message) for message in session.user_messages],
        "session_file": str(session.path),
    }
    if include_base_instructions:
        base = session.session_meta.get("base_instructions")
        if base is not None:
            data["base_instructions"] = base
    return redact(data, max_string_length=max_value_chars)


def _root_outputs(session: CodexSession, *, max_value_chars: int | None) -> dict[str, Any]:
    return redact(
        {
            "assistant_messages": [
                _message_payload(message) for message in session.assistant_messages
            ],
            "tool_call_count": len(session.tool_calls),
            "mcp_tool_call_count": sum(
                1 for call in session.tool_calls if call.classification.get("kind") == "mcp"
            ),
        },
        max_string_length=max_value_chars,
    )


def _root_attributes(session: CodexSession) -> dict[str, Any]:
    meta = session.session_meta
    attrs: dict[str, Any] = {
        "codex.session_id": session.session_id or "",
        "codex.session_path": str(Path(session.path).expanduser()),
        "codex.cli_version": str(meta.get("cli_version") or ""),
        "codex.originator": str(meta.get("originator") or ""),
        "codex.source": str(meta.get("source") or ""),
        "codex.thread_source": str(meta.get("thread_source") or ""),
        "codex.model_provider": str(meta.get("model_provider") or ""),
        "codex.model": session.model or "",
        "codex.cwd": session.cwd or "",
        "codex.started_at": session.started_at or "",
        "codex.ended_at": session.ended_at or "",
        "codex.event_count": len(session.events),
        "codex.message_count": len(session.messages),
        "codex.tool_call_count": len(session.tool_calls),
        "codex.mcp_tool_call_count": sum(
            1 for call in session.tool_calls if call.classification.get("kind") == "mcp"
        ),
    }
    return attrs


def _trace_message(mlflow: Any, message: Message, *, max_value_chars: int | None) -> None:
    name = (
        f"prompt.{message.role}"
        if message.role in {"user", "system", "developer"}
        else "message.assistant"
    )
    with mlflow.start_span(name=name, span_type="CHAT_MODEL") as span:
        span.set_attributes(
            {
                "codex.sequence_no": message.sequence_no,
                "codex.timestamp": message.timestamp or "",
                "codex.message_role": message.role,
                "codex.message_source": message.source,
            }
        )
        payload = redact(_message_payload(message), max_string_length=max_value_chars)
        span.set_inputs(payload if message.role != "assistant" else {})
        span.set_outputs(payload if message.role == "assistant" else {"recorded": True})


def _trace_tool_call(mlflow: Any, tool_call: ToolCall, *, max_value_chars: int | None) -> None:
    classification = tool_call.classification
    span_name = _tool_span_name(tool_call)
    with mlflow.start_span(name=span_name, span_type="TOOL") as span:
        attrs: dict[str, Any] = {
            "codex.sequence_no": tool_call.sequence_no,
            "codex.call_id": tool_call.call_id,
            "codex.tool_name": tool_call.name,
            "codex.tool_kind": classification.get("kind", ""),
            "codex.started_at": tool_call.started_at or "",
            "codex.ended_at": tool_call.ended_at or "",
        }
        if classification.get("kind") == "mcp":
            attrs["mcp.server"] = classification.get("mcp_server", "")
            attrs["mcp.tool"] = classification.get("mcp_tool", "")
        span.set_attributes(attrs)
        span.set_inputs(redact(tool_call.arguments, max_string_length=max_value_chars))
        span.set_outputs(redact(tool_call.output, max_string_length=max_value_chars))


def _trace_token_counts(
    mlflow: Any, token_counts: list[dict[str, Any]], *, max_value_chars: int | None
) -> None:
    with mlflow.start_span(name="codex.token_counts", span_type="UNKNOWN") as span:
        span.set_inputs({"count": len(token_counts)})
        span.set_outputs(redact(token_counts, max_string_length=max_value_chars))


def _tool_span_name(tool_call: ToolCall) -> str:
    classification = tool_call.classification
    if classification.get("kind") == "mcp":
        server = classification.get("mcp_server") or "unknown"
        tool = classification.get("mcp_tool") or tool_call.name
        return f"mcp.{server}.{tool}"
    return f"tool.{tool_call.name}"


def _message_payload(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sequence_no": message.sequence_no,
        "role": message.role,
        "content": message.text,
        "text": message.text,
        "timestamp": message.timestamp,
        "source": message.source,
    }
    if message.content != message.text:
        payload["content_blocks"] = message.content
    return payload


def _update_trace_preview(mlflow: Any, session: CodexSession) -> None:
    request_preview = _preview([message.text for message in session.user_messages])
    response_preview = _preview([message.text for message in session.assistant_messages])
    kwargs = {}
    if request_preview:
        kwargs["request_preview"] = request_preview
    if response_preview:
        kwargs["response_preview"] = response_preview
    if session.session_id:
        kwargs["tags"] = {"codex.session_id": session.session_id}
    if kwargs:
        mlflow.update_current_trace(**kwargs)


def _preview(values: list[str], *, max_chars: int = 240) -> str:
    text = "\n\n".join(value for value in values if value)
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def _extract_trace_id(root_span: Any) -> str | None:
    for attr in ("trace_id", "request_id"):
        value = getattr(root_span, attr, None)
        if isinstance(value, str):
            return value
    context = getattr(root_span, "context", None)
    if context is not None:
        value = getattr(context, "trace_id", None)
        if value is not None:
            return str(value)
    return None


# ---------------------------------------------------------------------------
# Claude Code session importer
# ---------------------------------------------------------------------------


def import_claude_session_to_mlflow(
    session: ClaudeSession,
    *,
    tracking_uri: str | None = None,
    experiment_name: str = "claude-traces",
    max_value_chars: int | None = 20000,
) -> str | None:
    """Create one MLflow trace for a Claude Code session and return the trace id."""
    try:
        import mlflow
    except ModuleNotFoundError as exc:
        raise MLflowUnavailableError(
            "mlflow is not installed. Run `uv sync` or install this project first."
        ) from exc

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    if experiment_name:
        mlflow.set_experiment(experiment_name)

    root_inputs = redact(
        {
            "user_messages": [_message_payload(m) for m in session.user_messages],
            "session_file": str(session.path),
        },
        max_string_length=max_value_chars,
    )
    root_outputs = redact(
        {
            "assistant_messages": [_message_payload(m) for m in session.assistant_messages],
            "tool_call_count": len(session.tool_calls),
            "mcp_tool_call_count": sum(
                1 for c in session.tool_calls if c.classification.get("kind") == "mcp"
            ),
        },
        max_string_length=max_value_chars,
    )

    attrs: dict[str, Any] = {
        "claude.session_id": session.session_id or "",
        "claude.session_path": str(session.path),
        "claude.ai_title": session.ai_title or "",
        "claude.model": session.model or "",
        "claude.cwd": session.cwd or "",
        "claude.version": session.version or "",
        "claude.started_at": session.started_at or "",
        "claude.ended_at": session.ended_at or "",
        "claude.message_count": len(session.messages),
        "claude.tool_call_count": len(session.tool_calls),
        "claude.mcp_tool_call_count": sum(
            1 for c in session.tool_calls if c.classification.get("kind") == "mcp"
        ),
    }

    # Aggregate token usage across all assistant turns
    total_input = total_output = total_cache_read = total_cache_creation = 0
    for usage in session.token_usages:
        total_input += usage.get("input_tokens", 0)
        total_output += usage.get("output_tokens", 0)
        total_cache_read += usage.get("cache_read_input_tokens", 0)
        total_cache_creation += usage.get("cache_creation_input_tokens", 0)
    if session.token_usages:
        attrs["claude.total_input_tokens"] = total_input
        attrs["claude.total_output_tokens"] = total_output
        attrs["claude.total_cache_read_tokens"] = total_cache_read
        attrs["claude.total_cache_creation_tokens"] = total_cache_creation

    with mlflow.start_span(name="claude.session", span_type="CHAIN") as root_span:
        root_span.set_attributes(attrs)
        root_span.set_inputs(root_inputs)

        _update_claude_trace_preview(mlflow, session)

        for message in session.messages:
            _trace_message(mlflow, message, max_value_chars=max_value_chars)

        for tool_call in session.tool_calls:
            _trace_tool_call(mlflow, tool_call, max_value_chars=max_value_chars)

        if session.token_usages:
            _trace_claude_token_usage(mlflow, session.token_usages, max_value_chars=max_value_chars)

        root_span.set_outputs(root_outputs)
        return _extract_trace_id(root_span)


def _update_claude_trace_preview(mlflow: Any, session: ClaudeSession) -> None:
    request_preview = _preview([m.text for m in session.user_messages])
    response_preview = _preview([m.text for m in session.assistant_messages])
    kwargs: dict[str, Any] = {}
    if request_preview:
        kwargs["request_preview"] = request_preview
    if response_preview:
        kwargs["response_preview"] = response_preview
    tags: dict[str, str] = {}
    if session.session_id:
        tags["claude.session_id"] = session.session_id
    if session.ai_title:
        tags["claude.ai_title"] = session.ai_title
    if tags:
        kwargs["tags"] = tags
    if kwargs:
        mlflow.update_current_trace(**kwargs)


def _trace_claude_token_usage(
    mlflow: Any, usages: list[dict[str, Any]], *, max_value_chars: int | None
) -> None:
    with mlflow.start_span(name="claude.token_usage", span_type="UNKNOWN") as span:
        span.set_inputs({"turn_count": len(usages)})
        span.set_outputs(redact(usages, max_string_length=max_value_chars))
