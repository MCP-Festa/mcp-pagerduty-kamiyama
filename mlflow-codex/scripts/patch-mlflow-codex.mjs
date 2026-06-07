import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const PACKAGE_NAME = "@mlflow/codex";
const SUPPORTED_VERSION = "0.2.0-rc.0";

const textExtractionPatch = {
  file: "dist/transcript.js",
  from: `    return content
        .filter((block) => block.type === 'input_text' || block.type === 'output_text')
        .map((block) => block.text)
        .join('\\n');
}`,
  to: `    return content
        .filter((block) => block.type === 'input_text' || block.type === 'output_text')
        .map((block) => block.text)
        .join('');
}`,
};

const transcriptPatch = {
  file: "dist/transcript.js",
  from: `export function findLastUserPrompt(records) {
    for (let i = records.length - 1; i >= 0; i--) {
        const record = records[i];
        if (record.type !== 'response_item') {
            continue;
        }
        const payload = record.payload;
        if (payload.type !== 'message' || payload.role !== 'user') {
            continue;
        }
        const text = extractTextFromContent(payload.content);
        // Skip system/developer context injections (start with XML-like tags)
        if (text && !text.startsWith('<')) {
            return { text, index: i };
        }
    }
    return null;
}
/**
 * Extract records belonging to the last turn.
 * Turns are delimited by event_msg records with type=task_started / task_complete.
 */`,
  to: `export function findLastUserPrompt(records) {
    for (let i = records.length - 1; i >= 0; i--) {
        const record = records[i];
        if (record.type !== 'response_item') {
            continue;
        }
        const payload = record.payload;
        if (payload.type !== 'message' || payload.role !== 'user') {
            continue;
        }
        const text = extractTextFromContent(payload.content);
        // Skip system/developer context injections (start with XML-like tags)
        if (text && !text.startsWith('<')) {
            return { text, index: i };
        }
    }
    return null;
}
/**
 * Find the last assistant message in the transcript.
 *
 * Codex emits assistant content in completed response items, which is more
 * reliable than the notify payload's last-assistant-message field when the
 * payload is assembled from streamed chunks.
 */
export function findLastAssistantResponse(records) {
    for (let i = records.length - 1; i >= 0; i--) {
        const record = records[i];
        if (record.type !== 'response_item') {
            continue;
        }
        const payload = record.payload;
        if (payload.type !== 'message' || payload.role !== 'assistant') {
            continue;
        }
        const text = extractTextFromContent(payload.content);
        if (text) {
            return text;
        }
    }
    return null;
}
/**
 * Extract records belonging to the last turn.
 * Turns are delimited by event_msg records with type=task_started / task_complete.
 */`,
};

