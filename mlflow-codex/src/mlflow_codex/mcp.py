"""MLflow tracing helpers for FastMCP servers.

Add MLflow tracing to any MCP server in three steps:

1. Import and call setup_mlflow() at server startup:
       from mlflow_codex.mcp import setup_mlflow, mcp_trace, mlflow_span
       setup_mlflow()  # reads MLFLOW_TRACKING_URI env var

2. Decorate each MCP tool (outermost, stacks with existing decorators):
       @mcp.tool()
       @mcp_trace          # one MLflow trace per tool call
       @_trace()           # existing logger unchanged
       async def my_tool(...): ...

3. Add child spans for HTTP/RPC calls:
       async with mlflow_span(f"service.{method}") as span:
           if span:
               span.set_attribute("service.method", method)
           result = await rpc(...)
"""
from __future__ import annotations

import functools
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])
log = logging.getLogger(__name__)

_configured = False


def _is_active() -> bool:
    return _configured or bool(os.getenv("MLFLOW_TRACKING_URI"))


def setup_mlflow(
    tracking_uri: str | None = None,
    experiment_name: str | None = None,
) -> bool:
    """Configure MLflow for MCP server tracing.

    Reads MLFLOW_TRACKING_URI env var if tracking_uri not provided.
    Returns True if successfully configured.
    """
    global _configured
    try:
        import mlflow
    except ImportError:
        return False

    uri = tracking_uri or os.getenv("MLFLOW_TRACKING_URI")
    if not uri:
        return False

    mlflow.set_tracking_uri(uri)
    if experiment_name:
        mlflow.set_experiment(experiment_name)
    _configured = True
    log.info("MLflow tracing configured: %s", uri)
    return True


def mcp_trace(func: F | None = None, *, name: str | None = None) -> F | Callable[[F], F]:
    """Decorator that wraps an async MCP tool with an MLflow trace span.

    Place as the outermost application-level decorator to trace the full call:

        @mcp.tool()
        @mcp_trace          # creates one MLflow trace per invocation
        @_trace()           # existing shownet_mcp_logger (untouched)
        async def my_tool(...): ...

    No-op if mlflow is not installed or MLFLOW_TRACKING_URI is not set.
    """
    def decorator(f: F) -> F:
        span_name = name or f.__name__

        @functools.wraps(f)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _is_active():
                return await f(*args, **kwargs)
            import mlflow
            with mlflow.start_span(name=span_name, span_type="TOOL") as span:
                try:
                    result = await f(*args, **kwargs)
                    span.set_attribute("mcp.status", "ok")
                    return result
                except Exception as exc:
                    span.set_attribute("mcp.status", "error")
                    span.set_attribute("mcp.error", str(exc))
                    raise

        return wrapper  # type: ignore[return-value]

    if func is not None:
        return decorator(func)
    return decorator


@asynccontextmanager
async def mlflow_span(name: str, attributes: dict[str, Any] | None = None):
    """Async context manager for a child span within an active MLflow trace.

    Use inside HTTP/RPC client code to record sub-operations as child spans:

        async with mlflow_span(f"zabbix.{method}") as span:
            if span:
                span.set_attribute("zabbix.result_count", len(result))
            result = await http_call(...)

    Yields the span object if MLflow is active, otherwise yields None (no-op).
    When called outside any active trace, MLflow creates a new root trace.
    """
    if not _is_active():
        yield None
        return
    import mlflow
    with mlflow.start_span(name=name) as span:
        if attributes:
            span.set_attributes(attributes)
        yield span
