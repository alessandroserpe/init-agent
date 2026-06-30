"""Diagnose runtime-flow graph completeness on small framework-shaped fixtures."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "experiments" / "flow-graph" / "results"

import sys

sys.path.insert(0, str(ROOT))

from init_agent.graph_store import GraphStore  # noqa: E402
from init_agent.scanner import scan_project  # noqa: E402
from init_agent.utils import ensure_agent_dir  # noqa: E402


@dataclass(frozen=True)
class FlowCase:
    name: str
    description: str
    files: dict[str, str]
    expectations: list[dict[str, Any]]


def main() -> int:
    results = [evaluate_case(case) for case in cases()]
    report = {
        "summary": summarize(results),
        "results": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RESULTS_DIR / "results.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def evaluate_case(case: FlowCase) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"init-agent-flow-{case.name}-") as tmp:
        root = Path(tmp)
        write_fixture(root, case.files)
        ensure_agent_dir(root)
        with GraphStore(root) as store:
            store.initialize()
            stats = scan_project(root, store)
            graph = load_graph(store.connection)
        expectations = [evaluate_expectation(graph, expectation) for expectation in case.expectations]
    present = [item for item in expectations if item["mode"] == "present"]
    limitations = [item for item in expectations if item["mode"] == "limitation"]
    return {
        "name": case.name,
        "description": case.description,
        "stats": stats,
        "present_passed": sum(1 for item in present if item["passed"]),
        "present_total": len(present),
        "limitation_confirmed": sum(1 for item in limitations if item["passed"]),
        "limitation_total": len(limitations),
        "expectations": expectations,
    }


def write_fixture(root: Path, files: dict[str, str]) -> None:
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def load_graph(connection: sqlite3.Connection) -> dict[str, Any]:
    files = {int(row["id"]): dict(row) for row in connection.execute("SELECT * FROM files")}
    path_to_id = {str(row["path"]): file_id for file_id, row in files.items()}
    symbols = [dict(row) for row in connection.execute("SELECT * FROM symbols")]
    relations = [dict(row) for row in connection.execute("SELECT * FROM relations")]
    return {
        "files": files,
        "path_to_id": path_to_id,
        "symbols": symbols,
        "relations": relations,
    }


def evaluate_expectation(graph: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    mode = expectation.get("mode", "present")
    kind = expectation["kind"]
    if kind == "file_relation":
        passed = has_file_relation(graph, expectation["source"], expectation["relation"], expectation["target"])
    elif kind == "import":
        passed = has_import(graph, expectation["source"], expectation["module"], expectation.get("target"))
    elif kind == "call":
        passed = has_call(graph, expectation["source"], expectation["symbol"], expectation.get("target"))
    elif kind == "route":
        passed = has_route(graph, expectation["source"], expectation["route"], expectation.get("handler"), expectation.get("target"))
    elif kind == "symbol":
        passed = has_symbol(graph, expectation["source"], expectation["symbol"], expectation.get("symbol_kind"))
    elif kind == "sql_table":
        passed = has_sql_table(graph, expectation["source"], expectation["table"])
    elif kind == "template":
        passed = has_template(graph, expectation["source"], expectation["template"], expectation.get("target"))
    elif kind == "unsupported":
        passed = not unsupported_feature_present(graph, expectation)
    else:
        raise ValueError(f"unknown expectation kind: {kind}")
    return {
        **expectation,
        "mode": mode,
        "passed": bool(passed),
    }


def has_file_relation(graph: dict[str, Any], source: str, relation: str, target: str) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    for item in graph["relations"]:
        if int(item["source_id"]) != source_id or item["relation"] != relation or item["target_type"] != "file":
            continue
        if resolve_file_target(source, str(item["target_id"]), graph["path_to_id"]) == target:
            return True
    return False


def has_import(graph: dict[str, Any], source: str, module: str, target: str | None = None) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    for item in graph["relations"]:
        if int(item["source_id"]) != source_id or item["relation"] != "imports" or item["target_type"] != "module":
            continue
        if item["target_id"] != module:
            continue
        if not target:
            return True
        return resolve_module_target(module, graph["path_to_id"]) == target
    return False


def has_call(graph: dict[str, Any], source: str, symbol: str, target: str | None = None) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    found_call = any(
        int(item["source_id"]) == source_id
        and item["relation"] == "calls"
        and item["target_type"] == "symbol_name"
        and item["target_id"] == symbol
        for item in graph["relations"]
    )
    if not found_call:
        return False
    if not target:
        return True
    return any(item["name"] == symbol and graph["files"][int(item["file_id"])]["path"] == target for item in graph["symbols"])


def has_route(graph: dict[str, Any], source: str, route: str, handler: str | None = None, target: str | None = None) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    route_found = any(
        int(item["file_id"]) == source_id and item["kind"] == "route" and item["name"] == route
        for item in graph["symbols"]
    )
    if not route_found:
        return False
    if not handler:
        return True
    handler_relation = any(
        int(item["source_id"]) == source_id
        and item["relation"] == "route_to_handler"
        and item["target_type"] == "symbol_name"
        and item["target_id"] == handler
        for item in graph["relations"]
    )
    if not handler_relation:
        return False
    if not target:
        return True
    return any(item["name"] == handler and graph["files"][int(item["file_id"])]["path"] == target for item in graph["symbols"])


def has_symbol(graph: dict[str, Any], source: str, symbol: str, symbol_kind: str | None = None) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    return any(
        int(item["file_id"]) == source_id
        and item["name"] == symbol
        and (symbol_kind is None or item["kind"] == symbol_kind)
        for item in graph["symbols"]
    )


def has_sql_table(graph: dict[str, Any], source: str, table: str) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    return any(
        int(item["source_id"]) == source_id
        and item["relation"] == "uses_table"
        and item["target_type"] == "sql_table"
        and item["target_id"] == table
        for item in graph["relations"]
    )


def has_template(graph: dict[str, Any], source: str, template: str, target: str | None = None) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    found = any(
        int(item["source_id"]) == source_id
        and item["relation"] == "renders_template"
        and item["target_type"] == "template"
        and item["target_id"] == template
        for item in graph["relations"]
    )
    if not found:
        return False
    if not target:
        return True
    return resolve_template_target(template, graph["path_to_id"]) == target


def unsupported_feature_present(graph: dict[str, Any], expectation: dict[str, Any]) -> bool:
    feature = expectation["feature"]
    if feature == "sql_table_usage":
        table = expectation["table"]
        return any(item["target_type"] == "sql_table" and item["target_id"] == table for item in graph["relations"])
    if feature == "template_render_target":
        target = expectation["target"]
        return any(item["target_type"] == "template" and item["target_id"] == target for item in graph["relations"])
    if feature == "relative_import_resolution":
        target = expectation["target"]
        return any(item["target_type"] == "file" and item["target_id"] == target for item in graph["relations"])
    raise ValueError(f"unknown unsupported feature: {feature}")


def resolve_file_target(source: str, raw_target: str, path_to_id: dict[str, int]) -> str | None:
    normalized = raw_target.lstrip("/")
    source_dir = Path(source).parent
    candidates = [
        normalized,
        (source_dir / normalized).as_posix(),
        (source_dir / Path(normalized).name).as_posix(),
    ]
    for candidate in candidates:
        clean = Path(candidate).as_posix().lstrip("./")
        if clean in path_to_id:
            return clean
    return None


def resolve_module_target(module: str, path_to_id: dict[str, int]) -> str | None:
    base = module.replace(".", "/")
    for candidate in (f"{base}.py", f"{base}/__init__.py", f"src/{base}.py", f"src/{base}/__init__.py"):
        if candidate in path_to_id:
            return candidate
    return None


def resolve_template_target(template: str, path_to_id: dict[str, int]) -> str | None:
    candidates = [template, f"templates/{template}"]
    if "/" in template:
        app, rest = template.split("/", 1)
        candidates.append(f"{app}/templates/{app}/{rest}")
    for candidate in candidates:
        if candidate in path_to_id:
            return candidate
    for path in path_to_id:
        if path.endswith(f"/templates/{template}"):
            return path
    return None


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    present_passed = sum(item["present_passed"] for item in results)
    present_total = sum(item["present_total"] for item in results)
    limitations = sum(item["limitation_total"] for item in results)
    return {
        "case_count": len(results),
        "present_passed": present_passed,
        "present_total": present_total,
        "present_pass_rate": round(present_passed / present_total, 3) if present_total else None,
        "limitation_count": limitations,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Flow Graph Results",
        "",
        "This is a graph-completeness diagnostic, not an agent benchmark.",
        "",
        "## Summary",
        "",
        f"- Cases: {report['summary']['case_count']}",
        f"- Present expectations: {report['summary']['present_passed']}/{report['summary']['present_total']}",
        f"- Pass rate: {report['summary']['present_pass_rate']}",
        f"- Documented limitations: {report['summary']['limitation_count']}",
        "",
        "## Cases",
        "",
    ]
    for result in report["results"]:
        lines.extend(
            [
                f"### {result['name']}",
                "",
                result["description"],
                "",
                f"- Indexed files: {result['stats']['files']}",
                f"- Symbols: {result['stats']['symbols']}",
                f"- Relations: {result['stats']['relations']}",
                f"- Present expectations: {result['present_passed']}/{result['present_total']}",
                "",
                "| Mode | Status | Kind | Description |",
                "| --- | --- | --- | --- |",
            ]
        )
        for expectation in result["expectations"]:
            status = "PASS" if expectation["passed"] else "FAIL"
            lines.append(f"| {expectation['mode']} | {status} | {expectation['kind']} | {expectation['description']} |")
        lines.append("")
    return "\n".join(lines)


def cases() -> list[FlowCase]:
    return [
        FlowCase(
            name="php_legacy_flow",
            description="Procedural PHP entrypoint with bootstrap includes, DB helper and render functions.",
            files={
                "index.php": """
                    <?php
                    require_once 'include/bootstrap.php';
                    include 'include/page.php';
                    ?>
                """,
                "include/bootstrap.php": """
                    <?php
                    require_once 'db.php';
                    require_once 'functions.php';
                    ?>
                """,
                "include/db.php": """
                    <?php
                    $db = new mysqli('localhost', 'user', 'pass', 'app');
                    ?>
                """,
                "include/functions.php": """
                    <?php
                    function fetchPageTitle($slug) {
                        global $db;
                        $result = mysqli_query($db, "SELECT title FROM pages WHERE slug = '" . $slug . "'");
                        return 'Dashboard';
                    }
                    function renderPageTitle($slug) {
                        return '<h1>' . fetchPageTitle($slug) . '</h1>';
                    }
                    ?>
                """,
                "include/page.php": """
                    <?php
                    $slug = $_GET['page'] ?? 'home';
                    echo renderPageTitle($slug);
                    ?>
                """,
            },
            expectations=[
                present("file_relation", "index.php includes bootstrap.php", source="index.php", relation="require_once", target="include/bootstrap.php"),
                present("file_relation", "index.php includes page.php", source="index.php", relation="include", target="include/page.php"),
                present("file_relation", "bootstrap.php requires db.php", source="include/bootstrap.php", relation="require_once", target="include/db.php"),
                present("file_relation", "bootstrap.php requires functions.php", source="include/bootstrap.php", relation="require_once", target="include/functions.php"),
                present("call", "page.php calls renderPageTitle defined in functions.php", source="include/page.php", symbol="renderPageTitle", target="include/functions.php"),
                present("call", "renderPageTitle calls fetchPageTitle in same file", source="include/functions.php", symbol="fetchPageTitle", target="include/functions.php"),
                present("sql_table", "functions.php records pages table usage", source="include/functions.php", table="pages"),
            ],
        ),
        FlowCase(
            name="fastapi_flow",
            description="FastAPI-like route module, service, repository and model flow.",
            files={
                "src/shop/app.py": """
                    from fastapi import FastAPI
                    from shop.routers.items import router as item_router

                    app = FastAPI()
                    app.include_router(item_router)
                """,
                "src/shop/routers/items.py": """
                    from fastapi import APIRouter
                    from shop.schemas import ItemIn
                    from shop.services.items import create_item

                    router = APIRouter()

                    @router.post('/items')
                    def create_item_endpoint(payload: ItemIn):
                        return create_item(payload)
                """,
                "src/shop/services/items.py": """
                    from shop.repositories.items import save_item

                    def create_item(payload):
                        return save_item(payload)
                """,
                "src/shop/repositories/items.py": """
                    from shop.models import Item

                    def save_item(payload):
                        item = Item(name=payload.name)
                        return item
                """,
                "src/shop/models.py": """
                    class Item:
                        def __init__(self, name):
                            self.name = name
                """,
                "src/shop/schemas.py": """
                    class ItemIn:
                        name: str
                """,
            },
            expectations=[
                present("import", "app.py imports item router module", source="src/shop/app.py", module="shop.routers.items", target="src/shop/routers/items.py"),
                present("route", "router module records POST /items and handler", source="src/shop/routers/items.py", route="/items", handler="create_item_endpoint", target="src/shop/routers/items.py"),
                present("call", "route handler calls create_item service", source="src/shop/routers/items.py", symbol="create_item", target="src/shop/services/items.py"),
                present("import", "service imports repository module", source="src/shop/services/items.py", module="shop.repositories.items", target="src/shop/repositories/items.py"),
                present("call", "service calls save_item repository function", source="src/shop/services/items.py", symbol="save_item", target="src/shop/repositories/items.py"),
                present("import", "repository imports model module", source="src/shop/repositories/items.py", module="shop.models", target="src/shop/models.py"),
            ],
        ),
        FlowCase(
            name="django_flow",
            description="Django-like URL config, view, model and template render flow.",
            files={
                "project/urls.py": """
                    from django.urls import path
                    from blog import views

                    urlpatterns = [
                        path('posts/<int:pk>/', views.detail, name='detail'),
                    ]
                """,
                "blog/views.py": """
                    from django.shortcuts import render
                    from .models import Post

                    def detail(request, pk):
                        post = Post.objects.get(pk=pk)
                        return render(request, 'blog/detail.html', {'post': post})
                """,
                "blog/models.py": """
                    class Post:
                        pass
                """,
                "blog/templates/blog/detail.html": """
                    <h1>{{ post.title }}</h1>
                """,
            },
            expectations=[
                present("route", "urls.py records route and view handler", source="project/urls.py", route="/posts/<int:pk>", handler="detail", target="blog/views.py"),
                present("call", "view calls render", source="blog/views.py", symbol="render"),
                present("import", "relative import from .models resolves to blog/models.py", source="blog/views.py", module="blog.models", target="blog/models.py"),
                present("template", "view render target resolves to template file", source="blog/views.py", template="blog/detail.html", target="blog/templates/blog/detail.html"),
            ],
        ),
        FlowCase(
            name="react_flow",
            description="React/Vite-like main file, app component, child component and API client.",
            files={
                "src/main.tsx": """
                    import { createRoot } from 'react-dom/client';
                    import { App } from './App';

                    createRoot(document.getElementById('root')!).render(<App />);
                """,
                "src/App.tsx": """
                    import { TaskList } from './components/TaskList';

                    export function App() {
                      return <TaskList />;
                    }
                """,
                "src/components/TaskList.tsx": """
                    import { listTasks } from '../api/tasks';

                    export function TaskList() {
                      listTasks();
                      return <h1>Tasks</h1>;
                    }
                """,
                "src/api/tasks.ts": """
                    export function listTasks() {
                      return fetch('/api/tasks');
                    }
                """,
            },
            expectations=[
                present("import", "main.tsx records local App import", source="src/main.tsx", module="./App"),
                present("import", "App.tsx records local TaskList import", source="src/App.tsx", module="./components/TaskList"),
                present("import", "TaskList.tsx records local API import", source="src/components/TaskList.tsx", module="../api/tasks"),
                present("call", "TaskList calls listTasks", source="src/components/TaskList.tsx", symbol="listTasks", target="src/api/tasks.ts"),
                limitation("unsupported", "relative TS imports are not resolved to file nodes", feature="relative_import_resolution", target="src/App.tsx"),
            ],
        ),
    ]


def present(kind: str, description: str, **kwargs: Any) -> dict[str, Any]:
    return {"mode": "present", "kind": kind, "description": description, **kwargs}


def limitation(kind: str, description: str, **kwargs: Any) -> dict[str, Any]:
    return {"mode": "limitation", "kind": kind, "description": description, **kwargs}


if __name__ == "__main__":
    raise SystemExit(main())