const tracingPatch = {
  file: "dist/tracing.js",
  from: [
    `import { parseTimestampToNs, extractTextFromContent, getTokenUsage, getModel, buildToolResultMap, findTranscriptForThread, getLastTurnRecords, readTranscript, } from './transcript.js';
/**
 * Process a Codex notify hook payload and create an MLflow trace.
 *
 * The notify payload has the user prompt and assistant response directly,
 * so we create a simple AGENT → LLM trace. If a transcript file is found,
 * we also parse it for tool calls and token usage.
 */
export async function processNotify(payload) {
    // input-messages accumulates all prompts in the session; take only the last one
    const inputMessages = payload['input-messages'] ?? [];
    const userPrompt = inputMessages[inputMessages.length - 1] ?? '';
    const sessionId = payload['thread-id'];
    if (!userPrompt) {
        return;
    }
    // Try to find and parse the transcript for richer data (tool calls, tokens)
    const transcriptPath = findTranscriptForThread(sessionId);
    let turnRecords = null;
    let model = 'unknown';
    if (transcriptPath) {
        const records = readTranscript(transcriptPath);
        if (records.length > 0) {
            turnRecords = getLastTurnRecords(records);
            model = getModel(records);
        }
    }`,
    `import { parseTimestampToNs, extractTextFromContent, getTokenUsage, getModel, buildToolResultMap, findTranscriptForThread, findLastAssistantResponse, getLastTurnRecords, readTranscript, } from './transcript.js';
/**
 * Process a Codex notify hook payload and create an MLflow trace.
 *
 * The notify payload has the user prompt and assistant response directly,
 * so we create a simple AGENT → LLM trace. If a transcript file is found,
 * we also parse it for tool calls and token usage.
 */
export async function processNotify(payload) {
    // input-messages accumulates all prompts in the session; take only the last one
    const inputMessages = payload['input-messages'] ?? [];
    const userPrompt = inputMessages[inputMessages.length - 1] ?? '';
    let assistantResponse = payload['last-assistant-message'] ?? '';
    const sessionId = payload['thread-id'];
    if (!userPrompt) {
        return;
    }
    // Try to find and parse the transcript for richer data (tool calls, tokens)
    const transcriptPath = findTranscriptForThread(sessionId);
    let turnRecords = null;
    let model = 'unknown';
    if (transcriptPath) {
        const records = readTranscript(transcriptPath);
        if (records.length > 0) {
            turnRecords = getLastTurnRecords(records);
            model = getModel(records);
            assistantResponse = findLastAssistantResponse(turnRecords) ?? payload['last-assistant-message'] ?? '';
        }
    }`,
  ],
  to: `import { parseTimestampToNs, extractTextFromContent, getTokenUsage, getModel, buildToolResultMap, findTranscriptForThread, findLastAssistantResponse, getLastTurnRecords, readTranscript, } from './transcript.js';
function normalizeStringArray(value) {
    if (value == null) {
        return [];
    }
    if (typeof value === 'string') {
        return [value];
    }
    if (Array.isArray(value)) {
        return value
            .map((item) => {
            if (typeof item === 'string') {
                return item;
            }
            if (item == null) {
                return '';
            }
            return JSON.stringify(item) ?? '';
        })
            .filter((item) => item.length > 0);
    }
    return [JSON.stringify(value) ?? ''];
}
function normalizeString(value) {
    if (value == null) {
        return '';
    }
    if (typeof value === 'string') {
        return value;
    }
    return JSON.stringify(value) ?? '';
}
function normalizeNotifyPayload(payload) {
    const inputMessages = normalizeStringArray(payload['input-messages']);
    return {
        inputMessages,
        userPrompt: inputMessages[inputMessages.length - 1] ?? '',
        assistantResponse: normalizeString(payload['last-assistant-message']),
        sessionId: normalizeString(payload['thread-id']),
    };
}
/**
 * Process a Codex notify hook payload and create an MLflow trace.
 *
 * The notify payload has the user prompt and assistant response directly,
 * so we create a simple AGENT → LLM trace. If a transcript file is found,
 * we also parse it for tool calls and token usage.
 */
export async function processNotify(payload) {
    const { inputMessages, userPrompt, assistantResponse: initialAssistantResponse, sessionId } = normalizeNotifyPayload(payload);
    let assistantResponse = initialAssistantResponse;
    if (!userPrompt) {
        return;
    }
    // Try to find and parse the transcript for richer data (tool calls, tokens)
    const transcriptPath = findTranscriptForThread(sessionId);
    let turnRecords = null;
    let model = 'unknown';
    if (transcriptPath) {
        const records = readTranscript(transcriptPath);
        if (records.length > 0) {
            turnRecords = getLastTurnRecords(records);
            model = getModel(records);
            assistantResponse = findLastAssistantResponse(turnRecords) ?? initialAssistantResponse;
        }
    }`,
};

const tracingInputsPatch = {
  file: "dist/tracing.js",
  from: `        inputs: userPrompt,`,
  to: `        inputs: {
            messages: inputMessages,
        },`,
};

const tracingOutputsPatch = {
  file: "dist/tracing.js",
  from: `        outputs: assistantResponse,`,
  to: `        outputs: {
            response: assistantResponse,
        },`,
};

const tracingCommentPatch = {
  file: "dist/tracing.js",
  from: `    // Create root AGENT span. Pass the user prompt as a raw string so MLflow
    // can auto-generate the request preview and the session view renders the
    // message cleanly.`,
  to: `    // Create root AGENT span with structured messages so MLflow can render
    // the full prompt and response cleanly.`,
};

const bundleTextExtractionPatch = {
  file: "bundle/cli.js",
  from: `  return content.filter((block) => block.type === "input_text" || block.type === "output_text").map((block) => block.text).join("\\n");`,
  to: `  return content.filter((block) => block.type === "input_text" || block.type === "output_text").map((block) => block.text).join("");`,
};

