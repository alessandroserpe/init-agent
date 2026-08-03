"""Diagnose runtime-flow graph completeness on small framework-shaped fixtures."""

from __future__ import annotations

import argparse
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
from init_agent.reading_plan import build_reading_plan  # noqa: E402
from init_agent.relation_resolver import rebuild_resolved_relations  # noqa: E402
from init_agent.scanner import scan_project  # noqa: E402
from init_agent.utils import ensure_agent_dir  # noqa: E402


@dataclass(frozen=True)
class FlowCase:
    name: str
    description: str
    files: dict[str, str]
    expectations: list[dict[str, Any]]
    ranking_query: str = ""
    ranking_expected: tuple[str, ...] = ()
    ranking_allowed: tuple[str, ...] = ()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate extracted and resolved runtime-flow graph edges.")
    parser.add_argument("--strict", action="store_true", help="Fail when extraction/resolution guards are not met.")
    parser.add_argument("--min-resolution-rate", type=float, default=1.0)
    args = parser.parse_args(argv)
    results = [evaluate_case(case) for case in cases()]
    report = {
        "summary": summarize(results),
        "results": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RESULTS_DIR / "results.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict:
        summary = report["summary"]
        if summary["extraction_pass_rate"] < 1.0:
            return 1
        if summary["resolution_pass_rate"] < args.min_resolution_rate:
            return 1
        if summary["negative_passed"] != summary["negative_total"]:
            return 1
        if summary["ranking_regressions"]:
            return 1
        if summary["ranking_noise_regressions"]:
            return 1
        if summary["ranking_top3_hits"] != summary["ranking_case_count"]:
            return 1
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
            ranking = evaluate_ranking(root, store, case)
        expectations = [evaluate_expectation(graph, expectation) for expectation in case.expectations]
    present = [item for item in expectations if item["mode"] == "present"]
    limitations = [item for item in expectations if item["mode"] == "limitation"]
    negative = [item for item in expectations if item["mode"] == "absent"]
    return {
        "name": case.name,
        "description": case.description,
        "stats": stats,
        "present_passed": sum(1 for item in present if item["passed"]),
        "present_total": len(present),
        "limitation_confirmed": sum(1 for item in limitations if item["passed"]),
        "limitation_total": len(limitations),
        "negative_passed": sum(1 for item in negative if item["passed"]),
        "negative_total": len(negative),
        "ranking": ranking,
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


def evaluate_ranking(root: Path, store: GraphStore, case: FlowCase) -> dict[str, Any] | None:
    if not case.ranking_query or not case.ranking_expected:
        return None
    assisted = build_reading_plan(root, case.ranking_query, limit=10, read_budget=3)
    store.connection.execute(
        "DELETE FROM relations WHERE target_type IN ('resolved_file', 'resolved_symbol')"
    )
    store.connection.commit()
    baseline = build_reading_plan(root, case.ranking_query, limit=10, read_budget=3)
    rebuild_resolved_relations(store)
    store.connection.commit()
    assisted_rank = _first_expected_rank(assisted.get("plan_items", []), case.ranking_expected)
    baseline_rank = _first_expected_rank(baseline.get("plan_items", []), case.ranking_expected)
    baseline_top5 = [str(item["path"]) for item in baseline.get("plan_items", [])[:5]]
    assisted_top5 = [str(item["path"]) for item in assisted.get("plan_items", [])[:5]]
    allowed = set(case.ranking_allowed)
    baseline_noise = len([path for path in baseline_top5 if path not in allowed]) if allowed else None
    resolved_noise = len([path for path in assisted_top5 if path not in allowed]) if allowed else None
    return {
        "query": case.ranking_query,
        "expected": list(case.ranking_expected),
        "baseline_rank": baseline_rank,
        "resolved_rank": assisted_rank,
        "rank_lift": (baseline_rank or 11) - (assisted_rank or 11),
        "top3_hit": bool(assisted_rank and assisted_rank <= 3),
        "regressed": bool(baseline_rank and assisted_rank and assisted_rank > baseline_rank),
        "baseline_top5": baseline_top5,
        "resolved_top5": assisted_top5,
        "baseline_noise": baseline_noise,
        "resolved_noise": resolved_noise,
        "noise_reduction": (baseline_noise - resolved_noise) if baseline_noise is not None and resolved_noise is not None else None,
    }


def _first_expected_rank(items: list[dict[str, Any]], expected: tuple[str, ...]) -> int | None:
    ranks = [int(item["rank"]) for item in items if str(item.get("path") or "") in expected]
    return min(ranks) if ranks else None


def evaluate_expectation(graph: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    mode = expectation.get("mode", "present")
    kind = expectation["kind"]
    resolved: bool | None = None
    if kind == "file_relation":
        extracted = has_file_relation(graph, expectation["source"], expectation["relation"])
        resolved = has_resolved_file_relation(graph, expectation["source"], expectation["relation"], expectation["target"])
    elif kind == "import":
        extracted = has_import(graph, expectation["source"], expectation["module"])
        if expectation.get("target"):
            resolved = has_resolved_file_relation(graph, expectation["source"], "imports", expectation["target"])
    elif kind == "call":
        extracted = has_call(graph, expectation["source"], expectation["symbol"])
        if expectation.get("target"):
            resolved = has_resolved_file_relation(graph, expectation["source"], "calls", expectation["target"])
    elif kind == "route":
        extracted = has_route(graph, expectation["source"], expectation["route"], expectation.get("handler"))
        if expectation.get("target"):
            resolved = has_resolved_file_relation(graph, expectation["source"], "route_to_handler", expectation["target"])
    elif kind == "symbol":
        extracted = has_symbol(graph, expectation["source"], expectation["symbol"], expectation.get("symbol_kind"))
    elif kind == "sql_table":
        extracted = has_sql_table(graph, expectation["source"], expectation["table"])
    elif kind == "template":
        extracted = has_template(graph, expectation["source"], expectation["template"])
        if expectation.get("target"):
            resolved = has_resolved_file_relation(graph, expectation["source"], "renders_template", expectation["target"])
    elif kind == "symbol_relation":
        extracted = has_scoped_symbol_relation(
            graph,
            expectation["source"],
            expectation["source_symbol"],
            expectation["relation"],
            expectation["target_symbol"],
        )
        resolved = has_resolved_symbol_relation(
            graph,
            expectation["source"],
            expectation["source_symbol"],
            expectation["relation"],
            expectation["target"],
            expectation["target_symbol"],
        )
    elif kind == "unresolved_call":
        extracted = has_call(graph, expectation["source"], expectation["symbol"])
        resolved = not has_any_resolved_relation(graph, expectation["source"], "calls", expectation.get("target"))
    elif kind == "unsupported":
        extracted = not unsupported_feature_present(graph, expectation)
    else:
        raise ValueError(f"unknown expectation kind: {kind}")
    passed = bool(extracted and resolved is not False)
    return {
        **expectation,
        "mode": mode,
        "extracted": bool(extracted),
        "resolved": resolved,
        "passed": bool(passed),
    }


def has_file_relation(graph: dict[str, Any], source: str, relation: str) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    for item in graph["relations"]:
        if int(item["source_id"]) != source_id or item["relation"] != relation or item["target_type"] != "file":
            continue
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
        return True
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
    return True


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
    return True


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
    return True


def has_resolved_file_relation(graph: dict[str, Any], source: str, relation: str, target: str) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    return any(
        int(item["source_id"]) == source_id
        and item["relation"] == relation
        and item["target_type"] == "resolved_file"
        and item["target_id"] == target
        for item in graph["relations"]
    )


def has_scoped_symbol_relation(
    graph: dict[str, Any],
    source: str,
    source_symbol: str,
    relation: str,
    target_symbol: str,
) -> bool:
    source_file_id = graph["path_to_id"].get(source)
    if source_file_id is None:
        return False
    source_symbol_ids = {
        int(item["id"])
        for item in graph["symbols"]
        if int(item["file_id"]) == source_file_id and item["qualified_name"] == source_symbol
    }
    return any(
        item.get("context_symbol_id") in source_symbol_ids
        and item["relation"] == relation
        and item["target_type"] == "symbol_name"
        and item["target_id"] == target_symbol
        for item in graph["relations"]
    )


def has_resolved_symbol_relation(
    graph: dict[str, Any],
    source: str,
    source_symbol: str,
    relation: str,
    target: str,
    target_symbol: str,
) -> bool:
    source_file_id = graph["path_to_id"].get(source)
    target_file_id = graph["path_to_id"].get(target)
    if source_file_id is None or target_file_id is None:
        return False
    source_symbol_ids = {
        int(item["id"])
        for item in graph["symbols"]
        if int(item["file_id"]) == source_file_id and item["qualified_name"] == source_symbol
    }
    target_symbol_ids = {
        str(item["id"])
        for item in graph["symbols"]
        if int(item["file_id"]) == target_file_id and item["qualified_name"] == target_symbol
    }
    return any(
        item["source_type"] == "symbol"
        and int(item["source_id"]) in source_symbol_ids
        and item["relation"] == relation
        and item["target_type"] == "resolved_symbol"
        and item["target_id"] in target_symbol_ids
        for item in graph["relations"]
    )


def has_any_resolved_relation(graph: dict[str, Any], source: str, relation: str, target: str | None = None) -> bool:
    source_id = graph["path_to_id"].get(source)
    if source_id is None:
        return False
    return any(
        int(item["source_id"]) == source_id
        and item["relation"] == relation
        and item["target_type"] == "resolved_file"
        and (target is None or item["target_id"] == target)
        for item in graph["relations"]
    )


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


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    present_passed = sum(item["present_passed"] for item in results)
    present_total = sum(item["present_total"] for item in results)
    limitations = sum(item["limitation_total"] for item in results)
    expectations = [
        expectation
        for result in results
        for expectation in result["expectations"]
        if expectation["mode"] == "present"
    ]
    extraction_total = len(expectations)
    extraction_passed = sum(1 for item in expectations if item["extracted"])
    resolution_items = [item for item in expectations if item["resolved"] is not None]
    resolution_passed = sum(1 for item in resolution_items if item["resolved"])
    negative_total = sum(item["negative_total"] for item in results)
    negative_passed = sum(item["negative_passed"] for item in results)
    ranking = [item["ranking"] for item in results if item.get("ranking")]
    noise_cases = [item for item in ranking if item.get("noise_reduction") is not None]
    return {
        "case_count": len(results),
        "present_passed": present_passed,
        "present_total": present_total,
        "present_pass_rate": round(present_passed / present_total, 3) if present_total else None,
        "limitation_count": limitations,
        "extraction_passed": extraction_passed,
        "extraction_total": extraction_total,
        "extraction_pass_rate": round(extraction_passed / extraction_total, 3) if extraction_total else None,
        "resolution_passed": resolution_passed,
        "resolution_total": len(resolution_items),
        "resolution_pass_rate": round(resolution_passed / len(resolution_items), 3) if resolution_items else None,
        "negative_passed": negative_passed,
        "negative_total": negative_total,
        "ranking_case_count": len(ranking),
        "ranking_top3_hits": sum(1 for item in ranking if item["top3_hit"]),
        "ranking_improved": sum(1 for item in ranking if item["rank_lift"] > 0),
        "ranking_unchanged": sum(1 for item in ranking if item["rank_lift"] == 0),
        "ranking_regressions": sum(1 for item in ranking if item["regressed"]),
        "ranking_noise_cases": len(noise_cases),
        "ranking_noise_reduction": sum(int(item["noise_reduction"]) for item in noise_cases),
        "ranking_noise_regressions": sum(1 for item in noise_cases if int(item["noise_reduction"]) < 0),
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
        f"- Extraction: {report['summary']['extraction_passed']}/{report['summary']['extraction_total']}",
        f"- Resolution: {report['summary']['resolution_passed']}/{report['summary']['resolution_total']}",
        f"- Resolution pass rate: {report['summary']['resolution_pass_rate']}",
        f"- Negative ambiguity guards: {report['summary']['negative_passed']}/{report['summary']['negative_total']}",
        f"- Ranking Top-3 with resolved graph: {report['summary']['ranking_top3_hits']}/{report['summary']['ranking_case_count']}",
        f"- Ranking improved/unchanged/regressed: {report['summary']['ranking_improved']}/{report['summary']['ranking_unchanged']}/{report['summary']['ranking_regressions']}",
        f"- Ranking noise reduction: {report['summary']['ranking_noise_reduction']} across {report['summary']['ranking_noise_cases']} scoped cases",
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
                "| Mode | Status | Extracted | Resolved | Kind | Description |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for expectation in result["expectations"]:
            status = "PASS" if expectation["passed"] else "FAIL"
            resolved = "n/a" if expectation["resolved"] is None else ("yes" if expectation["resolved"] else "no")
            lines.append(
                f"| {expectation['mode']} | {status} | {'yes' if expectation['extracted'] else 'no'} | "
                f"{resolved} | {expectation['kind']} | {expectation['description']} |"
            )
        if result.get("ranking"):
            ranking = result["ranking"]
            lines.append("")
            lines.append(
                f"Ranking: baseline={ranking['baseline_rank']} resolved={ranking['resolved_rank']} "
                f"lift={ranking['rank_lift']} query=`{ranking['query']}`"
            )
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
                    require_once __DIR__ . '/db.php';
                    require_once __DIR__ . '/functions.php';
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
                present(
                    "symbol_relation",
                    "renderPageTitle symbol resolves its call to fetchPageTitle",
                    source="include/functions.php",
                    source_symbol="renderPageTitle",
                    relation="calls",
                    target="include/functions.php",
                    target_symbol="fetchPageTitle",
                ),
                present("sql_table", "functions.php records pages table usage", source="include/functions.php", table="pages"),
            ],
            ranking_query="render page title from request",
            ranking_expected=("include/page.php", "include/functions.php"),
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
                present(
                    "symbol_relation",
                    "create_item symbol resolves its repository call",
                    source="src/shop/services/items.py",
                    source_symbol="create_item",
                    relation="calls",
                    target="src/shop/repositories/items.py",
                    target_symbol="save_item",
                ),
                present("import", "repository imports model module", source="src/shop/repositories/items.py", module="shop.models", target="src/shop/models.py"),
            ],
            ranking_query="create item route service repository",
            ranking_expected=("src/shop/routers/items.py", "src/shop/services/items.py", "src/shop/repositories/items.py"),
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
            ranking_query="render blog detail template for post",
            ranking_expected=("blog/views.py", "blog/templates/blog/detail.html"),
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
                present("import", "main.tsx resolves local App import", source="src/main.tsx", module="./App", target="src/App.tsx"),
                present("import", "App.tsx resolves local TaskList import", source="src/App.tsx", module="./components/TaskList", target="src/components/TaskList.tsx"),
                present("import", "TaskList.tsx resolves local API import", source="src/components/TaskList.tsx", module="../api/tasks", target="src/api/tasks.ts"),
                present("call", "TaskList calls listTasks", source="src/components/TaskList.tsx", symbol="listTasks", target="src/api/tasks.ts"),
            ],
            ranking_query="task list loads api tasks",
            ranking_expected=("src/components/TaskList.tsx", "src/api/tasks.ts"),
        ),
        FlowCase(
            name="python_inheritance_flow",
            description="Python imported base class and scoped method call resolve to concrete symbols.",
            files={
                "app/contracts.py": """
                    class ProtocolRoot:
                        pass
                """,
                "app/service.py": """
                    def save_request():
                        return True
                """,
                "app/handler.py": """
                    from app.contracts import ProtocolRoot
                    from app.service import save_request

                    class RequestHandler(ProtocolRoot):
                        def dispatch(self):
                            return save_request()
                """,
            },
            expectations=[
                present(
                    "symbol_relation",
                    "RequestHandler inherits imported ProtocolRoot",
                    source="app/handler.py",
                    source_symbol="RequestHandler",
                    relation="inherits",
                    target="app/contracts.py",
                    target_symbol="ProtocolRoot",
                ),
                present(
                    "symbol_relation",
                    "dispatch resolves save_request to its imported function",
                    source="app/handler.py",
                    source_symbol="RequestHandler.dispatch",
                    relation="calls",
                    target="app/service.py",
                    target_symbol="save_request",
                ),
            ],
            ranking_query="request handler dispatch",
            ranking_expected=("app/contracts.py",),
            ranking_allowed=("app/handler.py", "app/contracts.py", "app/service.py"),
        ),
        FlowCase(
            name="php_inheritance_flow",
            description="PHP class inheritance and a scoped method call resolve inside an include component.",
            files={
                "base.php": """
                    <?php class BaseController {}
                """,
                "render.php": """
                    <?php function renderPage() { return true; }
                """,
                "admin.php": """
                    <?php
                    require_once 'base.php';
                    require_once 'render.php';
                    class AdminController extends BaseController {
                        public function show() { return renderPage(); }
                    }
                """,
            },
            expectations=[
                present(
                    "symbol_relation",
                    "AdminController resolves its BaseController inheritance",
                    source="admin.php",
                    source_symbol="AdminController",
                    relation="inherits",
                    target="base.php",
                    target_symbol="BaseController",
                ),
                present(
                    "symbol_relation",
                    "show resolves renderPage through the include component",
                    source="admin.php",
                    source_symbol="AdminController::show",
                    relation="calls",
                    target="render.php",
                    target_symbol="renderPage",
                ),
            ],
            ranking_query="admin controller base render page",
            ranking_expected=("admin.php", "base.php", "render.php"),
        ),
        FlowCase(
            name="scoped_call_ranking",
            description="Imported call bindings should avoid unrelated duplicate definitions during trace ranking.",
            files={
                "main.py": """
                    from app.runner import run

                    if __name__ == '__main__':
                        run()
                """,
                "app/runner.py": """
                    from app.service import process

                    def run():
                        return process()
                """,
                "app/service.py": """
                    def process():
                        return 'ok'
                """,
                "noise/legacy.py": """
                    def process():
                        return 'legacy'
                """,
                "noise/example.py": """
                    def process():
                        return 'example'
                """,
            },
            expectations=[
                present("call", "main resolves run to app runner", source="main.py", symbol="run", target="app/runner.py"),
                present("call", "runner resolves process to app service", source="app/runner.py", symbol="process", target="app/service.py"),
            ],
            ranking_query="startup request lifecycle",
            ranking_expected=("app/runner.py", "app/service.py"),
            ranking_allowed=("main.py", "app/runner.py", "app/service.py"),
        ),
        FlowCase(
            name="hidden_test_symbol_ranking",
            description="A symptom query matching a test method should promote its resolved production call without broad file expansion.",
            files={
                "app/loader.py": """
                    def render_to_string():
                        return 'ok'
                """,
                "app/javascript.py": """
                    def configure_javascript():
                        return True
                """,
                "app/escaping.py": """
                    def escaping_helper():
                        return True
                """,
                "tests/test_templates.py": """
                    from app.loader import render_to_string

                    def test_javascript_escaping_corrupts_inline_output():
                        return render_to_string()
                """,
            },
            expectations=[
                present(
                    "symbol_relation",
                    "matching test method resolves its call to the production loader",
                    source="tests/test_templates.py",
                    source_symbol="test_javascript_escaping_corrupts_inline_output",
                    relation="calls",
                    target="app/loader.py",
                    target_symbol="render_to_string",
                ),
            ],
            ranking_query="javascript escaping corrupts inline output",
            ranking_expected=("app/loader.py",),
            ranking_allowed=(
                "app/javascript.py",
                "app/escaping.py",
                "tests/test_templates.py",
                "app/loader.py",
            ),
        ),
        FlowCase(
            name="ambiguous_symbol_guard",
            description="An unscoped duplicate function name must remain unresolved instead of creating noisy file edges.",
            files={
                "app.py": """
                    def run(value):
                        return save(value)
                """,
                "left.py": """
                    def save(value):
                        return value
                """,
                "right.py": """
                    def save(value):
                        return value
                """,
            },
            expectations=[
                absent(
                    "unresolved_call",
                    "ambiguous save call is extracted but not linked to either definition",
                    source="app.py",
                    symbol="save",
                ),
            ],
        ),
    ]


def present(kind: str, description: str, **kwargs: Any) -> dict[str, Any]:
    return {"mode": "present", "kind": kind, "description": description, **kwargs}


def limitation(kind: str, description: str, **kwargs: Any) -> dict[str, Any]:
    return {"mode": "limitation", "kind": kind, "description": description, **kwargs}


def absent(kind: str, description: str, **kwargs: Any) -> dict[str, Any]:
    return {"mode": "absent", "kind": kind, "description": description, **kwargs}


if __name__ == "__main__":
    raise SystemExit(main())
