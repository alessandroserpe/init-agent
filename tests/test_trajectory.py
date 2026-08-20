from tests.support import *

from concurrent.futures import ThreadPoolExecutor

from init_agent.trajectory import CODEX_HOOK_EVENTS, ingest_codex_hook
from init_agent.trajectory_hook_cli import main as hook_main
from init_agent.trajectory_hooks import (
    codex_trajectory_hook_status,
    install_codex_trajectory_hooks,
    uninstall_codex_trajectory_hooks,
)
from init_agent.web_ui import build_web_snapshot, render_dashboard_html


class TrajectoryTests(InitAgentTestCase):
    def test_codex_hook_ingestion_redacts_payloads_and_pairs_tool_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            session = "session-private-123"
            ingest_codex_hook(
                root,
                {
                    "hook_event_name": "SessionStart",
                    "session_id": session,
                    "cwd": str(root),
                    "model": "test-model",
                    "source": "startup",
                },
                recorded_at="2026-08-20T10:00:00.000+00:00",
            )
            ingest_codex_hook(
                root,
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": session,
                    "turn_id": "turn-1",
                    "tool_name": "Bash",
                    "tool_use_id": "tool-1",
                    "cwd": str(root),
                    "tool_input": {
                        "command": "API_TOKEN=SECRET_VALUE python3 scripts/check.py --password SECRET_PASSWORD",
                        "path": str(root / "src" / "auth" / "session.py"),
                        "outside_path": "/Users/example/.ssh/id_ed25519",
                        "file": "SECRET_FAKE_PATH",
                    },
                },
                recorded_at="2026-08-20T10:00:01.000+00:00",
            )
            result = ingest_codex_hook(
                root,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": session,
                    "turn_id": "turn-1",
                    "tool_name": "Bash",
                    "tool_use_id": "tool-1",
                    "cwd": str(root),
                    "tool_input": {
                        "command": "API_TOKEN=SECRET_VALUE python3 scripts/check.py --password SECRET_PASSWORD",
                        "path": str(root / "src" / "auth" / "session.py"),
                    },
                    "tool_response": {"exit_code": 0, "output": "SECRET TOOL OUTPUT"},
                },
                recorded_at="2026-08-20T10:00:03.250+00:00",
            )
            duplicate = ingest_codex_hook(
                root,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": session,
                    "turn_id": "turn-1",
                    "tool_name": "Bash",
                    "tool_use_id": "tool-1",
                    "cwd": str(root),
                    "tool_input": {"command": "do-not-store-this --secret duplicated"},
                    "tool_response": {"exit_code": 0, "output": "duplicate output"},
                },
                recorded_at="2026-08-20T10:00:03.500+00:00",
            )
            ingest_codex_hook(
                root,
                {
                    "hook_event_name": "SubagentStart",
                    "session_id": session,
                    "turn_id": "turn-1",
                    "agent_id": "agent-1",
                    "agent_type": "explorer",
                    "cwd": str(root),
                },
                recorded_at="2026-08-20T10:00:04.000+00:00",
            )
            ingest_codex_hook(
                root,
                {
                    "hook_event_name": "SessionEnd",
                    "session_id": session,
                    "cwd": str(root),
                    "reason": "other",
                },
                recorded_at="2026-08-20T10:00:05.000+00:00",
            )

            self.assertEqual(result["duration_ms"], 2250)
            self.assertFalse(duplicate["recorded"])
            self.assertEqual(duplicate["status"], "duplicate")
            with sqlite3.connect(root / ".agent" / "graph.sqlite") as conn:
                event_rows = conn.execute(
                    "SELECT event_name, status, duration_ms, metadata_json FROM trajectory_events ORDER BY id"
                ).fetchall()
                serialized = "\n".join(str(value) for row in event_rows for value in row)
                session_row = conn.execute(
                    "SELECT model, cwd, ended_at, end_reason FROM trajectory_sessions"
                ).fetchone()

            self.assertNotIn("SECRET_VALUE", serialized)
            self.assertNotIn("SECRET_PASSWORD", serialized)
            self.assertNotIn("SECRET TOOL OUTPUT", serialized)
            self.assertNotIn("SECRET_FAKE_PATH", serialized)
            database_bytes = (root / ".agent" / "graph.sqlite").read_bytes()
            self.assertNotIn(b"SECRET_VALUE", database_bytes)
            self.assertNotIn(b"SECRET_PASSWORD", database_bytes)
            self.assertNotIn(b"SECRET TOOL OUTPUT", database_bytes)
            self.assertNotIn(b"SECRET_FAKE_PATH", database_bytes)
            self.assertIn("src/auth/session.py", serialized)
            self.assertIn("<outside-repository>", serialized)
            self.assertIn('"command_name": "python3"', serialized)
            self.assertEqual(session_row[0], "test-model")
            self.assertEqual(session_row[1], ".")
            self.assertEqual(session_row[3], "other")

            snapshot = build_web_snapshot(root, limit=20)
            self.assertEqual(snapshot["trajectory_summary"]["session_count"], 1)
            self.assertEqual(snapshot["trajectory_summary"]["tool_call_count"], 1)
            self.assertEqual(snapshot["trajectory_summary"]["subagent_count"], 1)
            self.assertEqual(snapshot["trajectory_summary"]["average_tool_duration_ms"], 2250.0)
            self.assertEqual(snapshot["trajectory_sessions"][0]["status"], "finished")
            html = render_dashboard_html(snapshot)
            self.assertIn('data-tab-target="trajectory"', html)
            self.assertIn("Observable Trajectory", html)

    def test_ingest_skips_repositories_without_an_existing_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = ingest_codex_hook(
                Path(tmp),
                {"hook_event_name": "SessionStart", "session_id": "session-1", "cwd": tmp},
            )
            self.assertFalse(result["recorded"])
            self.assertEqual(result["status"], "not_initialized")
            self.assertFalse((Path(tmp) / ".agent").exists())

    def test_codex_hook_install_is_idempotent_and_preserves_other_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hooks_path = Path(tmp) / "hooks.json"
            hooks_path.write_text(
                json.dumps(
                    {
                        "description": "existing hooks",
                        "hooks": {
                            "PostToolUse": [
                                {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool audit"}]}
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            installed = install_codex_trajectory_hooks(hooks_path, command="/tmp/init-agent-hook")
            self.assertTrue(installed["current"])
            self.assertEqual(set(installed["events"]), CODEX_HOOK_EVENTS)
            self.assertTrue(Path(installed["backup_path"]).is_file())
            first_data = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertIn("other-tool audit", json.dumps(first_data))
            self.assertIn("/tmp/init-agent-hook --init-agent-trajectory-hook", json.dumps(first_data))

            repeated = install_codex_trajectory_hooks(hooks_path, command="/tmp/init-agent-hook")
            self.assertFalse(repeated["updated"])
            second_data = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertEqual(first_data, second_data)

            removed = uninstall_codex_trajectory_hooks(hooks_path)
            self.assertTrue(removed["removed"])
            remaining = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertIn("other-tool audit", json.dumps(remaining))
            self.assertNotIn("--init-agent-trajectory-hook", json.dumps(remaining))
            self.assertFalse(codex_trajectory_hook_status(hooks_path)["installed"])

    def test_trajectory_cli_installs_hooks_and_lightweight_hook_ingests_from_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            root = _create_context_fixture(repo)
            _prepare_index(root)
            hooks_path = Path(tmp) / "hooks.json"
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["trajectory", "install-codex", "--config-path", str(hooks_path), "--json"]),
                    0,
                )
            self.assertTrue(json.loads(output.getvalue())["current"])

            previous = Path.cwd()
            try:
                os.chdir(root)
                payload = {
                    "hook_event_name": "SessionStart",
                    "session_id": "cli-session",
                    "cwd": str(root / "src" / "auth"),
                }
                os.chdir(root / "src" / "auth")
                previous_stdin = sys.stdin
                try:
                    sys.stdin = StringIO(json.dumps(payload))
                    self.assertEqual(hook_main(), 0)
                finally:
                    sys.stdin = previous_stdin
            finally:
                os.chdir(previous)

            with GraphStore(root) as store:
                store.initialize()
                self.assertEqual(store._count("trajectory_events"), 1)

    def test_lightweight_hook_fails_open_for_invalid_input(self) -> None:
        previous_stdin = sys.stdin
        try:
            sys.stdin = StringIO("not-json")
            self.assertEqual(hook_main(), 0)
        finally:
            sys.stdin = previous_stdin

    def test_concurrent_hook_events_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)

            def record(index: int) -> bool:
                result = ingest_codex_hook(
                    root,
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "concurrent-session",
                        "turn_id": f"turn-{index}",
                        "tool_name": "Read",
                        "tool_use_id": f"tool-{index}",
                        "cwd": str(root),
                        "tool_input": {"path": str(root / "src" / "auth" / "session.py")},
                    },
                )
                return bool(result["recorded"])

            with ThreadPoolExecutor(max_workers=4) as executor:
                recorded = list(executor.map(record, range(12)))

            self.assertEqual(recorded, [True] * 12)
            with GraphStore(root) as store:
                store.initialize()
                self.assertEqual(store._count("trajectory_sessions"), 1)
                self.assertEqual(store._count("trajectory_events"), 12)