const bundleTracingPatch = {
  file: "bundle/cli.js",
  from: `// dist/tracing.js
async function processNotify(payload) {
  const inputMessages = payload["input-messages"] ?? [];
  const userPrompt = inputMessages[inputMessages.length - 1] ?? "";
  const assistantResponse = payload["last-assistant-message"] ?? "";
  const sessionId = payload["thread-id"];
  if (!userPrompt) {
    return;
  }
  const transcriptPath = findTranscriptForThread(sessionId);
  let turnRecords = null;
  let model = "unknown";
  if (transcriptPath) {
    const records = readTranscript(transcriptPath);
    if (records.length > 0) {
      turnRecords = getLastTurnRecords(records);
      model = getModel(records);
    }
  }`,
  to: `// dist/tracing.js
function normalizeStringArrayB(value) {
  if (value == null) return [];
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (typeof item === "string") return item;
      if (item == null) return "";
      return JSON.stringify(item) ?? "";
    }).filter((item) => item.length > 0);
  }
  return [JSON.stringify(value) ?? ""];
}
function normalizeStringB(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value) ?? "";
}
function findLastAssistantResponseB(records) {
  for (let i2 = records.length - 1; i2 >= 0; i2--) {
    const record = records[i2];
    if (record.type !== "response_item") continue;
    const payload2 = record.payload;
    if (payload2.type !== "message" || payload2.role !== "assistant") continue;
    const text = extractTextFromContent(payload2.content);
    if (text) return text;
  }
  return null;
}
async function processNotify(payload) {
  const inputMessages = normalizeStringArrayB(payload["input-messages"]);
  const userPrompt = inputMessages[inputMessages.length - 1] ?? "";
  let assistantResponse = normalizeStringB(payload["last-assistant-message"]);
  const sessionId = normalizeStringB(payload["thread-id"]);
  if (!userPrompt) {
    return;
  }
  const transcriptPath = findTranscriptForThread(sessionId);
  let turnRecords = null;
  let model = "unknown";
  if (transcriptPath) {
    const records = readTranscript(transcriptPath);
    if (records.length > 0) {
      turnRecords = getLastTurnRecords(records);
      model = getModel(records);
      assistantResponse = findLastAssistantResponseB(turnRecords) ?? assistantResponse;
    }
  }`,
};

const bundleInputsPatch = {
  file: "bundle/cli.js",
  from: `    inputs: userPrompt,`,
  to: `    inputs: {
      messages: inputMessages,
    },`,
};

const bundleOutputsPatch = {
  file: "bundle/cli.js",
  from: `    outputs: assistantResponse,`,
  to: `    outputs: {
      response: assistantResponse,
    },`,
};

const traceDataFormatPatch = {
  file: "bundle/cli.js",
  from: `      async uploadTraceData(traceInfo, traceData) {
        const traceDataJson = traceData.toJson();
        const artifactUrl = this.getArtifactUrlForTrace(traceInfo);
        await (0, utils_1.makeRequest)("PUT", artifactUrl, this.headersProvider, traceDataJson);
      }`,
  to: `      async uploadTraceData(traceInfo, traceData) {
        const traceDataJson = { info: traceInfo.toJson(), data: traceData.toJson() };
        const artifactUrl = this.getArtifactUrlForTrace(traceInfo);
        await (0, utils_1.makeRequest)("PUT", artifactUrl, this.headersProvider, traceDataJson);
      }`,
};

const artifactUriPatch = {
  file: "bundle/cli.js",
  from: `      resolveArtifactUri(artifactUri, fileName) {
        const baseApiPath = "/api/2.0/mlflow-artifacts/artifacts";
        const url = new URL(artifactUri);
        if (url.protocol !== "mlflow-artifacts:") {
          throw new Error(\`Expected mlflow-artifacts:// URI, got \${url.protocol}\`);
        }
        const cleanHost = this.host.replace(/\\/$/, "");
        return \`\${cleanHost}\${baseApiPath}\${url.pathname}/\${fileName}\`;
      }`,
  to: `      resolveArtifactUri(artifactUri, fileName) {
        const baseApiPath = "/api/2.0/mlflow-artifacts/artifacts";
        const cleanHost = this.host.replace(/\\/$/, "");
        if (artifactUri.startsWith("/")) {
          return \`\${cleanHost}\${baseApiPath}\${artifactUri}/\${fileName}\`;
        }
        const url = new URL(artifactUri);
        if (url.protocol !== "mlflow-artifacts:") {
          throw new Error(\`Expected mlflow-artifacts:// URI, got \${url.protocol}\`);
        }
        return \`\${cleanHost}\${baseApiPath}\${url.pathname}/\${fileName}\`;
      }`,
};

