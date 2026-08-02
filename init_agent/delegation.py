"""Build conservative, provider-agnostic delegation advice for reading plans."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any


MODEL_TIERS = {"fast", "balanced", "deep"}
REASONING_EFFORTS = {"low", "medium", "high"}

_CONTAINER_SEGMENTS = {"app", "apps", "lib", "libs", "packages", "pkg", "src"}
_TAG_SCOPES = (
    "frontend",
    "backend",
    "tests",
    "docs",
    "cli",
    "mcp",
    "web",
    "database",
    "security",
    "config",
)


def build_delegation_advice(
    query: str,
    plan_items: list[dict[str, Any]],
    read_budget: int,
) -> dict[str, Any]:
    """Return optional workstreams without assuming a specific agent provider."""

    candidates = [
        item
        for item in plan_items
        if item.get("read_priority") in {"read_now", "read_if_needed"}
        and item.get("action") != "skip_unless_needed"
    ][: max(3, min(9, read_budget * 2))]
    task_profile = _task_profile(query, candidates)
    if not candidates:
        return _advice(
            strategy="direct",
            recommended=False,
            reason="no reliable file candidates are available for safe delegation",
            task_profile=task_profile,
            workstreams=[],
        )

    grouped = _group_candidates(candidates)
    parallel_groups = [group for group in grouped if group[1]][:3]
    if len(parallel_groups) >= 2 and len(candidates) >= 4:
        workstreams = [
            _workstream(index, query, scope, items)
            for index, (scope, items) in enumerate(parallel_groups, start=1)
        ]
        return _advice(
            strategy="parallel",
            recommended=True,
            reason="the plan contains multiple bounded repository scopes that can be explored independently",
            task_profile=task_profile,
            workstreams=workstreams,
        )

    if len(candidates) >= 3:
        scope, items = parallel_groups[0]
        return _advice(
            strategy="single_worker",
            recommended=True,
            reason="one bounded read-only exploration can keep intermediate output out of the parent context",
            task_profile=task_profile,
            workstreams=[_workstream(1, query, scope, items[: max(2, read_budget)])],
        )

    return _advice(
        strategy="direct",
        recommended=False,
        reason="the plan is small enough that spawning a subagent would likely add more coordination than value",
        task_profile=task_profile,
        workstreams=[],
    )


def _task_profile(query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    confidences = [str(item.get("confidence") or "low") for item in candidates]
    low_confidence = sum(1 for value in confidences if value == "low")
    high_confidence = sum(1 for value in confidences if value == "high")
    query_size = len([token for token in query.split() if token])
    if len(candidates) <= 2 and high_confidence == len(candidates) and query_size <= 12:
        tier, effort = "fast", "low"
    elif low_confidence or len(candidates) >= 7 or query_size >= 20:
        tier, effort = "deep", "high"
    else:
        tier, effort = "balanced", "medium"
    return {
        "model_tier": tier,
        "reasoning_effort": effort,
        "basis": "structural plan size and confidence only; the orchestrator must apply semantic judgment",
    }


def _group_candidates(candidates: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        grouped[_scope_for(item)].append(item)
    ordered = sorted(
        grouped.items(),
        key=lambda entry: (
            min(int(item.get("rank") or 9999) for item in entry[1]),
            entry[0],
        ),
    )
    if len(ordered) > 1:
        return ordered

    tag_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        tags = {str(tag).lower() for tag in item.get("tags") or []}
        scope = next((tag for tag in _TAG_SCOPES if tag in tags), "core")
        tag_groups[scope].append(item)
    return sorted(
        tag_groups.items(),
        key=lambda entry: min(int(item.get("rank") or 9999) for item in entry[1]),
    )


def _scope_for(item: dict[str, Any]) -> str:
    path = PurePosixPath(str(item.get("path") or ""))
    parts = [part for part in path.parts if part not in {".", ""}]
    if not parts:
        return "repository"
    lowered = [part.lower() for part in parts]
    if any(part in {"test", "tests", "spec", "specs"} for part in lowered):
        return "tests"
    if any(part in {"doc", "docs", "documentation"} for part in lowered) or path.suffix.lower() == ".md":
        return "docs"
    index = 1 if lowered[0] in _CONTAINER_SEGMENTS and len(parts) > 1 else 0
    return parts[index]


def _workstream(
    index: int,
    query: str,
    scope: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = [str(item.get("path") or "") for item in items if item.get("path")][:5]
    confidences = {str(item.get("confidence") or "low") for item in items}
    if len(paths) <= 2 and confidences == {"high"}:
        tier, effort = "fast", "low"
    elif "low" in confidences or len(paths) >= 5:
        tier, effort = "deep", "high"
    else:
        tier, effort = "balanced", "medium"
    return {
        "key": f"ws-{index}",
        "title": f"Explore {scope}",
        "objective": f"Inspect the assigned scope for {query.strip()} and return verified evidence to the parent orchestrator.",
        "role": "explorer",
        "model_tier": tier,
        "reasoning_effort": effort,
        "access_mode": "read_only",
        "scope_paths": paths,
        "depends_on": [],
        "status": "proposed",
    }


def _advice(
    *,
    strategy: str,
    recommended: bool,
    reason: str,
    task_profile: dict[str, Any],
    workstreams: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "recommended": recommended,
        "reason": reason,
        "task_profile": task_profile,
        "workstreams": workstreams,
        "orchestrator_contract": {
            "must_review_reports": True,
            "responsibility": "the parent orchestrator decides whether delegated work is correct and complete",
            "unused_proposals_block_finish": False,
            "unreviewed_reports_block_finish": True,
            "report_tool": "repo_workstream_report",
            "review_tool": "repo_workstream_review",
        },
        "report_contract": {
            "required": ["summary"],
            "optional": [
                "files_read",
                "files_modified",
                "tests",
                "findings",
                "risks",
                "remaining",
            ],
        },
    }
