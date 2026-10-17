from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from init_agent import typescript_analyzer


class TypeScriptAnalyzerTests(unittest.TestCase):
    def test_unavailable_is_non_structural_when_node_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "main.ts").write_text("export {};\n")
            with patch.object(typescript_analyzer.shutil, "which", return_value=None):
                result = typescript_analyzer.analyze(Path(tmp), "main.ts")
        self.assertFalse(result["structural"])
        self.assertEqual(result["symbols"], [])
        self.assertIn("unavailable", result["gaps"][0])

    def test_rejects_path_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = typescript_analyzer.analyze(Path(tmp), "../elsewhere.ts")
        self.assertFalse(result["structural"])
        self.assertIn("root-relative", result["gaps"][0])

    def test_rejects_absolute_and_symlink_target_paths(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root, other = Path(tmp), Path(outside)
            source = root / "main.ts"
            source.write_text("export {};\n")
            absolute = typescript_analyzer.analyze(root, str(source))
            (other / "outside.ts").write_text("export {};\n")
            (root / "linked.ts").symlink_to(other / "outside.ts")
            linked = typescript_analyzer.analyze(root, "linked.ts")
        self.assertFalse(absolute["structural"])
        self.assertFalse(linked["structural"])
        self.assertIn("root-relative", absolute["gaps"][0])
        self.assertIn("symlink", linked["gaps"][0])

    @unittest.skipUnless(shutil.which("node") and typescript_analyzer.COMPILER.is_file(),
                         "optional pinned TypeScript compiler is not installed")
    def test_compiler_resolves_js_specifier_to_ts_and_finds_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base.json").write_text('{"compilerOptions":{"module":"ESNext","moduleResolution":"Bundler","baseUrl":".","paths":{"@helper":["helper.ts"]}}}')
            (root / "tsconfig.json").write_text('{"extends":"./base.json"}')
            (root / "helper.ts").write_text('export function greet(name: string) { return name; }\n')
            (root / "main.ts").write_text('import { greet } from "./helper.js";\nimport { greet as aliasGreet } from "@helper";\nimport * as helper from "./helper.js";\nexport function main() {\n  greet("x");\n  aliasGreet("y");\n  return helper.greet("z");\n}\n')
            result = typescript_analyzer.analyze(root, "main.ts")
        self.assertTrue(result["structural"], result["gaps"])
        self.assertTrue(any(s["name"] == "main" for s in result["symbols"]))
        self.assertFalse(any(s["name"] == "greet" for s in result["symbols"]))
        self.assertTrue(any(e["target_path"] == "helper.ts" for e in result["edges"]))
        self.assertEqual(sum(e["relation"] == "calls" and e["target_symbol"] == "greet" for e in result["edges"]), 3)
        self.assertTrue(all(e["source_symbol"] == "<module>" or e["source_symbol"] == "main" for e in result["edges"]))
        self.assertIn("base.json", result["dependencies"])
        self.assertTrue(all(e.get("source_sha256") and e.get("target_sha256") for e in result["edges"]))

    @unittest.skipUnless(shutil.which("node") and typescript_analyzer.COMPILER.is_file(),
                         "optional pinned TypeScript compiler is not installed")
    def test_only_stable_direct_functions_resolve_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "calls.ts").write_text(
                'function known() {}\n'
                'function overloaded(x: string): void;\n'
                'function overloaded(x: number): void;\n'
                'function overloaded(x: any) {}\n'
                'let callback = () => known();\n'
                'class Worker { work() {} }\n'
                'export function run(callback: () => void, worker: Worker) {\n'
                '  known();\n'
                '  callback();\n'
                '  worker.work();\n'
                '  overloaded("x");\n'
                '}\n'
            )
            result = typescript_analyzer.analyze(root, "calls.ts")
        self.assertTrue(result["structural"])
        self.assertEqual([edge["target_symbol"] for edge in result["edges"]], ["known", "known"])
        self.assertGreaterEqual(sum("unresolved dynamic" in gap for gap in result["gaps"]), 3)

    @unittest.skipUnless(shutil.which("node") and typescript_analyzer.COMPILER.is_file(),
                         "optional pinned TypeScript compiler is not installed")
    def test_unsupported_project_references_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tsconfig.json").write_text('{"files":["main.ts"],"references":[{"path":"./other"}]}')
            (root / "main.ts").write_text("export function main() {}\n")
            result = typescript_analyzer.analyze(root, "main.ts")
        self.assertFalse(result["structural"])
        self.assertIn("project references", result["gaps"][0])

    @unittest.skipUnless(shutil.which("node") and typescript_analyzer.COMPILER.is_file(),
                         "optional pinned TypeScript compiler is not installed")
    def test_imported_syntax_errors_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.ts").write_text("export function broken( {\n")
            (root / "main.ts").write_text('import { broken } from "./bad.js";\nbroken();\n')
            result = typescript_analyzer.analyze(root, "main.ts")
        self.assertFalse(result["structural"])
        self.assertIn("imported source", result["gaps"][0])

    @unittest.skipUnless(shutil.which("node") and typescript_analyzer.COMPILER.is_file(),
                         "optional pinned TypeScript compiler is not installed")
    def test_interface_dispatch_stays_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api.ts").write_text(
                'interface Api { run(): void }\n'
                'class ApiImpl implements Api { run() {} }\n'
                'export function dispatch(api: Api) { api.run(); }\n'
            )
            result = typescript_analyzer.analyze(root, "api.ts")
        self.assertTrue(result["structural"])
        self.assertFalse(any(edge["relation"] == "calls" for edge in result["edges"]))
        self.assertTrue(any("unresolved dynamic" in gap for gap in result["gaps"]))


if __name__ == "__main__":
    unittest.main()
