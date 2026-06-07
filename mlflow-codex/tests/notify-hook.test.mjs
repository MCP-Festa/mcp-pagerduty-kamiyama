import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";

function getGlobalCodexRoot() {
  const root = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
  return join(root, "@mlflow", "codex");
}

function buildStubCoreModule(stubRoot) {
  const coreRoot = join(stubRoot, "node_modules", "@mlflow", "core");
  mkdirSync(coreRoot, { recursive: true });

  writeFileSync(
    join(coreRoot, "package.json"),
    JSON.stringify({ name: "@mlflow/core", type: "module", exports: "./index.js" }, null, 2),
    "utf8",
  );

  writeFileSync(
    join(coreRoot, "index.js"),
    `const state = globalThis.__mlflowCoreStubState ??= {
  spans: [],
  startSpanCalls: [],
  traces: new Map(),
  flushed: false,
};

class StubSpan {
  constructor(options) {
    this.options = options;
    this.traceId = "trace-1";
    this.spanId = "span-" + (state.spans.length + 1);
    this.endArgs = null;
  }

  setAttribute() {}

  setStatus() {}

  end(args = {}) {
    this.endArgs = args;
  }
}

export const SpanStatusCode = {
  ERROR: "ERROR",
  OK: "OK",
  UNSET: "UNSET",
};

export const SpanType = {
  AGENT: "AGENT",
  LLM: "LLM",
  TOOL: "TOOL",
};

export const SpanAttributeKey = {
  TOKEN_USAGE: "token_usage",
};

export const TraceMetadataKey = {
  TRACE_SESSION: "trace_session",
  TRACE_USER: "trace_user",
};

export const TokenUsageKey = {
  INPUT_TOKENS: "input_tokens",
  OUTPUT_TOKENS: "output_tokens",
  TOTAL_TOKENS: "total_tokens",
};

export function startSpan(options) {
  state.startSpanCalls.push(options);
  const span = new StubSpan(options);
  state.spans.push(span);
  state.traces.set(span.traceId, { info: { traceMetadata: {} } });
  return span;
}

export async function flushTraces() {
  state.flushed = true;
}

export const InMemoryTraceManager = {
  getInstance() {
    return {
      getTrace(traceId) {
        return state.traces.get(traceId) ?? null;
      },
    };
  },
};
`,
    "utf8",
  );
}

async function loadTracingModule() {
  const root = mkdtempSync(join(tmpdir(), "mlflow-codex-tracing-"));
  const codexRoot = getGlobalCodexRoot();

  writeFileSync(join(root, "package.json"), JSON.stringify({ type: "module" }, null, 2), "utf8");
  buildStubCoreModule(root);
  copyFileSync(join(codexRoot, "dist", "tracing.js"), join(root, "tracing.js"));
  copyFileSync(join(codexRoot, "dist", "transcript.js"), join(root, "transcript.js"));

  return {
    root,
    module: await import(pathToFileURL(join(root, "tracing.js")).href),
  };
}

function resetStubState() {
  globalThis.__mlflowCoreStubState = {
    spans: [],
    startSpanCalls: [],
    traces: new Map(),
    flushed: false,
  };
}

test("normalizes the notify payload and stores full strings in trace inputs/outputs", async () => {
  resetStubState();
  const { module, root } = await loadTracingModule();

  try {
    await module.processNotify({
      type: "agent-turn-complete",
      "thread-id": "unit-test-no-transcript-019e7cf8-61fa-7ab2-b1ea-757fdeabd3f0",
      "turn-id": "unit-test-no-transcript-019e7cf8-62c8-7860-94a9-633e396041b8",
      cwd: "/Users/yuma",
      client: "codex-tui",
      "input-messages": ["MLflow tracing debug test. Please reply with hello world."],
      "last-assistant-message": "hello world",
    });

    const state = globalThis.__mlflowCoreStubState;
    assert.equal(state.startSpanCalls.length, 2);
    assert.deepEqual(state.startSpanCalls[0].inputs, {
      messages: ["MLflow tracing debug test. Please reply with hello world."],
    });
    assert.deepEqual(state.startSpanCalls[1].inputs, {
      model: "unknown",
      messages: [{ role: "user", content: "MLflow tracing debug test. Please reply with hello world." }],
    });
    assert.deepEqual(state.spans[0].endArgs.outputs, { response: "hello world" });
    assert.deepEqual(state.spans[1].endArgs.outputs, {
      choices: [{ message: { role: "assistant", content: "hello world" } }],
    });
    assert.equal(state.flushed, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("wraps a string input-messages payload as one message", async () => {
  resetStubState();
  const { module, root } = await loadTracingModule();

  try {
    await module.processNotify({
      type: "agent-turn-complete",
      "thread-id": "unit-test-no-transcript-debug-thread",
      "turn-id": "unit-test-no-transcript-debug-turn",
      cwd: "/Users/yuma",
      client: "codex-tui",
      "input-messages": "MLflow tracing debug test. Please reply with hello world.",
      "last-assistant-message": "hello world",
    });

    const state = globalThis.__mlflowCoreStubState;
    assert.equal(state.startSpanCalls.length, 2);
    assert.deepEqual(state.startSpanCalls[0].inputs.messages, [
      "MLflow tracing debug test. Please reply with hello world.",
    ]);
    assert.equal(state.startSpanCalls[0].inputs.messages[0], "MLflow tracing debug test. Please reply with hello world.");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
