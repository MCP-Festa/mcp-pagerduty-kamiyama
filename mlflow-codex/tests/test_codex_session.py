import unittest
from pathlib import Path

from mlflow_codex.codex_session import classify_tool_name, load_session
from mlflow_codex.redaction import redact
from mlflow_codex.tracer import _message_payload

FIXTURE = Path(__file__).parent / "fixtures" / "codex_session.jsonl"


class CodexSessionTests(unittest.TestCase):
    def test_loads_messages_and_tool_calls(self) -> None:
        session = load_session(FIXTURE)

        self.assertEqual(session.session_id, "session-1")
        self.assertEqual(session.model, "gpt-5.5")
        self.assertEqual(len(session.messages), 2)
        self.assertEqual(session.user_messages[0].text, "List files")
        self.assertEqual(session.assistant_messages[0].text, "README.md")

        self.assertEqual(len(session.tool_calls), 1)
        call = session.tool_calls[0]
        self.assertEqual(call.name, "mcp__filesystem__list_directory")
        self.assertEqual(call.arguments["path"], ".")
        self.assertEqual(call.output["files"], ["README.md"])
        self.assertEqual(call.classification["kind"], "mcp")
        self.assertEqual(call.classification["mcp_server"], "filesystem")
        self.assertEqual(call.classification["mcp_tool"], "list_directory")

    def test_redacts_secrets_recursively(self) -> None:
        payload = {"api_key": "abc", "nested": {"authorization": "Bearer xyz"}, "ok": "value"}

        self.assertEqual(
            redact(payload),
            {"api_key": "[REDACTED]", "nested": {"authorization": "[REDACTED]"}, "ok": "value"},
        )

    def test_classifies_non_mcp_tools(self) -> None:
        self.assertEqual(classify_tool_name("exec_command")["kind"], "codex_builtin")
        self.assertEqual(classify_tool_name("custom_tool")["kind"], "tool")

    def test_classifies_bare_zabbix_mcp_tool_names(self) -> None:
        classification = classify_tool_name("list_hosts")

        self.assertEqual(classification["kind"], "mcp")
        self.assertEqual(classification["mcp_server"], "zabbix")
        self.assertEqual(classification["mcp_tool"], "list_hosts")

    def test_message_payload_uses_normalized_text_for_content(self) -> None:
        session = load_session(FIXTURE)
        payload = _message_payload(session.user_messages[0])

        self.assertEqual(payload["content"], "List files")
        self.assertEqual(payload["text"], "List files")
        self.assertNotIn("content_blocks", payload)

    def test_message_payload_preserves_structured_content_separately(self) -> None:
        session = load_session(FIXTURE)
        payload = _message_payload(session.assistant_messages[0])

        self.assertEqual(payload["content"], "README.md")
        self.assertEqual(payload["text"], "README.md")
        self.assertIn("content_blocks", payload)


if __name__ == "__main__":
    unittest.main()
