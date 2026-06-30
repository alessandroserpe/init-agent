"""Evaluate init-agent context results against local benchmark cases."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "experiments" / "cases.json"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = load_cases(args.case)
    results = []
    skipped = []
    rebuilt_repos: set[Path] = set()
    for case in cases:
        repo = resolve_case_repo(case)
        if repo is None:
            skipped.append({"name": case["name"], "reason": f"missing repo: {Path(case['repo'])}"})
            continue
        if repo != Path(case["repo"]):
            case = {**case, "repo": str(repo)}
        if args.rebuild_index and repo not in rebuilt_repos:
            _rebuild_index(repo)
            rebuilt_repos.add(repo)
        try:
            results.append(evaluate_case(case, measure_manual_scan=args.measure_manual_scan))
        except subprocess.CalledProcessError as exc:
            results.append(
                {
                    "name": case["name"],
                    "status": "error",
                    "elapsed_seconds": None,
                    "error": exc.stderr.strip() or str(exc),
                }
            )

    summary = summarize(results)
    strict_failures = strict_failures_for(summary, args) if args.strict else []
    report = {"summary": summary, "results": results, "skipped": skipped}
    if args.strict:
        report["strict"] = {
            "ok": not strict_failures,
            "failures": strict_failures,
            "min_top3_rate": args.min_top3_rate,
            "min_top5_rate": args.min_top5_rate,
            "max_noise": args.max_noise,
        }
    write_report_outputs(report, args)
    print(json.dumps(report, indent=2, sort_keys=True))
    if any(item.get("status") == "error" for item in results):
        return 1
    if strict_failures:
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate init-agent against local benchmark repositories.")
    parser.add_argument("--case", action="append", default=[], help="Run only cases with this exact name. Can be passed more than once.")
    parser.add_argument("--strict", action="store_true", help="Fail when summary metrics do not meet thresholds.")
    parser.add_argument("--rebuild-index", action="store_true", help="Run init/map/git before each case to avoid stale local indexes.")
    parser.add_argument("--measure-manual-scan", action="store_true", help="Also time reading all indexed files for each case repository.")
    parser.add_argument("--min-top3-rate", type=float, default=0.85, help="Minimum top-3 hit rate for --strict.")
    parser.add_argument("--min-top5-rate", type=float, default=1.0, help="Minimum top-5 hit rate for --strict.")
    parser.add_argument("--max-noise", type=int, default=2, help="Maximum total noise hits for --strict.")
    parser.add_argument("--output-dir", type=Path, help="Write results.json, results.csv and summary.md to this directory.")
    parser.add_argument("--json-output", type=Path, help="Write machine-readable JSON report to this path.")
    parser.add_argument("--csv-output", type=Path, help="Write per-case CSV results to this path.")
    parser.add_argument("--markdown-output", type=Path, help="Write a Markdown benchmark summary to this path.")
    return parser.parse_args(argv)


def load_cases(selected_names: list[str] | None = None) -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    names = set(selected_names or [])
    if not names:
        return cases
    selected = [case for case in cases if case.get("name") in names]
    missing = sorted(names - {case.get("name") for case in selected})
    if missing:
        raise SystemExit(f"unknown benchmark case(s): {', '.join(missing)}")
    return selected


def resolve_case_repo(case: dict[str, Any]) -> Path | None:
    repo = Path(case["repo"])
    if repo.exists():
        return repo
    if case.get("name") == "init-agent-repository-overview":
        return ROOT
    return None


def evaluate_case(case: dict[str, Any], measure_manual_scan: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    command = list(case_command(case))
    proc = subprocess.run(
        command,
        cwd=case["repo"],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    elapsed = time.perf_counter() - started
    data = json.loads(proc.stdout)
    candidates = candidate_paths_for_case(case, data)
    expected = list(case.get("expected_files", []))
    noise_patterns = list(case.get("noise_patterns", []))
    expected_hits = [path for path in expected if path in candidates]
    expected_file_ranks = expected_ranks(candidates, expected)
    missing_expected_files = [path for path, rank in expected_file_ranks.items() if rank is None]
    noise_hits = [path for path in candidates if any(pattern in path for pattern in noise_patterns)]
    manual_scan_file_count = indexed_file_count(Path(case["repo"]))
    manual_scan = measure_indexed_file_read(Path(case["repo"])) if measure_manual_scan else None
    result = {
        "name": case["name"],
        "status": "ok",
        "elapsed_seconds": round(elapsed, 3),
        "top1_hit": _top_hit(candidates, expected, 1),
        "top3_hit": _top_hit(candidates, expected, 3),
        "top5_hit": _top_hit(candidates, expected, 5),
        "expected_hits": expected_hits,
        "expected_hit_count": len(expected_hits),
        "expected_count": len(expected),
        "expected_file_ranks": expected_file_ranks,
        "missing_expected_files": missing_expected_files,
        "noise_hits": noise_hits,
        "noise_hit_count": len(noise_hits),
        "candidate_file_count": len(candidates),
        "manual_scan_file_count": manual_scan_file_count,
        "manual_scan_reduction_percent": scan_reduction_percent(manual_scan_file_count, len(candidates)),
        "candidate_files": candidates,
    }
    if manual_scan:
        result["manual_scan_elapsed_seconds"] = manual_scan["elapsed_seconds"]
        result["manual_scan_characters"] = manual_scan["characters"]
    if case.get("notes"):
        result["notes"] = case["notes"]
    return result


def case_command(case: dict[str, Any]) -> list[str]:
    if case.get("command") == "overview":
        return [sys.executable, "-m", "init_agent.cli", "run", "--overview", "--json"]
    return [sys.executable, "-m", "init_agent.cli", "run", case["query"], "--json"]


def candidate_paths_for_case(case: dict[str, Any], data: dict[str, Any]) -> list[str]:
    if case.get("command") != "overview":
        return [item["path"] for item in data["context"]["candidate_files"]]
    overview = data.get("overview", {})
    paths = []
    paths.extend(item["path"] for item in overview.get("suggested_first_reads", []))
    paths.extend(item["path"] for item in overview.get("entry_points", []))
    paths.extend(item["path"] for item in overview.get("manifests", []))
    return list(dict.fromkeys(paths))


def indexed_file_count(repo: Path) -> int | None:
    db_path = repo / ".agent" / "graph.sqlite"
    if not db_path.exists():
        return None
    try:
        with closing(sqlite3.connect(db_path)) as connection:
            row = connection.execute("SELECT COUNT(*) FROM files").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


def scan_reduction_percent(total_files: int | None, candidate_files: int) -> float | None:
    if not total_files:
        return None
    reduced = max(total_files - candidate_files, 0)
    return round((reduced / total_files) * 100, 1)


def measure_indexed_file_read(repo: Path) -> dict[str, int | float] | None:
    db_path = repo / ".agent" / "graph.sqlite"
    if not db_path.exists():
        return None
    try:
        with closing(sqlite3.connect(db_path)) as connection:
            rows = connection.execute("SELECT path FROM files ORDER BY path").fetchall()
    except sqlite3.Error:
        return None
    started = time.perf_counter()
    characters = 0
    files_read = 0
    for (relative_path,) in rows:
        path = repo / str(relative_path)
        try:
            characters += len(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        files_read += 1
    return {
        "files": files_read,
        "characters": characters,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _rebuild_index(repo: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    subprocess.run(
        [sys.executable, "-m", "init_agent.cli", "init"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "init_agent.cli", "map"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "init_agent.cli", "git"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_results = [item for item in results if item.get("status") == "ok"]
    total = len(ok_results)
    if total == 0:
        return {"cases": 0}
    top1_hits = sum(1 for item in ok_results if item["top1_hit"])
    top3_hits = sum(1 for item in ok_results if item["top3_hit"])
    top5_hits = sum(1 for item in ok_results if item["top5_hit"])
    noise_hits = sum(int(item["noise_hit_count"]) for item in ok_results)
    reductions = [
        float(item["manual_scan_reduction_percent"])
        for item in ok_results
        if item.get("manual_scan_reduction_percent") is not None
    ]
    manual_elapsed = [
        float(item["manual_scan_elapsed_seconds"])
        for item in ok_results
        if item.get("manual_scan_elapsed_seconds") is not None
    ]
    return {
        "cases": total,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top1_rate": round(top1_hits / total, 3),
        "top3_rate": round(top3_hits / total, 3),
        "top5_rate": round(top5_hits / total, 3),
        "noise_hits": noise_hits,
        "average_elapsed_seconds": round(sum(float(item["elapsed_seconds"]) for item in ok_results) / total, 3),
        "average_manual_scan_reduction_percent": round(sum(reductions) / len(reductions), 1) if reductions else None,
        "average_manual_scan_elapsed_seconds": round(sum(manual_elapsed) / len(manual_elapsed), 3) if manual_elapsed else None,
    }


def expected_ranks(candidates: list[str], expected: list[str]) -> dict[str, int | None]:
    rank_by_path = {path: index + 1 for index, path in enumerate(candidates)}
    return {path: rank_by_path.get(path) for path in expected}


def write_report_outputs(report: dict[str, Any], args: argparse.Namespace) -> None:
    output_dir = getattr(args, "output_dir", None)
    json_output = getattr(args, "json_output", None)
    csv_output = getattr(args, "csv_output", None)
    markdown_output = getattr(args, "markdown_output", None)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_output = json_output or output_dir / "results.json"
        csv_output = csv_output or output_dir / "results.csv"
        markdown_output = markdown_output or output_dir / "summary.md"
    if json_output:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if csv_output:
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        write_csv_report(report, csv_output)
    if markdown_output:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(render_markdown_summary(report), encoding="utf-8")


CSV_FIELDS = [
    "name",
    "status",
    "top1_hit",
    "top3_hit",
    "top5_hit",
    "expected_count",
    "expected_hit_count",
    "missing_expected_count",
    "noise_hit_count",
    "candidate_file_count",
    "elapsed_seconds",
    "manual_scan_file_count",
    "manual_scan_reduction_percent",
    "expected_file_ranks",
    "missing_expected_files",
]


def write_csv_report(report: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in report.get("results", []):
            writer.writerow(result_csv_row(item))


def result_csv_row(item: dict[str, Any]) -> dict[str, Any]:
    ranks = item.get("expected_file_ranks") or {}
    missing = item.get("missing_expected_files") or []
    return {
        "name": item.get("name", ""),
        "status": item.get("status", ""),
        "top1_hit": _csv_bool(item.get("top1_hit")),
        "top3_hit": _csv_bool(item.get("top3_hit")),
        "top5_hit": _csv_bool(item.get("top5_hit")),
        "expected_count": item.get("expected_count", ""),
        "expected_hit_count": item.get("expected_hit_count", ""),
        "missing_expected_count": len(missing),
        "noise_hit_count": item.get("noise_hit_count", ""),
        "candidate_file_count": item.get("candidate_file_count", ""),
        "elapsed_seconds": item.get("elapsed_seconds", ""),
        "manual_scan_file_count": item.get("manual_scan_file_count", ""),
        "manual_scan_reduction_percent": item.get("manual_scan_reduction_percent", ""),
        "expected_file_ranks": "; ".join(f"{path}={rank if rank is not None else 'missing'}" for path, rank in ranks.items()),
        "missing_expected_files": "; ".join(missing),
    }


def render_markdown_summary(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# init-agent Benchmark Summary",
        "",
        "This report measures repository-orientation quality. It checks whether",
        "expected useful files appear early in the generated context pack.",
        "",
        "It does not measure whether an agent solved a task end-to-end.",
        "",
        "## Summary",
        "",
        f"- Cases run: {summary.get('cases', 0)}",
        f"- Top-1 hit rate: {_percent(summary.get('top1_rate'))}",
        f"- Top-3 hit rate: {_percent(summary.get('top3_rate'))}",
        f"- Top-5 hit rate: {_percent(summary.get('top5_rate'))}",
        f"- Noise hits: {summary.get('noise_hits', 0)}",
        f"- Average elapsed seconds: {_value(summary.get('average_elapsed_seconds'))}",
        f"- Average manual scan reduction: {_percent_value(summary.get('average_manual_scan_reduction_percent'))}",
        "",
        "## Cases",
        "",
        "| Case | Status | Top-1 | Top-3 | Top-5 | Noise | Candidates | Elapsed | Manual Scan Reduction | Missing Expected |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report.get("results", []):
        missing = item.get("missing_expected_files") or []
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("name", "")),
                    str(item.get("status", "")),
                    _yes_no(item.get("top1_hit")),
                    _yes_no(item.get("top3_hit")),
                    _yes_no(item.get("top5_hit")),
                    str(item.get("noise_hit_count", "")),
                    str(item.get("candidate_file_count", "")),
                    _value(item.get("elapsed_seconds")),
                    _percent_value(item.get("manual_scan_reduction_percent")),
                    "<br>".join(missing) if missing else "-",
                ]
            )
            + " |"
        )
    skipped = report.get("skipped") or []
    if skipped:
        lines.extend(["", "## Skipped", ""])
        for item in skipped:
            lines.append(f"- `{item.get('name')}`: {item.get('reason')}")
    lines.extend(
        [
            "",
            "## Reading The Results",
            "",
            "- `top1_hit`: the first suggested file was one of the expected useful files.",
            "- `top3_hit` / `top5_hit`: at least one expected file appeared in the first 3 or 5 candidates.",
            "- `noise_hits`: suggested files matching case-specific known-noise patterns.",
            "- `manual_scan_reduction_percent`: indexed file-count reduction from broad scanning to candidate files.",
            "- `missing_expected_files`: expected files that did not appear in the candidate set.",
            "",
        ]
    )
    return "\n".join(lines)


def _csv_bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return ""


def _yes_no(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "-"


def _value(value: Any) -> str:
    return "-" if value is None else str(value)


def _percent(rate: Any) -> str:
    if rate is None:
        return "-"
    return f"{float(rate) * 100:.1f}%"


def _percent_value(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}%"


def strict_failures_for(summary: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures = []
    if int(summary.get("cases", 0)) == 0:
        failures.append("no benchmark cases ran")
        return failures
    if float(summary.get("top3_rate", 0.0)) < args.min_top3_rate:
        failures.append(f"top3_rate {summary.get('top3_rate')} < {args.min_top3_rate}")
    if float(summary.get("top5_rate", 0.0)) < args.min_top5_rate:
        failures.append(f"top5_rate {summary.get('top5_rate')} < {args.min_top5_rate}")
    if int(summary.get("noise_hits", 0)) > args.max_noise:
        failures.append(f"noise_hits {summary.get('noise_hits')} > {args.max_noise}")
    return failures


def _top_hit(candidates: list[str], expected: list[str], limit: int) -> bool:
    return any(path in candidates[:limit] for path in expected)


if __name__ == "__main__":
    raise SystemExit(main())
