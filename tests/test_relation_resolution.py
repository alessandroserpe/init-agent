from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

from init_agent.agent_tools import repo_reading_plan, repo_reading_plan_finish
from init_agent.exporter import export_graph
from init_agent.feedback import add_feedback
from init_agent.graph_store import GraphStore
from init_agent.memory import add_note
from init_agent.plan_feedback import reading_plan_stats
from init_agent.query import callers_for_symbol, related
from init_agent.refresh import refresh_index
from init_agent.scanner import scan_project
from init_agent.trace import trace_query
from init_agent.utils import ensure_agent_dir


class RelationResolutionTests(unittest.TestCase):
    def test_graph_store_migrates_legacy_symbol_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_agent_dir(root)
            connection = sqlite3.connect(root / ".agent" / "graph.sqlite")
            connection.execute(
                """
                CREATE TABLE symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    line INTEGER,
                    signature TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    confidence REAL,
                    metadata_json TEXT
                )
                """
            )
            connection.commit()
            connection.close()

            with GraphStore(root) as store:
                store.initialize()
                columns = {str(row["name"]) for row in store.connection.execute("PRAGMA table_info(symbols)")}
                relation_columns = {
                    str(row["name"])
                    for row in store.connection.execute("PRAGMA table_info(relations)")
                }
            self.assertTrue({"qualified_name", "container_name", "end_line"}.issubset(columns))
            self.assertIn("context_symbol_id", relation_columns)

    def test_python_symbol_graph_resolves_calls_and_inheritance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "app/base.py", "class BaseHandler:\n    pass\n")
            self._write(root, "app/service.py", "def save():\n    return True\n")
            self._write(
                root,
                "app/handler.py",
                "from app.base import BaseHandler\n"
                "from app.service import save\n\n"
                "class RequestHandler(BaseHandler):\n"
                "    def dispatch(self):\n"
                "        return save()\n",
            )
            self._map(root)

            edges = self._resolved_symbol_edges(root)
            self.assertIn(("app/handler.py", "RequestHandler", "inherits", "app/base.py", "BaseHandler"), edges)
            self.assertIn(("app/handler.py", "RequestHandler.dispatch", "calls", "app/service.py", "save"), edges)

            callers = callers_for_symbol(root, "save")
            self.assertEqual(callers["callers"][0]["path"], "app/handler.py")
            self.assertEqual(callers["callers"][0]["source_qualified_name"], "RequestHandler.dispatch")
            related_handler = related(root, "app/handler.py")
            self.assertIsNotNone(related_handler)
            relation_names = {item["relation"] for item in related_handler["symbol_relations"]}
            self.assertEqual(relation_names, {"calls", "inherits"})
            exported = export_graph(root)
            symbol_edges = [
                item
                for item in exported["relations"]
                if item["source_type"] == "symbol" and item["target_type"] == "resolved_symbol"
            ]
            self.assertTrue(any(item.get("source_symbol", {}).get("qualified_name") == "RequestHandler.dispatch" for item in symbol_edges))
            self.assertTrue(any(item.get("target_symbol", {}).get("qualified_name") == "BaseHandler" for item in symbol_edges))
            scoped_raw_calls = [
                item
                for item in exported["relations"]
                if item["source_type"] == "file"
                and item["relation"] == "calls"
                and item.get("context_symbol")
            ]
            self.assertTrue(
                any(item["context_symbol"]["qualified_name"] == "RequestHandler.dispatch" for item in scoped_raw_calls)
            )

    def test_python_receiver_calls_stay_within_verified_class_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                "app/base.py",
                "class ParentView:\n"
                "    def get_success_url(self):\n"
                "        return '/done'\n\n"
                "    def form_valid(self):\n"
                "        return True\n",
            )
            self._write(
                root,
                "app/views.py",
                "from app.base import ParentView\n\n"
                "class UnrelatedView:\n"
                "    def get_user(self):\n"
                "        return None\n\n"
                "class LoginView(ParentView):\n"
                "    def form_valid(self, form):\n"
                "        self.get_user()\n"
                "        form.get_user()\n"
                "        self.get_success_url()\n"
                "        return super().form_valid()\n",
            )
            self._map(root)

            edges = self._resolved_symbol_edges(root)
            self.assertIn(
                ("app/views.py", "LoginView.form_valid", "calls", "app/base.py", "ParentView.get_success_url"),
                edges,
            )
            self.assertIn(
                ("app/views.py", "LoginView.form_valid", "calls", "app/base.py", "ParentView.form_valid"),
                edges,
            )
            self.assertNotIn(
                ("app/views.py", "LoginView.form_valid", "calls", "app/views.py", "UnrelatedView.get_user"),
                edges,
            )

    def test_php_symbol_graph_resolves_calls_and_inheritance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "base.php", "<?php class BaseController {}\n")
            self._write(root, "helpers.php", "<?php function renderPage() { return true; }\n")
            self._write(
                root,
                "admin.php",
                "<?php\n"
                "require_once 'base.php';\n"
                "require_once 'helpers.php';\n"
                "class AdminController extends BaseController {\n"
                "    public function show() { return renderPage(); }\n"
                "}\n",
            )
            self._map(root)

            edges = self._resolved_symbol_edges(root)
            self.assertIn(("admin.php", "AdminController", "inherits", "base.php", "BaseController"), edges)
            self.assertIn(("admin.php", "AdminController::show", "calls", "helpers.php", "renderPage"), edges)

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

    def test_incremental_refresh_removes_obsolete_symbol_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "service.py", "def save():\n    return True\n")
            self._write(root, "main.py", "from service import save\n\ndef run():\n    return save()\n")
            self._map(root)
            self.assertTrue(any(edge[1] == "run" and edge[2] == "calls" for edge in self._resolved_symbol_edges(root)))

            self._write(root, "main.py", "from service import save\n\ndef execute():\n    return save()\n")
            refreshed = refresh_index(root)
            self.assertEqual(refreshed["status"], "OK")
            edges = self._resolved_symbol_edges(root)
            self.assertFalse(any(edge[1] == "run" for edge in edges))
            self.assertTrue(any(edge[1] == "execute" and edge[2] == "calls" for edge in edges))

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

    @staticmethod
    def _resolved_symbol_edges(root: Path) -> set[tuple[str, str, str, str, str]]:
        with GraphStore(root) as store:
            store.initialize()
            rows = store.connection.execute(
                """
                SELECT source_file.path AS source_path,
                       source.qualified_name AS source_symbol,
                       r.relation,
                       target_file.path AS target_path,
                       target.qualified_name AS target_symbol
                FROM relations r
                JOIN symbols source ON source.id = r.source_id
                JOIN files source_file ON source_file.id = source.file_id
                JOIN symbols target ON target.id = CAST(r.target_id AS INTEGER)
                JOIN files target_file ON target_file.id = target.file_id
                WHERE r.source_type = 'symbol' AND r.target_type = 'resolved_symbol'
                """
            ).fetchall()
        return {
            (
                str(row["source_path"]),
                str(row["source_symbol"]),
                str(row["relation"]),
                str(row["target_path"]),
                str(row["target_symbol"]),
            )
            for row in rows
        }


if __name__ == "__main__":
    unittest.main()
