from tests.support import *

from init_agent.agent_tools import (
    repo_reading_plan,
    repo_reading_plan_finish,
    repo_session_close,
)
from init_agent.index_health import clear_index_health_cache
from init_agent.memory import add_note


class IndexHealthTests(InitAgentTestCase):
    def tearDown(self) -> None:
        clear_index_health_cache()

    def test_mcp_overview_reports_filesystem_drift_and_hides_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            _prepare_index(root)
            (root / "README.md").unlink()
            (root / "src" / "sample" / "cli.py").write_text(
                "def main():\n    return 42\n\ndef changed():\n    return True\n",
                encoding="utf-8",
            )
            (root / "src" / "sample" / "new_module.py").write_text(
                "def new_feature():\n    return True\n",
                encoding="utf-8",
            )
            clear_index_health_cache()

            server = InitAgentMcpServer(root)
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "repo_overview", "arguments": {}},
                }
            )
            assert response is not None
            data = response["result"]["structuredContent"]
            health = data["preparation"]["index_health"]
            self.assertEqual(health["status"], "stale")
            self.assertGreaterEqual(health["changed_count"], 1)
            self.assertGreaterEqual(health["missing_count"], 1)
            self.assertGreaterEqual(health["unindexed_count"], 1)
            self.assertTrue(any("index may be stale" in warning for warning in data["warnings"]))
            returned_paths = {
                str(item.get("path") or "")
                for key in ("suggested_first_reads", "entry_points", "manifests")
                for item in data.get(key, [])
            }
            self.assertNotIn("README.md", returned_paths)

    def test_reading_plan_excludes_deleted_index_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            (root / "src" / "auth" / "session.py").unlink()
            clear_index_health_cache()

            plan = repo_reading_plan(root, "validate session timeout", prepare=False)
            self.assertEqual(plan["preparation"]["index_health"]["status"], "stale")
            self.assertNotIn(
                "src/auth/session.py",
                {item["path"] for item in plan["plan_items"]},
            )

    def test_deleted_useful_files_are_not_suggested_as_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            plan = repo_reading_plan(root, "validate login session", prepare=False)
            target = "src/auth/session.py"
            (root / target).unlink()

            finished = repo_reading_plan_finish(
                root,
                int(plan["id"]),
                read=[target],
                verified=[target],
                useful=[target],
                summary="verified before file removal",
            )
            self.assertEqual(finished["suggested_memory"], [])

            clear_index_health_cache()
            closed = repo_session_close(root)
            commands = [item["command"] for item in closed["suggested_memory"]]
            self.assertFalse(any(target in command for command in commands))
            self.assertEqual(closed["index_health"]["status"], "stale")
            self.assertFalse(closed["close_ready"])

    def test_session_close_does_not_suggest_duplicate_fresh_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            plan = repo_reading_plan(root, "validate login session", prepare=False)
            target = "src/auth/session.py"
            repo_reading_plan_finish(
                root,
                int(plan["id"]),
                read=[target],
                verified=[target],
                useful=[target],
                summary="verified session flow",
            )
            add_note(
                root,
                path=target,
                scope="file",
                topic="login session",
                query="validate login session",
                note="Owns session timeout validation for the sample application.",
                source="agent",
                evidence="read_excerpt",
                tags=["login", "session"],
            )

            closed = repo_session_close(root)
            commands = [item["command"] for item in closed["suggested_memory"]]
            self.assertFalse(any(target in command and "repo_memory_add" in command for command in commands))

    def test_mcp_related_and_callers_are_bounded_with_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "include"
            include.mkdir()
            functions = ["<?php"]
            for index in range(25):
                name = "buildForm" if index == 0 else f"helper{index}"
                functions.append(f"function {name}() {{ return {index}; }}")
            (include / "functions.php").write_text("\n".join(functions) + "\n", encoding="utf-8")
            for index in range(20):
                (root / f"caller_{index}.php").write_text(
                    "<?php\nrequire_once __DIR__ . '/include/functions.php';\nbuildForm();\n",
                    encoding="utf-8",
                )
            _prepare_index(root)
            server = InitAgentMcpServer(root, profile="full")

            related_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "repo_related_file", "arguments": {"path": "include/functions.php"}},
                }
            )
            callers_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "repo_symbol_callers", "arguments": {"symbol": "buildForm"}},
                }
            )
            detailed_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_related_file",
                        "arguments": {"path": "include/functions.php", "include_details": True},
                    },
                }
            )
            assert related_response is not None
            assert callers_response is not None
            assert detailed_response is not None
            related = related_response["result"]["structuredContent"]
            callers = callers_response["result"]["structuredContent"]
            detailed = detailed_response["result"]["structuredContent"]

            self.assertTrue(related["compact"])
            self.assertEqual(related["counts"]["symbols"], 25)
            self.assertEqual(len(related["symbols"]), 12)
            self.assertTrue(related["truncated"]["symbols"])
            self.assertTrue(callers["compact"])
            self.assertEqual(callers["counts"]["callers"], 20)
            self.assertEqual(len(callers["callers"]), 15)
            self.assertTrue(callers["truncated"]["callers"])
            self.assertNotIn("compact", detailed)
            self.assertEqual(len(detailed["symbols"]), 25)
            self.assertLess(len(json.dumps(related_response)), 20_000)
            self.assertLess(len(json.dumps(callers_response)), 20_000)


if __name__ == "__main__":
    unittest.main()
