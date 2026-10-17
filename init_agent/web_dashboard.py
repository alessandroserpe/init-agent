"""Read-only work and verification views for the local dashboard."""
import html


def e(value):
    return html.escape(str(value), quote=True)


LABELS = {'passed': 'Passed · files unchanged', 'needs_rerun': 'Needs rerun',
          'not_verified': 'Not verified', 'timeout': 'Timed out', 'unknown': 'Not checked',
          'open': 'Open', 'in_progress': 'In progress', 'blocked': 'Blocked', 'done': 'Completed'}


def badge(state):
    known = state if state in LABELS else 'unknown'
    return f'<span class="status status-{known}">{e(LABELS[known])}</span>'


def search_data(item):
    return e(str(item).lower())


def task_list(tasks):
    rows = []
    for task in tasks:
        details = f'<p>{e(task.get("summary") or "No summary recorded.")}</p>'
        if task.get('remaining'):
            details += f'<h4>Remaining work</h4><p>{e(task["remaining"])}</p>'
        if task.get('files'):
            details += '<h4>Linked files</h4><ul>' + ''.join(f'<li><code>{e(p)}</code></li>' for p in task['files']) + '</ul>'
        rows.append(f'<article class="work-row filter-row" data-search="{search_data(task)}">'
                    f'<div class="row-meta"><span>Task #{e(task["id"])}</span>{badge(task["status"])}</div>'
                    f'<h3>{e(task["title"])}</h3><p class="row-topic">{e(task.get("topic") or "No topic")}</p>'
                    f'<details><summary>Task details</summary>{details}</details></article>')
    body = ''.join(rows) or '<p class="empty">No open tasks. Completed work remains in local history.</p>'
    return '<section class="work-section"><div class="section-heading"><h2>Open work</h2>' + f'<span>{len(tasks)} shown</span></div>{body}</section>'


def checks_list(checks):
    rows = []
    # Attention first within the bounded recent sample; never imply global coverage.
    ordered = sorted(checks, key=lambda c: c['state'] == 'passed')
    for check in ordered:
        state = check['state']
        changed = check.get('changed_files', [])
        uncovered = check.get('uncovered_files', [])
        unchecked = check.get('unchecked_files', [])
        reasons = []
        if changed:
            reasons.append('Changed or unavailable: ' + ', '.join(changed))
        if uncovered:
            reasons.append('Added to task after this run: ' + ', '.join(uncovered))
        if unchecked:
            reasons.append('Not checked within the live-read budget: ' + ', '.join(unchecked))
        if not reasons:
            reasons.append('Recorded files are unchanged. This does not prove task completion.' if state == 'passed'
                           else 'This run does not provide a current passing verification.')
        counts = check.get('counts') or {}
        details = '<p>' + e(' · '.join(reasons)) + '</p>'
        details += f'<p>Last run: {e(check.get("checked_at") or "unknown")} · {e(counts.get("run", 0))} tests · {e(counts.get("skipped", 0))} skipped</p>'
        details += f'<p>Recorded outcome: {e(check.get("run_state", "unknown"))}. Scope: linked files and test module only; environment and other dependencies are not checked.</p>'
        details += '<ul>' + ''.join(f'<li><code>{e(p)}</code></li>' for p in check.get('files', [])) + '</ul>'
        rows.append(f'<article class="work-row filter-row" data-search="{search_data(check)}">'
                    f'<div class="row-meta"><span>Task #{e(check["task_id"])} · {e(LABELS.get(check.get("task_status"), "Unknown"))}</span>{badge(state)}</div>'
                    f'<h3><code>{e(check["test"])}</code></h3><p class="row-topic">{e(check["title"])}</p>'
                    f'<p class="check-reason">{e(reasons[0])}</p>'
                    f'<details><summary>Evidence & files</summary>{details}</details></article>')
    body = ''.join(rows) or '<p class="empty">No saved test runs. When a task has linked files, its selected test can be run and recorded with <code>init-agent task verify &lt;id&gt; --test &lt;test&gt;</code>.</p>'
    return '<section class="work-section"><div class="section-heading"><h2>Recent verifications</h2>' + f'<span>{len(checks)} shown</span></div>{body}</section>'


def index_panel(health):
    state = health.get('status', 'unknown')
    title = {'ready': 'No index drift detected', 'stale': 'Graph update available',
             'missing': 'Graph not created', 'empty': 'Graph is empty',
             'error': 'Index could not be read'}.get(state, 'Index not checked')
    if state == 'stale':
        detail = f'{health.get("changed_count", 0)} changed · {health.get("unindexed_count", 0)} new · {health.get("missing_count", 0)} removed'
    elif state == 'ready':
        detail = 'Compared file paths, sizes and modification times; not a full content audit.'
    else:
        detail = 'Availability is separate from the validity of saved test evidence.'
    return ('<section class="index-summary"><h2>Repository index</h2>'
            f'<h3>{e(title)}</h3><p>{e(detail)}</p>'
            '<p>Search updates its index when needed. Task evidence is checked directly against files.</p>'
            '<details><summary>When is a manual update useful?</summary>'
            '<p>Update before using graph orientation if its index is outdated. You do not need to rebuild the graph to view tasks or saved test checks.</p></details></section>')