// Log spans via OTLP /v1/traces so MLflow stores them in DB (sets SPANS_LOCATION=TRACKING_STORE tag)
// and the "See detailed trace view" can retrieve them from DB instead of the artifact file.
const bundleOtlpExportPatch = {
  file: "bundle/cli.js",
  from: `      /**
       * Export a complete trace to the MLflow backend
       * Step 1: Create trace metadata via StartTraceV3 endpoint
       * Step 2: Upload trace data (spans) via artifact repository pattern
       */
      async exportTraceToBackend(trace2) {
        try {
          const traceInfo = await this._client.createTrace(trace2.info);
          await this._client.uploadTraceData(traceInfo, trace2.data);
        } catch (error) {
          console.error(\`Failed to export trace \${trace2.info.traceId}:\`, error);
          throw error;
        } finally {
          delete this._pendingExports[trace2.info.traceId];
        }
      }`,
  to: `      /**
       * Export a complete trace to the MLflow backend
       * Step 1: Create trace metadata via StartTraceV3 endpoint
       * Step 2: Upload trace data (spans) via artifact repository pattern
       * Step 3: Log spans via OTLP to set SPANS_LOCATION tag so MLflow UI can retrieve them from DB
       */
      async exportTraceToBackend(trace2) {
        try {
          const traceInfo = await this._client.createTrace(trace2.info);
          await this._client.uploadTraceData(traceInfo, trace2.data);
          await this._logSpansViaOtlp(traceInfo, trace2.data).catch((e) => {
            console.debug("OTLP span logging skipped:", e.message);
          });
        } catch (error) {
          console.error(\`Failed to export trace \${trace2.info.traceId}:\`, error);
          throw error;
        } finally {
          delete this._pendingExports[trace2.info.traceId];
        }
      }
      async _logSpansViaOtlp(traceInfo, traceData) {
        function toOtlpVal(v) {
          if (v === null || v === void 0) return {};
          if (typeof v === "boolean") return { boolValue: v };
          if (typeof v === "number") return Number.isInteger(v) ? { intValue: v } : { doubleValue: v };
          if (typeof v === "string") return { stringValue: v };
          if (Array.isArray(v)) return { arrayValue: { values: v.map(toOtlpVal) } };
          if (typeof v === "object") return { kvlistValue: { values: Object.entries(v).map(([k, w]) => ({ key: k, value: toOtlpVal(w) })) } };
          return { stringValue: String(v) };
        }
        const experimentId = traceInfo.traceLocation?.mlflowExperiment?.experimentId ?? "0";
        const otelTraceId = traceInfo.traceId.startsWith("tr-") ? traceInfo.traceId.slice(3) : traceInfo.traceId;
        const otlpSpans = traceData.spans.map((span) => {
          const st = span.startTime;
          const et = span.endTime;
          const startNs = (BigInt(st[0]) * 1000000000n + BigInt(st[1])).toString();
          const endNs = et ? (BigInt(et[0]) * 1000000000n + BigInt(et[1])).toString() : startNs;
          const s = {
            traceId: otelTraceId,
            spanId: span.spanId,
            name: span.name,
            kind: 1,
            startTimeUnixNano: startNs,
            endTimeUnixNano: endNs,
            status: {},
            attributes: Object.entries(span.attributes || {}).map(([k, v]) => ({ key: k, value: toOtlpVal(v) }))
          };
          if (span.parentId) s.parentSpanId = span.parentId;
          return s;
        });
        const payload = JSON.stringify({
          resourceSpans: [{
            resource: { attributes: [{ key: "service.name", value: { stringValue: "codex_cli_rs" } }] },
            scopeSpans: [{ scope: {}, spans: otlpSpans }]
          }]
        });
        const host = this._client.getHost().replace(/\\/$/, "");
        const headers = await this._client.headersProvider();
        headers["Content-Type"] = "application/json";
        headers["X-MLflow-Experiment-Id"] = String(experimentId);
        const resp = await fetch(\`\${host}/v1/traces\`, { method: "POST", headers, body: payload });
        if (!resp.ok) {
          const text = await resp.text().catch(() => "");
          throw new Error(\`OTLP export failed: \${resp.status} \${text}\`);
        }
      }`,
};

