"""Text renderers for agent-facing tool contracts."""

from __future__ import annotations

from typing import Any


def render_repo_graph_search_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_graph_search",
        "",
        f"Query: {result['query']}",
        "",
        "Candidate files:",
    ]
    if not result["candidate_files"]:
        lines.append("-")
    for index, item in enumerate(result["candidate_files"], start=1):
        lines.append(f"{index}. {item['path']} score {item['score']:.2f}")
        for reason in item.get("reasons", [])[:3]:
            lines.append(f"   - {reason}")
    confidence = result.get("confidence", {})
    lines.extend(["", "Confidence:", f"- Level: {confidence.get('level', '-')}"])
    for reason in confidence.get("reasons", [])[:5]:
        lines.append(f"- {reason}")
    lines.extend(["", "Next agent actions:"])
    if not result.get("next_agent_actions"):
        lines.append("-")
    for action in result.get("next_agent_actions", []):
        lines.append(f"- {action.get('command', '-')}")
        if action.get("reason"):
            lines.append(f"  reason: {action['reason']}")
    lines.extend(["", "Symbols:"])
    if not result["symbols"]:
        lines.append("-")
    for symbol in result["symbols"]:
        lines.append(f"- {symbol['name']} {symbol['kind']} in {symbol['file']}:{symbol['line']}")
    lines.extend(["", "Follow-up commands:"])
    if not result["followup_commands"]:
        lines.append("-")
    for command in result["followup_commands"]:
        lines.append(f"- {command['command']}")
    if result["warnings"]:
        lines.extend(["", "Warnings:"])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_repo_trace_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_trace",
        "",
        f"Query: {result['query']}",
        f"Profile: {result.get('profile') or '-'}",
        "",
        "Starts:",
    ]
    if not result.get("starts"):
        lines.append("-")
    for item in result.get("starts", [])[:8]:
        lines.append(f"- {item.get('path', '-')} ({item.get('language') or '-'} / {item.get('role') or '-'})")
    lines.extend(["", "Investigation paths:"])
    if not result.get("paths"):
        lines.append("-")
    for index, item in enumerate(result.get("paths", [])[:10], start=1):
        lines.append(f"{index}. {item['target']} score {item['score']:.2f}")
        path = " -> ".join(item.get("path", []))
        if path:
            lines.append(f"   path: {path}")
        if item.get("start_reason"):
            lines.append(f"   start: {item['start_reason']}")
        if item.get("why_this_path"):
            lines.append(f"   why: {item['why_this_path']}")
        edges = list(item.get("edges") or [])
        if edges:
            lines.append("   edges:")
            for edge in edges[:5]:
                if isinstance(edge, dict):
                    lines.append(f"   - {edge.get('from')} --{edge.get('relation')}--> {edge.get('to')}")
                    if edge.get("reason"):
                        lines.append(f"     reason: {edge.get('reason')}")
                else:
                    lines.append(f"   - {edge}")
        if item.get("stop_reason"):
            lines.append(f"   stop: {item['stop_reason']}")
        for reason in item.get("reasons", [])[:4]:
            lines.append(f"   - {reason}")
    lines.extend(["", "Suggested first reads:"])
    if not result.get("suggested_first_reads"):
        lines.append("-")
    for path in result.get("suggested_first_reads", [])[:5]:
        lines.append(f"- {path}")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result.get("followup_commands", []))
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_reading_plan_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_reading_plan",
        "",
        f"Plan id: {result.get('id') or '-'}",
        f"Query: {result['query']}",
        f"Read budget: {result.get('read_budget', '-')}",
        "",
        "Read now:",
    ]
    if not result.get("plan_items"):
        lines.append("-")
    read_now = [item for item in result.get("plan_items", []) if item.get("read_priority") == "read_now"]
    if not read_now and result.get("plan_items"):
        lines.append("-")
    for item in read_now[:10]:
        lines.append(f"{item['rank']}. {item['path']} score {item['score']:.2f}")
        lines.append(f"   action: {item.get('action', '-')}")
        if item.get("read_budget_rank"):
            lines.append(f"   read_budget_rank: {item.get('read_budget_rank')}")
        lines.append(f"   confidence: {item.get('confidence', '-')}")
        sources = ", ".join(item.get("sources") or [])
        lines.append(f"   sources: {sources or '-'}")
        tags = ", ".join(item.get("tags") or [])
        if tags:
            lines.append(f"   tags: {tags}")
        if item.get("reason"):
            lines.append(f"   reason: {item['reason']}")
        for note in item.get("memory", [])[:2]:
            stale = "stale" if note.get("stale") else "fresh"
            if note.get("stale") is None:
                stale = "repo/unknown"
            lines.append(f"   memory #{note['id']} ({stale}): {note.get('topic') or '-'}")
    lines.extend(["", "Read if needed:"])
    secondary = [item for item in result.get("plan_items", []) if item.get("read_priority") in {"read_if_needed", "context_only", "skip_unless_needed"}]
    if not secondary:
        lines.append("-")
    for item in secondary[:10]:
        lines.append(f"- {item['path']} ({item.get('read_priority') or '-'}; rank {item.get('rank')})")
        if item.get("reason"):
            lines.append(f"  reason: {item['reason']}")
    lines.extend(["", "Recommended actions:"])
    _append_commands(lines, result.get("recommended_actions", []))
    if result.get("repo_memory_context"):
        lines.extend(["", "Repo memory context:"])
        for note in result["repo_memory_context"][:5]:
            lines.append(f"- #{note['id']} {note.get('topic') or '-'}: {note.get('note') or '-'}")
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_reading_plan_finish_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_reading_plan_finish",
        "",
        f"Plan id: {result.get('id')}",
        f"Updated: {'yes' if result.get('updated') else 'no'}",
        "",
        "Events:",
    ]
    if not result.get("events"):
        lines.append("-")
    for event in result.get("events", []):
        suffix = f" feedback #{event['feedback_id']}" if event.get("feedback_id") else ""
        lines.append(f"- {event.get('event')}: {event.get('path')}{suffix}")
    if result.get("suggested_memory"):
        lines.extend(["", "Suggested memory:"])
        for item in result["suggested_memory"][:5]:
            lines.append(f"- {item.get('path')}: {item.get('command')}")
            lines.append(f"  reason: {item.get('reason')}")
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_reading_plan_read_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_reading_plan_read",
        "",
        f"Plan id: {result.get('id')}",
        f"Updated: {'yes' if result.get('updated') else 'no'}",
        "",
        "Opened files:",
    ]
    if not result.get("events"):
        lines.append("-")
    for event in result.get("events", []):
        lines.append(f"- {event.get('path')}")
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_reading_plan_diff_text(result: dict[str, Any]) -> str:
    diff = result.get("diff") or {}
    lines = [
        "Init Agent Tool: repo_reading_plan_diff",
        "",
        f"Plan id: {result.get('id')}",
        f"Found: {'yes' if result.get('found') else 'no'}",
        "",
        "Read now not read:",
    ]
    _append_plain_list(lines, diff.get("read_now_not_read", []))
    lines.extend(["", "Suggested not read:"])
    _append_plain_list(lines, diff.get("suggested_not_read", []))
    lines.extend(["", "Read but not planned:"])
    _append_plain_list(lines, diff.get("read_not_planned", []))
    lines.extend(["", "Read without outcome:"])
    _append_plain_list(lines, diff.get("read_without_outcome", []))
    lines.extend(["", "Outcomes:"])
    lines.append(f"- useful: {len(diff.get('useful_paths', []))}")
    lines.append(f"- noisy: {len(diff.get('noisy_paths', []))}")
    lines.append(f"- missing: {len(diff.get('missing_paths', []))}")
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_reading_plan_stats_text(result: dict[str, Any]) -> str:
    stats = result.get("stats") or {}
    lines = [
        "Init Agent Tool: repo_reading_plan_stats",
        "",
        f"Plans: {stats.get('plan_count', 0)}",
        f"Finished: {stats.get('finished_plan_count', 0)}",
        f"Unfinished: {stats.get('unfinished_plan_count', 0)}",
        f"Average files read per finished plan: {stats.get('average_files_read_per_finished_plan', 0)}",
        f"Top-1 useful rate: {stats.get('top1_verified_useful_rate', 0)}",
        f"Top-3 useful rate: {stats.get('top3_verified_useful_rate', 0)}",
        f"Missing count: {stats.get('missing_count', 0)}",
    ]
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_related_file_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_related_file",
        "",
        f"Path: {result['path']}",
        "",
        "File:",
    ]
    if result["file"]:
        file_item = result["file"]
        lines.append(f"- {file_item['path']} ({file_item.get('language') or '-'} / {file_item.get('role') or '-'})")
    else:
        lines.append("-")
    lines.extend(["", "Symbols:"])
    if not result["symbols"]:
        lines.append("-")
    for symbol in result["symbols"][:10]:
        lines.append(f"- {symbol['kind']} {symbol['name']}:{symbol['line']}")
    lines.extend(["", "Calls:"])
    _append_calls(lines, result["calls"][:10])
    lines.extend(["", "Called by:"])
    if not result["called_by"]:
        lines.append("-")
    for caller in result["called_by"][:10]:
        first_line = caller.get("first_line") or "-"
        lines.append(f"- {caller['path']}:{first_line} calls {caller['name']} ({caller['call_count']}x)")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_symbol_callers_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_symbol_callers",
        "",
        f"Symbol: {result['symbol']}",
        "",
        "Definitions:",
    ]
    if not result["definitions"]:
        lines.append("-")
    for definition in result["definitions"]:
        lines.append(f"- {definition['kind']} {definition['path']}:{definition['line']} ({definition['language']})")
    lines.extend(["", "Callers:"])
    if not result["callers"]:
        lines.append("-")
    for caller in result["callers"][:20]:
        first_line = caller.get("first_line") or "-"
        lines.append(f"- {caller['path']}:{first_line} calls {result['symbol']} ({caller['call_count']}x)")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_overview_text(result: dict[str, Any]) -> str:
    project = result["project"]
    lines = [
        "Init Agent Tool: repo_overview",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        f"Git: {'yes' if project.get('git') else 'no'}",
        f"Branch: {project.get('branch') or '-'}",
        "",
        "Suggested first reads:",
    ]
    if not result["suggested_first_reads"]:
        lines.append("-")
    for index, item in enumerate(result["suggested_first_reads"], start=1):
        lines.append(f"{index}. {item['path']}")
        for reason in item.get("reasons", [])[:3]:
            lines.append(f"   - {reason}")
    lines.extend(["", "Likely entry points:"])
    if not result["entry_points"]:
        lines.append("-")
    for item in result["entry_points"]:
        detail = f":{item['line']}" if item.get("line") else ""
        lines.append(f"- {item['path']}{detail} {item['kind']} {item['name']}")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_entrypoints_text(result: dict[str, Any]) -> str:
    project = result["project"]
    lines = [
        "Init Agent Tool: repo_entrypoints",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        "",
        "Likely entry points:",
    ]
    if not result["entry_points"]:
        lines.append("-")
    for index, item in enumerate(result["entry_points"], start=1):
        detail = f":{item['line']}" if item.get("line") else ""
        lines.append(f"{index}. {item['path']}{detail} {item['kind']} {item['name']}")
    lines.extend(["", "Supporting files:"])
    if not result["supporting_files"]:
        lines.append("-")
    for item in result["supporting_files"]:
        lines.append(f"- {item['path']} ({item.get('role') or '-'} / {item.get('language') or '-'})")
        for reason in item.get("reasons", [])[:3]:
            lines.append(f"  - {reason}")
    lines.extend(["", "Manifests and config:"])
    if not result["manifests"]:
        lines.append("-")
    for item in result["manifests"]:
        lines.append(f"- {item['path']}")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_feedback_add_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_feedback_add",
        "",
        f"Query: {result['query']}",
        f"Path: {result['path']}",
        f"Rating: {result['rating']}",
        f"Source: {result['source']}",
        f"Recorded: {'yes' if result['recorded'] else 'no'}",
    ]
    if result.get("feedback"):
        lines.append(f"Feedback id: {result['feedback']['id']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_feedback_explain_text(result: dict[str, Any]) -> str:
    feedback = result["feedback"]
    lines = [
        "Init Agent Tool: repo_feedback_explain",
        "",
        f"Query: {feedback['query']}",
        f"Query tokens: {', '.join(feedback['query_tokens']) if feedback['query_tokens'] else '-'}",
        "",
        "Matched signals:",
    ]
    if not feedback["signals"]:
        lines.append("-")
    for signal in feedback["signals"]:
        lines.append(f"- {signal['path']} net {signal['net']:+.2f}")
        for item in signal.get("items", [])[:3]:
            lines.append(f"  - #{item['id']} {item['rating']} similarity {item['similarity']:.2f}")
            if item.get("reason"):
                lines.append(f"    reason: {item['reason']}")
    if feedback.get("ignored"):
        lines.extend(["", "Ignored feedback:"])
        for item in feedback["ignored"][:5]:
            lines.append(f"- #{item['id']} {item['rating']} {item['path']} ({item['ignored_reason']})")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_add_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_add",
        "",
        f"Scope: {result['scope']}",
        f"Path: {result['path']}",
        f"Topic: {result['topic'] or '-'}",
        f"Query: {result['query'] or '-'}",
        f"Source: {result['source']}",
        f"Evidence: {result['evidence']}",
        f"Tags: {', '.join(result.get('tags') or []) or '-'}",
        f"Recorded: {'yes' if result['recorded'] else 'no'}",
    ]
    if result.get("memory"):
        lines.append(f"Memory id: {result['memory']['id']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_search_text(result: dict[str, Any]) -> str:
    memory = result["memory"]
    lines = [
        "Init Agent Tool: repo_memory_search",
        "",
        f"Query: {memory['query']}",
        "Matches:",
    ]
    if not memory["matches"]:
        lines.append("-")
    for item in memory["matches"]:
        label = item["path"] or "(repo)"
        lines.append(f"- {label} score {item['score']:.2f}")
        if item.get("scope"):
            lines.append(f"  scope: {item['scope']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("evidence"):
            lines.append(f"  evidence: {item['evidence']}")
        if item.get("tags"):
            lines.append(f"  tags: {', '.join(item['tags'])}")
        if item.get("stale"):
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        elif item.get("stale") is None:
            lines.append(f"  stale: unknown ({item.get('stale_reason') or 'no file hash recorded'})")
        lines.append(f"  note: {item['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_file_notes_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_file_notes",
        "",
        f"Path: {result['path']}",
        "Notes:",
    ]
    if not result["notes"]:
        lines.append("-")
    for item in result["notes"]:
        lines.append(f"- #{item['id']} {item['created_at']}")
        if item.get("scope"):
            lines.append(f"  scope: {item['scope']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("evidence"):
            lines.append(f"  evidence: {item['evidence']}")
        if item.get("stale"):
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        elif item.get("stale") is None:
            lines.append(f"  stale: unknown ({item.get('stale_reason') or 'no file hash recorded'})")
        lines.append(f"  note: {item['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_list_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_list",
        "",
        f"Path: {result.get('path') or '-'}",
        f"Topic: {result.get('topic') or '-'}",
        f"Scope: {result.get('scope') or '-'}",
        f"Stale only: {'yes' if result.get('stale_only') else 'no'}",
        "Notes:",
    ]
    if not result["notes"]:
        lines.append("-")
    for item in result["notes"]:
        label = item["path"] or "(repo)"
        lines.append(f"- #{item['id']} {label} ({item['created_at']})")
        if item.get("scope"):
            lines.append(f"  scope: {item['scope']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("evidence"):
            lines.append(f"  evidence: {item['evidence']}")
        if item.get("stale"):
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        elif item.get("stale") is None:
            lines.append(f"  stale: unknown ({item.get('stale_reason') or 'no file hash recorded'})")
        lines.append(f"  note: {item['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_topics_text(result: dict[str, Any]) -> str:
    memory = result["memory"]
    lines = [
        "Init Agent Tool: repo_memory_topics",
        "",
        f"Topic filter: {memory.get('topic') or '-'}",
        "Topics:",
    ]
    if not memory["topics"]:
        lines.append("-")
    for item in memory["topics"]:
        label = item["topic"] or "(untitled)"
        lines.append(f"- {label}: {item['note_count']} notes, {item['file_count']} files")
        if item.get("repo_note_count"):
            lines.append(f"  repo notes: {item['repo_note_count']}")
        if item.get("stale_count"):
            lines.append(f"  stale notes: {item['stale_count']}")
        if item.get("paths"):
            lines.append(f"  paths: {', '.join(item['paths'][:5])}")
        for note in item.get("notes", [])[:3]:
            note_label = note.get("path") or "(repo)"
            lines.append(f"  - #{note['id']} {note_label}: {note['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_flow_topics_text(result: dict[str, Any]) -> str:
    flows = result["flows"]
    lines = [
        "Init Agent Tool: repo_flow_topics",
        "",
        f"Tag filter: {flows.get('tag') or '-'}",
        "Flows:",
    ]
    if not flows.get("flows"):
        lines.append("-")
    for item in flows.get("flows", [])[:10]:
        lines.append(f"- {item['tag']}: {item['file_count']} files, {item['note_count']} notes")
        if item.get("stale_count"):
            lines.append(f"  stale notes: {item['stale_count']}")
        if item.get("paths"):
            lines.append(f"  paths: {', '.join(item['paths'][:5])}")
        if item.get("suggested_flow_memory"):
            lines.append(f"  suggested: {item['suggested_flow_memory']['command']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_audit_text(result: dict[str, Any]) -> str:
    audit = result["audit"]
    lines = [
        "Init Agent Tool: repo_memory_audit",
        "",
        f"Notes checked: {audit.get('note_count', 0)}",
        "Summary:",
    ]
    summary = audit.get("summary") or {}
    if not summary:
        lines.append("-")
    for key, count in summary.items():
        lines.append(f"- {key}: {count}")
    issues = audit.get("issues") or {}
    for key in ("stale", "unknown_evidence", "missing_topic", "short_note"):
        items = list(issues.get(key) or [])[:5]
        if not items:
            continue
        lines.extend(["", key.replace("_", " ").title() + ":"])
        for item in items:
            label = item.get("path") or "(repo)"
            lines.append(f"- #{item['id']} {label} [{item.get('topic') or '-'}]")
    duplicates = list(issues.get("duplicate_file_topic") or [])[:5]
    if duplicates:
        lines.extend(["", "Duplicate File/Topic Groups:"])
        for item in duplicates:
            label = item.get("path") or "(repo)"
            lines.append(f"- {label} [{item.get('topic') or '-'}]: {item['note_count']} notes ids={item['ids']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_delete_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_delete",
        "",
        f"Memory id: {result['id']}",
        f"Deleted: {'yes' if result['deleted'] else 'no'}",
    ]
    if result.get("note"):
        lines.append(f"Scope: {result['note'].get('scope', 'file')}")
        lines.append(f"Path: {result['note']['path'] or '(repo)'}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_update_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_update",
        "",
        f"Memory id: {result['id']}",
        f"Updated: {'yes' if result['updated'] else 'no'}",
    ]
    if result.get("memory"):
        memory = result["memory"]
        lines.append(f"Scope: {memory.get('scope', 'file')}")
        lines.append(f"Path: {memory['path'] or '(repo)'}")
        if memory.get("topic"):
            lines.append(f"Topic: {memory['topic']}")
        if memory.get("evidence"):
            lines.append(f"Evidence: {memory['evidence']}")
        if memory.get("stale"):
            lines.append(f"Stale: {memory.get('stale_reason') or 'yes'}")
        elif memory.get("stale") is None:
            lines.append(f"Stale: unknown ({memory.get('stale_reason') or 'no file hash recorded'})")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_add_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_task_add",
        "",
        f"Recorded: {'yes' if result.get('recorded') else 'no'}",
    ]
    if result.get("task"):
        task = result["task"]
        lines.append(f"Task id: {task['id']}")
        lines.append(f"Title: {task['title']}")
        lines.append(f"Status: {task['status']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_list_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_task_list",
        "",
        f"Status filter: {result.get('status') or '-'}",
        f"Topic filter: {result.get('topic') or '-'}",
        "Tasks:",
    ]
    tasks = list(result.get("tasks") or [])
    if not tasks:
        lines.append("-")
    for task in tasks:
        lines.append(f"- #{task['id']} [{task['status']}] {task['title']}")
        if task.get("topic"):
            lines.append(f"  topic: {task['topic']}")
        if task.get("files"):
            lines.append(f"  files: {', '.join(task['files'][:5])}")
        if task.get("remaining"):
            lines.append(f"  remaining: {'; '.join(task['remaining'][:3])}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_update_text(result: dict[str, Any]) -> str:
    lines = [
        f"Init Agent Tool: {result['tool']}",
        "",
        f"Task id: {result['id']}",
        f"Updated: {'yes' if result.get('updated') else 'no'}",
    ]
    if result.get("task"):
        task = result["task"]
        lines.append(f"Title: {task['title']}")
        lines.append(f"Status: {task['status']}")
        if task.get("files"):
            lines.append(f"Files: {', '.join(task['files'][:5])}")
        if task.get("tests"):
            lines.append(f"Tests: {'; '.join(task['tests'][:3])}")
        if task.get("remaining"):
            lines.append(f"Remaining: {'; '.join(task['remaining'][:3])}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_note_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_task_note",
        "",
        f"Task id: {result['id']}",
        f"Recorded: {'yes' if result.get('recorded') else 'no'}",
    ]
    if result.get("note"):
        lines.append(f"Note id: {result['note']['id']}")
    if result.get("task"):
        lines.append(f"Status: {result['task']['status']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_session_summary_text(result: dict[str, Any]) -> str:
    project = result.get("project") or {}
    git = result.get("git") or {}
    lines = [
        "Init Agent Tool: repo_session_summary",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        f"Git: {'yes' if git.get('available') else 'no'}",
        f"Branch: {git.get('branch') or '-'}",
        "",
        "Git status:",
    ]
    status = list(git.get("status") or [])
    if not status:
        lines.append("-")
    for item in status:
        lines.append(f"- {item}")

    audit_summary = (result.get("memory_audit") or {}).get("summary") or {}
    lines.extend(["", "Memory audit:"])
    if not audit_summary:
        lines.append("-")
    for key, count in audit_summary.items():
        lines.append(f"- {key}: {count}")

    lines.extend(["", "Recent memory:"])
    recent_memory = list(result.get("recent_memory") or [])
    if not recent_memory:
        lines.append("-")
    for item in recent_memory[:5]:
        label = item.get("path") or "(repo)"
        topic = item.get("topic") or "-"
        lines.append(f"- #{item['id']} {label} [{topic}]")
        if item.get("stale") is True:
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        lines.append(f"  note: {item['note']}")

    lines.extend(["", "Recent feedback:"])
    recent_feedback = list(result.get("recent_feedback") or [])
    if not recent_feedback:
        lines.append("-")
    for item in recent_feedback[:5]:
        lines.append(f"- #{item['id']} {item['rating']} {item['path']}")
        if item.get("reason"):
            lines.append(f"  reason: {item['reason']}")

    lines.extend(["", "Open tasks:"])
    recent_tasks = list(result.get("recent_tasks") or [])
    if not recent_tasks:
        lines.append("-")
    for item in recent_tasks[:5]:
        lines.append(f"- #{item['id']} [{item['status']}] {item['title']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("remaining"):
            lines.append(f"  remaining: {'; '.join(item['remaining'][:3])}")

    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result.get("followup_commands") or [])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_session_close_text(result: dict[str, Any]) -> str:
    project = result.get("project") or {}
    git = result.get("git") or {}
    lines = [
        "Init Agent Session Close",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        f"Git: {'yes' if git.get('available') else 'no'}",
        f"Branch: {git.get('branch') or '-'}",
        f"Close ready: {'yes' if result.get('close_ready') else 'no'}",
        "",
        "Checklist:",
    ]
    for item in result.get("checklist") or []:
        command = item.get("command") or ""
        lines.append(f"- [{item.get('status', '-')}] {item.get('title', '-')}")
        if item.get("reason"):
            lines.append(f"  reason: {item['reason']}")
        if command:
            lines.append(f"  command: {command}")

    audit_summary = (result.get("memory_audit") or {}).get("summary") or {}
    lines.extend(["", "Memory audit:"])
    if not audit_summary:
        lines.append("-")
    for key, count in audit_summary.items():
        lines.append(f"- {key}: {count}")

    status = list(git.get("status") or [])
    lines.extend(["", "Git status:"])
    if not status:
        lines.append("-")
    for item in status:
        lines.append(f"- {item}")

    lines.extend(["", "Recent memory:"])
    recent_memory = list(result.get("recent_memory") or [])
    if not recent_memory:
        lines.append("-")
    for item in recent_memory[:5]:
        label = item.get("path") or "(repo)"
        topic = item.get("topic") or "-"
        lines.append(f"- #{item['id']} {label} [{topic}]")
        if item.get("stale") is True:
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        lines.append(f"  note: {item['note']}")

    lines.extend(["", "Open tasks:"])
    recent_tasks = list(result.get("recent_tasks") or [])
    if not recent_tasks:
        lines.append("-")
    for item in recent_tasks[:5]:
        lines.append(f"- #{item['id']} [{item['status']}] {item['title']}")
        if item.get("remaining"):
            lines.append(f"  remaining: {'; '.join(item['remaining'][:3])}")

    plan_activity = result.get("plan_activity") or {}
    lines.extend(["", "Reading plans:"])
    lines.append(f"- unfinished: {len(plan_activity.get('unfinished_plans') or [])}")
    lines.append(f"- finished recent: {len(plan_activity.get('finished_plans') or [])}")
    lines.append(f"- events recent: {plan_activity.get('event_count', 0)}")

    lines.extend(["", "Suggested feedback:"])
    suggested_feedback = list(result.get("suggested_feedback") or [])
    if not suggested_feedback:
        lines.append("-")
    for item in suggested_feedback[:5]:
        lines.append(f"- {item.get('command')}")
        lines.append(f"  reason: {item.get('reason')}")

    lines.extend(["", "Suggested memory:"])
    suggested_memory = list(result.get("suggested_memory") or [])
    if not suggested_memory:
        lines.append("-")
    for item in suggested_memory[:5]:
        lines.append(f"- {item.get('command')}")
        lines.append(f"  reason: {item.get('reason')}")

    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)



def _append_calls(lines: list[str], calls: list[dict[str, Any]]) -> None:
    printed = 0
    unresolved = 0
    for call in calls:
        definitions = call.get("definitions", [])
        if definitions:
            for definition in definitions:
                lines.append(f"- {call['name']} -> {definition['path']}:{definition['line']} ({definition['kind']})")
                printed += 1
        else:
            unresolved += 1
    if unresolved:
        lines.append(f"- {unresolved} unresolved calls omitted")
    if not printed and not unresolved:
        lines.append("-")


def _append_commands(lines: list[str], commands: list[dict[str, str]]) -> None:
    if not commands:
        lines.append("-")
    for command in commands:
        lines.append(f"- {command['command']}")


def _append_plain_list(lines: list[str], items: list[str]) -> None:
    if not items:
        lines.append("-")
    for item in items:
        lines.append(f"- {item}")


def _append_warnings(lines: list[str], warnings: list[str]) -> None:
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings:
            lines.append(f"- {warning}")


