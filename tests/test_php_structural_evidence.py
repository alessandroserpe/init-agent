from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import json
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from init_agent.native_parser import PHPStructuralSyntaxError, extract_php_isolated
from init_agent.analysis_capabilities import build_capabilities
from init_agent.symbol_extractor import (
    _php_add_use_aliases,
    _php_declaration_name,
    _php_includes_in_line,
    _php_qualify_name,
    _php_use_aliases,
    _tree_sitter_php_call_metadata,
    _tree_sitter_static_include_target,
    _extract_php_tree_sitter,
    extract_symbols_and_relations,
)
from init_agent.evidence_trace import trace_evidence
from init_agent.graph_store import GraphStore
from init_agent.scanner import scan_project
from init_agent.utils import ensure_agent_dir


class Node:
    def __init__(self, node_type: str, text: str = "", fields: dict[str, "Node"] | None = None, start: int = 0):
        self.type = node_type
        self.start_byte = start
        self.end_byte = start + len(text.encode())
        self._fields = fields or {}

    def child_by_field_name(self, name: str):
        return self._fields.get(name)


class AstNode(Node):
    def __init__(self, node_type: str, source: str, start: int, end: int,
                 fields: dict[str, "AstNode"] | None = None, children: list["AstNode"] | None = None):
        super().__init__(node_type, fields=fields)
        self.start_byte = start
        self.end_byte = end
        self.named_children = children or []
        self.start_point = (source[:start].count("\n"), 0)
        self.end_point = (source[:end].count("\n"), 0)
        self.has_error = False