// Make TOOL spans children of their triggering LLM span for proper nesting in MLflow UI
const bundleToolParentInitPatch = {
  file: "bundle/cli.js",
  from: `  let prevBoundaryNs = findTaskStartedNs(turnRecords);
  const responseItems = turnRecords.filter((record) => record.type === "response_item");
  for (let i2 = 0;`,
  to: `  let prevBoundaryNs = findTaskStartedNs(turnRecords);
  let currentLlmSpan = null;
  const responseItems = turnRecords.filter((record) => record.type === "response_item");
  for (let i2 = 0;`,
};

const bundleToolParentSavePatch = {
  file: "bundle/cli.js",
  from: `        llmSpan.end({
          outputs: {
            choices: [{ message: { role: "assistant", content: text } }]
          },
          endTimeNs: timestampNs
        });
        prevBoundaryNs = timestampNs;`,
  to: `        llmSpan.end({
          outputs: {
            choices: [{ message: { role: "assistant", content: text } }]
          },
          endTimeNs: timestampNs
        });
        currentLlmSpan = llmSpan;
        prevBoundaryNs = timestampNs;`,
};

const bundleToolParentUsePatch = {
  file: "bundle/cli.js",
  from: `        parent: parentSpan,
        spanType: import_core4.SpanType.TOOL,`,
  to: `        parent: currentLlmSpan ?? parentSpan,
        spanType: import_core4.SpanType.TOOL,`,
};

function getGlobalRoot() {
  try {
    const output = execFileSync("npm", ["root", "-g"], { encoding: "utf8" });
    return output.trim();
  } catch {
    return null;
  }
}

function patchFile(filePath, from, to) {
  if (!existsSync(filePath)) {
    return false;
  }

  const current = readFileSync(filePath, "utf8");
  if (current.includes(to)) {
    return false;
  }
  const candidates = Array.isArray(from) ? from : [from];
  for (const candidate of candidates) {
    if (!current.includes(candidate)) {
      continue;
    }
    const next = current.replace(candidate, to);
    if (next === current) {
      return false;
    }

    writeFileSync(filePath, next, "utf8");
    return true;
  }

  throw new Error(`Expected patch target not found in ${filePath}`);
}

function getPackageVersion(packageRoot) {
  try {
    const pkg = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
    return pkg.version ?? null;
  } catch {
    return null;
  }
}

function patchInstallRoot(root) {
  if (!root) {
    return [];
  }

  const packageRoot = join(root, PACKAGE_NAME);
  if (!existsSync(packageRoot)) {
    return [];
  }

  const version = getPackageVersion(packageRoot);
  if (version && version !== SUPPORTED_VERSION) {
    console.warn(
      `[mlflow-codex patch] WARNING: installed version is ${version}, ` +
      `supported version is ${SUPPORTED_VERSION}. Patch may not apply correctly.`
    );
  }

  const changed = [];
  const warnings = [];
  for (const patch of [textExtractionPatch, transcriptPatch, tracingPatch, tracingInputsPatch, tracingOutputsPatch, tracingCommentPatch, bundleTextExtractionPatch, bundleTracingPatch, bundleInputsPatch, bundleOutputsPatch, traceDataFormatPatch, artifactUriPatch, bundleOtlpExportPatch, bundleToolParentInitPatch, bundleToolParentSavePatch, bundleToolParentUsePatch]) {
    const filePath = join(packageRoot, patch.file);
    try {
      if (patchFile(filePath, patch.from, patch.to)) {
        changed.push(filePath);
      }
    } catch (err) {
      warnings.push(`  ${filePath}: ${err.message}`);
    }
  }
  if (warnings.length > 0) {
    console.warn("[mlflow-codex patch] Some patches could not be applied (version mismatch?):");
    warnings.forEach((w) => console.warn(w));
  }
  return changed;
}

const roots = [
  join(process.cwd(), "node_modules"),
  getGlobalRoot(),
];

const changedFiles = roots.flatMap((root) => patchInstallRoot(root));

if (changedFiles.length > 0) {
  console.log(`Applied MLflow Codex patch to ${changedFiles.length} file(s).`);
} else {
  console.log("MLflow Codex patch already applied or package not installed.");
}