def work_overview(snapshot):
    tasks = snapshot.get('open_tasks') or []
    checks = snapshot.get('recent_checks') or []
    attention = sum(c['state'] != 'passed' for c in checks)
    stale = sum(n.get('stale') is True for n in snapshot.get('recent_memory', []))
    return ('<div class="work-intro"><div><h2>Pick up where you left off</h2>'
            '<p>Open work and the evidence you can still rely on.</p></div>'
            f'<span class="local-label">Local · Read-only</span></div>'
            '<div class="attention-strip">'
            f'<button type="button" data-go="tasks">{len(tasks)} open tasks shown <span aria-hidden="true">→</span></button>'
            f'<button type="button" data-go="checks">{attention} recent checks need attention <span aria-hidden="true">→</span></button>'
            f'<button type="button" data-go="memory">{stale} stale notes shown <span aria-hidden="true">→</span></button>'
            '</div><div class="work-layout"><div>' + task_list(tasks) + '</div><aside>'
            + index_panel(snapshot.get('index_health') or {}) + '</aside></div>'
            + checks_list(sorted(checks, key=lambda c: c["state"] == "passed")[:5])
            + '<p class="scope-note">Recent sample only. No tests run and no index is rebuilt when you open this view.</p>')


DASHBOARD_CSS = """
:root { --focus: #075ca0; }
header { position: static; }
header > div { min-width: 0; }
header span { overflow-wrap: anywhere; }
h1, h2, h3 { text-wrap: balance; }
.layout { max-width: 1344px; }
.snapshot-meta { margin: 0 0 20px; color: var(--muted); font-size: 12px; }
.toolbar { align-items: stretch; flex-direction: column; gap: 18px; }
.tabs { gap: 0; border-bottom: 1px solid var(--line); }
.tab { border: 0; border-radius: 0; background: transparent; padding: 12px 14px; border-bottom: 2px solid transparent; }
.tab.active { background: transparent; border-color: var(--accent); font-weight: 600; }
.tab:hover, .action:hover { background: var(--accent-soft); }
.search { min-width: 0; width: min(100%, 520px); }
input::placeholder { color: var(--muted); opacity: 1; }
button, a, summary, input { -webkit-tap-highlight-color: transparent; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; }
.action { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 8px 12px; cursor: pointer; }
.action:disabled { opacity: .65; cursor: wait; }
.work-intro { display: flex; justify-content: space-between; gap: 18px; align-items: start; margin: 28px 0 20px; }
.work-intro h2 { font-size: 23px; margin: 0 0 6px; }
.work-intro p, .scope-note { color: var(--muted); margin: 0; }
.local-label { color: var(--muted); font-size: 12px; padding-top: 8px; white-space: nowrap; }
.attention-strip { display: flex; flex-wrap: wrap; gap: 8px 24px; padding: 16px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin-bottom: 30px; }
.attention-strip button { border: 0; padding: 4px 0; background: transparent; color: var(--accent); font: inherit; cursor: pointer; }
.attention-strip button:hover { text-decoration: underline; }
.attention-strip span { margin-left: 8px; }
.work-layout { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(260px, 1fr); gap: 38px; align-items: start; }
.work-section { margin-bottom: 32px; min-width: 0; }
.section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--line); padding-bottom: 12px; }
.section-heading h2 { margin: 0; font-size: 17px; }
.section-heading > span { font-size: 12px; color: var(--muted); white-space: nowrap; }
.work-row { padding: 18px 0; border-bottom: 1px solid var(--line); }
.work-row h3 { font-size: 16px; line-height: 1.5; margin: 10px 0 4px; overflow-wrap: anywhere; }
.work-row h3 code { font-size: 14px; }
.row-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; color: var(--muted); font-size: 12px; }
.row-topic { color: var(--muted); margin: 0 0 12px; overflow-wrap: anywhere; }
.status { display: inline-block; font-size: 12px; padding: 3px 8px; border-radius: 4px; background: #e8edf3; color: #354456; }
.status-passed, .status-done { background: #e8f5ef; color: #176b43; }
.status-needs_rerun, .status-timeout, .status-not_verified { background: #fff0d6; color: #754400; }
.status-blocked { background: #fff0f0; color: #9d2b2b; }
.status-in_progress { background: #e8f2fb; color: #1769aa; }
.check-reason { font-size: 13px; color: var(--muted-strong); overflow-wrap: anywhere; margin-bottom: 12px; }
details { overflow-wrap: anywhere; }
summary { cursor: pointer; color: var(--accent); padding: 5px 0; }
details p { max-width: 75ch; }
details h4 { margin: 14px 0 4px; }
details ul { padding-left: 22px; }
.index-summary { background: #edf2f7; padding: 20px; border-radius: 6px; }
.index-summary h2 { font-size: 13px; color: var(--muted); margin: 0 0 14px; font-weight: 500; }
.index-summary h3 { font-size: 18px; margin: 0 0 10px; }
.index-summary p { color: var(--muted-strong); }
.scope-note { margin: -12px 0 24px; font-size: 12px; }
.technical { border-top: 1px solid var(--line); padding-top: 16px; margin-top: 30px; }
.technical > summary { color: var(--muted-strong); }
.technical .metrics { display: flex; flex-wrap: wrap; margin: 20px 0; gap: 16px 28px; }
.technical .metrics div { background: none; padding: 0; border: none; }
.technical .metrics strong { font-size: 16px; }
.technical .warning { background: transparent; box-shadow: none; }
.filter-empty { color: var(--muted); padding: 20px 0; }
[hidden] { display: none !important; }
@media (max-width: 760px) {
  header { padding: 18px 16px; gap: 16px; }
  nav { flex-wrap: wrap; }
  .work-layout { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .index-summary { margin: 0 0 28px; }
  .work-intro { flex-direction: column; gap: 6px; }
  .tabs { flex-wrap: nowrap; overflow-x: auto; padding: 4px; }
  .tab { flex-shrink: 0; }
}
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; transition: none !important; } }
"""
