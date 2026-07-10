from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from init_agent.agent_tools import repo_reading_plan, repo_reading_plan_finish
from init_agent.feedback import add_feedback
from init_agent.graph_store import GraphStore
from init_agent.memory import add_note
from init_agent.plan_feedback import reading_plan_stats
from init_agent.query import related
from init_agent.refresh import refresh_index
from init_agent.scanner import scan_project
from init_agent.trace import trace_query
from init_agent.utils import ensure_agent_dir


class RelationResolutionTests(unittest.TestCase):
    def test_python_imported_calls_resolve_without_ambiguous_global_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "main.py", "from app.service import save as persist\n\ndef run():\n    return persist()\n")
            self._write(root, "app/service.py", "def save():\n    return 'ok'\n")
            self._write(root, "noise/legacy.py", "def save():\n    return 'legacy'\n")
            self._map(root)

            resolved = self._resolved_edges(root)
            self.assertIn(("main.py", "imports", "app/service.py"), resolved)
            self.assertIn(("main.py", "imports_symbol", "app/service.py"), resolved)
            self.assertIn(("main.py", "calls", "app/service.py"), resolved)
            self.assertNotIn(("main.py", "calls", "noise/legacy.py"), resolved)

            trace = trace_query(root, "startup lifecycle", limit=20)
            traced_paths = {path for item in trace["paths"] for path in item.get("path", [])}
            self.assertIn("app/service.py", traced_paths)
            self.assertNotIn("noise/legacy.py", traced_paths)
            related_main = related(root, "main.py")
            self.assertIsNotNone(related_main)
            resolved_calls = {item["name"]: item for item in related_main["resolved_calls"]}
            self.assertEqual(resolved_calls["persist"]["definitions"][0]["path"], "app/service.py")
            related_service = related(root, "app/service.py")
            self.assertEqual(related_service["callers"][0]["path"], "main.py")

    def test_php_dir_includes_and_unique_functions_resolve_to_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "index.php", "<?php require_once __DIR__ . '/include/bootstrap.php'; runPage();\n")
            self._write(root, "include/bootstrap.php", "<?php require_once __DIR__ . '/functions.php';\n")
            self._write(root, "include/functions.php", "<?php function runPage() { return true; }\n")
            self._map(root)

            resolved = self._resolved_edges(root)
            self.assertIn(("index.php", "require_once", "include/bootstrap.php"), resolved)
            self.assertIn(("include/bootstrap.php", "require_once", "include/functions.php"), resolved)
            self.assertIn(("index.php", "calls", "include/functions.php"), resolved)

    def test_ambiguous_unscoped_python_call_remains_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "main.py", "def run():\n    return save()\n")
            self._write(root, "left.py", "def save():\n    return 1\n")
            self._write(root, "right.py", "def save():\n    return 2\n")
            self._map(root)

            resolved = self._resolved_edges(root)
            self.assertFalse(any(source == "main.py" and relation == "calls" for source, relation, _ in resolved))

    def test_unique_php_symbol_outside_include_component_remains_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "public/index.php", "<?php echo internalOnly();\n")
            self._write(root, "tools/internal.php", "<?php function internalOnly() { return true; }\n")
            self._map(root)

            resolved = self._resolved_edges(root)
            self.assertNotIn(("public/index.php", "calls", "tools/internal.php"), resolved)

    def test_incremental_refresh_rebuilds_resolved_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "main.py", "from app.first import run\nrun()\n")
            self._write(root, "app/first.py", "def run():\n    return 1\n")
            self._map(root)
            self.assertIn(("main.py", "calls", "app/first.py"), self._resolved_edges(root))

            self._write(root, "main.py", "from app.second import run\nrun()\n")
            self._write(root, "app/second.py", "def run():\n    return 2\n")
            refreshed = refresh_index(root)
            self.assertEqual(refreshed["status"], "OK")
            resolved = self._resolved_edges(root)
            self.assertIn(("main.py", "calls", "app/second.py"), resolved)
            self.assertNotIn(("main.py", "calls", "app/first.py"), resolved)

    def test_plan_manifest_reclassifies_new_missing_file_as_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "main.py", "def main():\n    return 0\n")
            self._map(root)
            plan = repo_reading_plan(root, "change main runtime", limit=5, read_budget=1, prepare=False)
            plan_id = int(plan["id"])
            self._write(root, "new_module.py", "def created():\n    return True\n")

            result = repo_reading_plan_finish(
                root,
                plan_id,
                read=["main.py", "new_module.py"],
                verified=["main.py", "new_module.py"],
                central=["main.py"],
                missing=["new_module.py"],
            )
            events = {(item["event"], item["path"]) for item in result["events"]}
            self.assertIn(("created", "new_module.py"), events)
            self.assertNotIn(("missing", "new_module.py"), events)
            stats = reading_plan_stats(root)
            self.assertEqual(stats["created_count"], 1)
            self.assertEqual(stats["missing_count"], 0)

    def test_preexisting_excluded_file_is_not_inferred_as_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "main.py", "def main():\n    return 0\n")
            self._write(root, "node_modules/hidden.py", "def hidden():\n    return True\n")
            self._map(root)
            plan = repo_reading_plan(root, "inspect hidden support", limit=5, read_budget=1, prepare=False)
            result = repo_reading_plan_finish(root, int(plan["id"]), missing=["node_modules/hidden.py"])
            events = {(item["event"], item["path"]) for item in result["events"]}
            self.assertIn(("missing", "node_modules/hidden.py"), events)
            self.assertNotIn(("created", "node_modules/hidden.py"), events)

    def test_plan_persists_observed_memory_feedback_and_tag_rank_lift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "alpha.py", "def alpha_runtime():\n    return True\n")
            self._write(root, "beta.py", "def beta_runtime():\n    return True\n")
            self._map(root)
            add_note(
                root,
                path="beta.py",
                topic="runtime selection",
                query="choose runtime handler",
                note="beta.py owns the verified runtime handler.",
                evidence="read_full_file",
                tags=["runtime", "handler"],
            )
            add_feedback(root, "choose runtime handler", "beta.py", "useful", reason="verified", source="agent")
            plan = repo_reading_plan(root, "choose runtime handler", limit=5, read_budget=1, prepare=False)
            beta = next(item for item in plan["plan_items"] if item["path"] == "beta.py")
            self.assertIn("base_rank", beta)
            self.assertIn("memory", beta["signal_rank_lift"])
            result = repo_reading_plan_finish(root, int(plan["id"]), read=["beta.py"], central=["beta.py"])
            self.assertTrue(result["updated"])
            stats = reading_plan_stats(root)
            self.assertGreaterEqual(stats["signal_impact"]["memory"]["observed_useful_files"], 1)
            self.assertGreaterEqual(stats["signal_impact"]["feedback"]["observed_useful_files"], 1)
            self.assertGreaterEqual(stats["signal_impact"]["tags"]["observed_useful_files"], 1)

    @staticmethod
    def _write(root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _map(root: Path) -> None:
        ensure_agent_dir(root)
        with GraphStore(root) as store:
            store.initialize()
            scan_project(root, store)

    @staticmethod
    def _resolved_edges(root: Path) -> set[tuple[str, str, str]]:
        with GraphStore(root) as store:
            store.initialize()
            rows = store.connection.execute(
                """
                SELECT f.path AS source, r.relation, r.target_id
                FROM relations r
                JOIN files f ON f.id = r.source_id
                WHERE r.source_type = 'file' AND r.target_type = 'resolved_file'
                """
            ).fetchall()
        return {(str(row["source"]), str(row["relation"]), str(row["target_id"])) for row in rows}


if __name__ == "__main__":
    unittest.main()
