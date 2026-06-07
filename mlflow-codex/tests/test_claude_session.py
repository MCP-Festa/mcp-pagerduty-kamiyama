import unittest
from pathlib import Path

from mlflow_codex.claude_session import load_claude_session

FIXTURE = Path(__file__).parent / "fixtures" / "claude_session.jsonl"


class ClaudeSessionTests(unittest.TestCase):
    def test_loads_metadata(self) -> None:
        session = load_claude_session(FIXTURE)

        self.assertEqual(session.session_id, "session-claude-1")
        self.assertEqual(session.ai_title, "List files in project")
        self.assertEqual(session.model, "claude-sonnet-4-6")
        self.assertEqual(session.cwd, "/home/user/project")
        self.assertEqual(session.version, "2.1.126")

    def test_loads_messages(self) -> None:
        session = load_claude_session(FIXTURE)

        self.assertEqual(len(session.user_messages), 1)
        self.assertEqual(session.user_messages[0].text, "ファイルを一覧してください")

        self.assertEqual(len(session.assistant_messages), 2)
        self.assertIn("ファイルを確認します", session.assistant_messages[0].text)
        self.assertIn("README.md", session.assistant_messages[1].text)

    def test_loads_tool_calls(self) -> None:
        session = load_claude_session(FIXTURE)

        self.assertEqual(len(session.tool_calls), 1)
        call = session.tool_calls[0]
        self.assertEqual(call.name, "mcp__filesystem__list_directory")
        self.assertEqual(call.arguments["path"], ".")
        self.assertIn("README.md", call.output_raw or "")

        cls = call.classification
        self.assertEqual(cls["kind"], "mcp")
        self.assertEqual(cls["mcp_server"], "filesystem")
        self.assertEqual(cls["mcp_tool"], "list_directory")

    def test_aggregates_token_usage(self) -> None:
        session = load_claude_session(FIXTURE)

        self.assertEqual(len(session.token_usages), 2)
        total_input = sum(u.get("input_tokens", 0) for u in session.token_usages)
        self.assertEqual(total_input, 250)  # 100 + 150

    def test_turn_durations(self) -> None:
        session = load_claude_session(FIXTURE)

        self.assertEqual(len(session.turn_durations), 1)
        self.assertEqual(session.turn_durations[0]["durationMs"], 3000)

    def test_timestamps(self) -> None:
        session = load_claude_session(FIXTURE)

        self.assertEqual(session.started_at, "2026-05-30T10:00:00.000Z")
        self.assertEqual(session.ended_at, "2026-05-30T10:00:03.000Z")


if __name__ == "__main__":
    unittest.main()