class PhpStructuralEvidenceTests(unittest.TestCase):
    def test_import_alias_and_namespace_qualification(self):
        aliases = _php_use_aliases("use Vendor\\Library\\Widget as Thing;")
        self.assertEqual(aliases, {"thing": "Vendor\\Library\\Widget"})
        self.assertEqual(_php_qualify_name("Thing", "App\\Http", aliases), "Vendor\\Library\\Widget")
        self.assertEqual(_php_qualify_name("Local", "App\\Http", aliases), "App\\Http\\Local")
        self.assertEqual(_php_qualify_name("\\GlobalType", "App\\Http", aliases), "GlobalType")
        self.assertEqual(_php_declaration_name("Thing", "App\\Http"), "App\\Http\\Thing")
        function_aliases: dict[str, dict[str, str]] = {}
        _php_add_use_aliases(function_aliases, "use function Vendor\\Fns\\run as Alias;")
        self.assertEqual(function_aliases, {"function": {"alias": "Vendor\\Fns\\run"}})
        self.assertEqual(_php_qualify_name("Alias", "App", function_aliases, "class"), "App\\Alias")
        self.assertEqual(_php_qualify_name("Alias", "App", function_aliases, "function"), "Vendor\\Fns\\run")

    def test_unbracketed_namespace_and_function_alias_reach_following_siblings(self):
        source = (
            "<?php\nnamespace App;\nuse function Vendor\\Functions\\run as Alias;\n"
            "function run() { Alias(); }\n"
        )
        name_start = source.index("run()")
        call_start = source.index("Alias()")
        namespace_start = source.index("App;")
        import_start = source.index("use function")
        name_node = AstNode("name", source, name_start, name_start + 3)
        alias_node = AstNode("name", source, call_start, call_start + 5)
        call_node = AstNode(
            "function_call_expression", source, call_start, call_start + len("Alias()"),
            fields={"function": alias_node}, children=[alias_node],
        )
        namespace_name = AstNode("namespace_name", source, namespace_start, namespace_start + 3)
        namespace_node = AstNode(
            "namespace_definition", source, source.index("namespace"), namespace_start + 4,
            fields={"name": namespace_name}, children=[namespace_name],
        )
        use_node = AstNode(
            "namespace_use_declaration", source, import_start,
            source.index(";", import_start) + 1,
        )
        function_node = AstNode(
            "function_definition", source, source.index("function run"), len(source),
            fields={"name": name_node}, children=[name_node, call_node],
        )
        root_node = AstNode("program", source, 0, len(source), children=[namespace_node, use_node, function_node])

        class Parser:
            language = None

            def parse(self, _source: bytes):
                return SimpleNamespace(root_node=root_node)

        with patch("init_agent.symbol_extractor._php_tree_sitter_parser", return_value=(Parser(), object())):
            symbols, relations = _extract_php_tree_sitter(source)
        function = next(symbol for symbol in symbols if symbol.kind == "function")
        call = next(relation for relation in relations if relation.relation == "calls")
        self.assertEqual(function.qualified_name, "App\\run")
        self.assertEqual(call.metadata["qualified_name"], "Vendor\\Functions\\run")
        self.assertEqual(call.source_qualified_name, "App\\run")

    def test_dynamic_include_expressions_do_not_create_path_edges(self):
        dynamic = Node("include_expression")
        source = b"include $base . '/picked-by-accident.php'"
        dynamic.start_byte = 0
        dynamic.end_byte = len(source)
        self.assertEqual(_tree_sitter_static_include_target(source, dynamic), "")
        self.assertEqual(_php_includes_in_line("include $base . '/picked-by-accident.php';"), [])
        self.assertEqual(_php_includes_in_line("require_once __DIR__ . '/lib.php';")[0][1], "lib.php")

    def test_call_metadata_distinguishes_static_and_dynamic_dispatch(self):
        scope = Node("name", "Thing")
        method = Node("name", "make", start=7)
        static = Node("scoped_call_expression", "Thing::make", {"scope": scope, "name": method})
        static_metadata = _tree_sitter_php_call_metadata(b"Thing::make", static, "App", {"thing": "Vendor\\Thing"})
        self.assertEqual(static_metadata, {"dispatch_kind": "static", "qualified_name": "Vendor\\Thing::make"})

        receiver = Node("variable_name", "$service")
        member = Node("member_call_expression", "$service->run", {"object": receiver, "name": Node("name", "run")})
        member_metadata = _tree_sitter_php_call_metadata(b"$service->run", member, "App", {})
        self.assertEqual(member_metadata, {"dispatch_kind": "member", "receiver": "$service"})

    def test_tree_sitter_syntax_errors_are_not_reported_as_structural_success(self):
        payload = json.dumps({"symbols": [], "relations": [], "syntax_errors": True})
        with patch("init_agent.native_parser.importlib.util.find_spec", return_value=object()), \
             patch("init_agent.native_parser.run_bounded", return_value=SimpleNamespace(returncode=0, stdout=payload)), \
             patch("init_agent.native_parser._worker_command", return_value=["php-parser"]):
            with self.assertRaisesRegex(PHPStructuralSyntaxError, "syntax errors"):
                extract_php_isolated("<?php function broken( {")

    def test_malformed_structural_tree_falls_back_and_regex_edges_are_marked(self):
        with patch("init_agent.native_parser.extract_php_isolated", side_effect=PHPStructuralSyntaxError("bad tree")):
            symbols, relations = extract_symbols_and_relations(
                "<?php\nrequire_once 'lib.php';\nRoute::get('/home', [HomeController::class, 'show']);\n",
                "php",
            )
        self.assertTrue(any(item.relation == "require_once" and item.provenance == "regex_fallback" for item in relations))
        self.assertTrue(any(item.relation == "route_to_handler" and item.provenance == "regex_fallback" for item in relations))

    def test_capabilities_reuse_extraction_outcome_without_a_second_parser_run(self):
        with patch("init_agent.native_parser.extract_php_isolated", return_value=([], [])) as parser:
            symbols, relations = extract_symbols_and_relations("<?php function ready() {}", "php")
            capability = build_capabilities("php", "<?php function ready() {}", symbols, relations)
            partial = build_capabilities("php", "<?php function ready() {}", symbols, relations, ["record budget exceeded"])
        parser.assert_called_once()
        self.assertTrue(capability["structural"])
        self.assertFalse(partial["structural"])

    @unittest.skipUnless(
        importlib.util.find_spec("tree_sitter") and importlib.util.find_spec("tree_sitter_php"),
        "optional PHP tree-sitter dependencies are not installed",
    )
    def test_namespaced_symbols_and_alias_calls_keep_qualified_evidence(self):
        content = """<?php
namespace App\\Http;
use Vendor\\Service\\Runner as TaskRunner;
class Controller {
    public function run() { TaskRunner::execute(); $this->save(); }
}
"""
        symbols, relations = _extract_php_tree_sitter(content)
        controller = next(item for item in symbols if item.name == "Controller")
        method = next(item for item in symbols if item.name == "run")
        self.assertEqual(controller.qualified_name, "App\\Http\\Controller")
        self.assertEqual(method.container_name, "App\\Http\\Controller")
        static_call = next(item for item in relations if item.relation == "calls" and item.target == "execute")
        member_call = next(item for item in relations if item.relation == "calls" and item.target == "save")
        self.assertEqual(static_call.metadata["qualified_name"], "Vendor\\Service\\Runner::execute")
        self.assertEqual(member_call.metadata["dispatch_kind"], "member")
        self.assertEqual(member_call.source_qualified_name, "App\\Http\\Controller::run")

    @unittest.skipUnless(
        importlib.util.find_spec("tree_sitter") and importlib.util.find_spec("tree_sitter_php"),
        "optional PHP tree-sitter dependencies are not installed",
    )
    def test_real_php_evidence_trace_links_local_namespaced_call_and_rejects_dynamic_include(self):
        from init_agent import native_parser

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            (root / "main.php").write_text(
                "<?php\nnamespace App;\n"
                "function entryPoint() { return helper(); }\n"
                "function helper() { return 7; }\n"
                "function dynamicLoader($base) { require $base . '/picked.php'; }\n"
            )
            (root / "picked.php").write_text("<?php function decoy() {}\n")
            # The optional dependency is real; call the same structural extractor
            # directly because this macOS host cannot enforce the worker limits.
            with patch.object(native_parser, "extract_php_isolated", side_effect=_extract_php_tree_sitter):
                with GraphStore(root) as store:
                    store.initialize()
                    scan_project(root, store)
                traced = trace_evidence(root, [], anchor={"path": "main.php", "symbol": "App\\entryPoint"})
                with GraphStore(root) as store:
                    dynamic_edges = store.connection.execute(
                        "SELECT relation, target_id FROM relations r JOIN files f ON r.source_id=f.id "
                        "WHERE r.source_type='file' AND f.path='main.php' AND relation IN ('require','include')"
                    ).fetchall()
                    capability = store.connection.execute(
                        "SELECT metadata_json FROM file_analysis a JOIN files f ON a.file_id=f.id WHERE f.path='main.php'"
                    ).fetchone()[0]
            self.assertTrue(json.loads(capability)["structural"])
            self.assertEqual([tuple(row) for row in dynamic_edges], [])
            edge = traced["paths"][0]["resolved_edges"][0]
            self.assertEqual((edge["from"], edge["to"], edge["source_symbol"], edge["target_symbol"]),
                             ("main.php", "main.php", "App\\entryPoint", "App\\helper"))


if __name__ == "__main__":
    unittest.main()
