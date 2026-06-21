"""Build broad repository overview packs from indexed metadata."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .git_reader import current_branch, git_available, has_git
from .graph_store import GraphStore


MANIFEST_NAMES = {
    "pyproject.toml",
    "package.json",
    "composer.json",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "Makefile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}
README_NAMES = {"README.md", "README.rst", "README.txt", "readme.md", "readme.rst", "readme.txt"}
CONFIG_NAMES = {
    ".env.example",
    "Dockerfile",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
    "webpack.config.js",
    "next.config.js",
    "eslint.config.js",
    "ruff.toml",
}
ENTRY_FILENAMES = {
    "__main__.py",
    "main.py",
    "app.py",
    "server.py",
    "cli.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "index.php",
    "index.js",
    "index.ts",
    "main.go",
    "main.rs",
    "lib.rs",
}
ENTRY_PARTS = {"cli", "server", "router", "routers", "routes", "api", "app", "main", "cmd", "bin"}
SUBSYSTEM_NOISE = {".agent", ".git", "__pycache__"}
MAX_FIRST_READS = 12
MAX_ENTRY_POINTS = 10
MAX_MANIFESTS = 10
MAX_SUBSYSTEMS = 10


def build_overview_pack(root: Path) -> dict[str, Any]:
    with GraphStore(root) as store:
        store.initialize()
        conn = store.connection
        files = [
            dict(row)
            for row in conn.execute(
                "SELECT id, path, extension, language, role, size, modified_at FROM files ORDER BY path"
            )
        ]
        symbols = [
            dict(row)
            for row in conn.execute(
                """
                SELECT s.name, s.kind, s.line, s.signature, f.path AS file, f.role AS file_role
                FROM symbols s
                JOIN files f ON f.id = s.file_id
                ORDER BY f.path, s.line, s.name
                """
            )
        ]
        project = store.get_meta("project", root.name)
        last_map = store.latest_map_time()

    symbol_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for symbol in symbols:
        symbol_by_file[str(symbol["file"])].append(symbol)

    candidates = _rank_first_reads(files, symbol_by_file)
    entry_points = _entry_points(files, symbol_by_file)
    manifests = _manifest_files(files, symbol_by_file)
    subsystems = _subsystems(files)
    git_present = has_git(root)
    branch = current_branch(root) if git_available(root) else None

    return {
        "project": {
            "name": project or root.name,
            "root": str(root),
            "git": git_present,
            "branch": branch,
            "last_map": last_map,
        },
        "suggested_first_reads": candidates[:MAX_FIRST_READS],
        "entry_points": entry_points[:MAX_ENTRY_POINTS],
        "manifests": manifests[:MAX_MANIFESTS],
        "subsystems": subsystems[:MAX_SUBSYSTEMS],
    }


def render_overview_text(pack: dict[str, Any]) -> str:
    project = pack["project"]
    lines = [
        "Init Agent Repository Overview",
        "",
        "Project:",
        f"- Name: {project['name']}",
        f"- Root: {project['root']}",
        f"- Git: {'yes' if project['git'] else 'no'}",
        f"- Branch: {project['branch'] or '-'}",
        f"- Last map: {project['last_map'] or '-'}",
        "",
        "Suggested first reads:",
    ]
    _append_ranked_files(lines, pack["suggested_first_reads"])
    lines.extend(["", "Likely entry points:"])
    _append_entry_points(lines, pack["entry_points"])
    lines.extend(["", "Package manifests and config:"])
    _append_simple_files(lines, pack["manifests"])
    lines.extend(["", "Major subsystems:"])
    _append_subsystems(lines, pack["subsystems"])
    lines.extend(["", "Note: overview is heuristic. Verify by reading the files before changing code."])
    return "\n".join(lines)


def render_overview_markdown(pack: dict[str, Any]) -> str:
    project = pack["project"]
    lines = [
        "# Init Agent Repository Overview",
        "",
        f"Project: `{project['name']}`",
        f"Root: `{project['root']}`",
        f"Git: `{'yes' if project['git'] else 'no'}`",
        f"Branch: `{project['branch'] or '-'}`",
        "",
        "## Suggested first reads",
    ]
    if not pack["suggested_first_reads"]:
        lines.append("-")
    for index, item in enumerate(pack["suggested_first_reads"], start=1):
        lines.append(f"{index}. `{item['path']}`")
        lines.append(f"   - role: {item['role'] or '-'}")
        lines.append(f"   - language: {item['language'] or '-'}")
        for reason in item["reasons"]:
            lines.append(f"   - {reason}")
    lines.extend(["", "## Likely entry points"])
    if not pack["entry_points"]:
        lines.append("-")
    for item in pack["entry_points"]:
        detail = f":{item['line']}" if item.get("line") else ""
        lines.append(f"- `{item['path']}{detail}` {item['kind']} `{item['name']}`")
    lines.extend(["", "## Package manifests and config"])
    if not pack["manifests"]:
        lines.append("-")
    for item in pack["manifests"]:
        lines.append(f"- `{item['path']}`")
    lines.extend(["", "## Major subsystems"])
    if not pack["subsystems"]:
        lines.append("-")
    for item in pack["subsystems"]:
        languages = ", ".join(item["languages"]) if item["languages"] else "-"
        roles = ", ".join(item["roles"]) if item["roles"] else "-"
        lines.append(f"- `{item['path_prefix']}`: {item['files']} files; languages: {languages}; roles: {roles}")
    lines.extend(["", "_Heuristic overview. Verify by reading files before changing code._"])
    return "\n".join(lines)


def _rank_first_reads(files: list[dict[str, Any]], symbol_by_file: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    ranked = []
    for file_item in files:
        path = str(file_item["path"])
        score, reasons = _file_overview_score(path, str(file_item.get("role") or ""), symbol_by_file.get(path, []))
        if score <= 0:
            continue
        ranked.append(
            {
                "path": path,
                "score": round(score, 2),
                "language": file_item.get("language"),
                "role": file_item.get("role"),
                "reasons": reasons[:5],
            }
        )
    ranked.sort(key=lambda item: (-float(item["score"]), _path_depth(str(item["path"])), str(item["path"])))
    return ranked


def _file_overview_score(path: str, role: str, symbols: list[dict[str, Any]]) -> tuple[float, list[str]]:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    lower_name = name.lower()
    lower_path = normalized.lower()
    parts = {part.lower() for part in Path(normalized).parts}
    score = 0.0
    reasons: list[str] = []

    depth = _path_depth(normalized)
    if name in MANIFEST_NAMES:
        if depth == 1:
            score += 12
            reasons.append("package manifest")
        else:
            score += 4
            reasons.append("nested package manifest")
    if name in README_NAMES or lower_name.startswith("readme."):
        if depth == 1:
            score += 9
            reasons.append("project README")
        else:
            score += 4
            reasons.append("nested README")
    if name in CONFIG_NAMES:
        score += 4
        reasons.append("configuration file")
    elif role == "config":
        score += 2
        reasons.append("indexed config file")
    if name in ENTRY_FILENAMES:
        score += 8
        reasons.append("conventional entry-point filename")
    if parts.intersection(ENTRY_PARTS):
        score += 4
        reasons.append("entry-point path segment")
    if role == "route":
        score += 5
        reasons.append("route file")
    if role in {"asset", "migration"}:
        score -= 3
        reasons.append(f"{role} files are secondary for overview")

    has_project_script = False
    has_package_script = False
    has_route = False
    entry_symbols: list[str] = []
    for symbol in symbols:
        kind = str(symbol.get("kind") or "")
        name_value = str(symbol.get("name") or "")
        if kind == "project_script":
            has_project_script = True
        elif kind == "package_script":
            has_package_script = True
        elif kind == "route":
            has_route = True
        elif kind in {"class", "function", "struct", "impl"} and _entry_name_hint(name_value):
            entry_symbols.append(name_value)

    if has_project_script:
        score += 4
        reasons.append("declares project script")
    if has_package_script:
        score += 3
        reasons.append("declares package script")
    if has_route and role != "test":
        score += 3
        reasons.append("declares routes")
    if entry_symbols:
        score += 7
        reasons.append(f"defines likely entry symbol {entry_symbols[0]}")

    if "/src/" in lower_path or lower_path.startswith("src/"):
        score += 1
    if "/docs/" in lower_path or lower_path.startswith("docs/"):
        score -= 2
    if role == "test":
        score *= 0.2
        reasons.append("test files are secondary for overview")
    return score, list(dict.fromkeys(reasons))


def _entry_points(files: list[dict[str, Any]], symbol_by_file: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    entries = []
    for file_item in files:
        path = str(file_item["path"])
        name = Path(path).name
        role = str(file_item.get("role") or "")
        for symbol in symbol_by_file.get(path, []):
            kind = str(symbol.get("kind") or "")
            symbol_name = str(symbol.get("name") or "")
            if role == "test" and kind == "route":
                continue
            if kind in {"project_script", "package_script", "route"} or _entry_name_hint(symbol_name):
                entries.append(
                    {
                        "path": path,
                        "name": symbol_name,
                        "kind": kind,
                        "line": symbol.get("line") or 0,
                    }
                )
        if name in ENTRY_FILENAMES:
            entries.append({"path": path, "name": name, "kind": "file", "line": 0})
    entries.sort(key=lambda item: (_entry_priority(item), _path_depth(str(item["path"])), str(item["path"])))
    return _dedupe_entries(entries)


def _manifest_files(files: list[dict[str, Any]], symbol_by_file: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for file_item in files:
        path = str(file_item["path"])
        name = Path(path).name
        lower_name = name.lower()
        role = str(file_item.get("role") or "")
        if name in MANIFEST_NAMES or name in CONFIG_NAMES or lower_name.startswith("readme.") or role == "config":
            result.append(
                {
                    "path": path,
                    "language": file_item.get("language"),
                    "role": file_item.get("role"),
                    "symbols": [
                        {"name": symbol["name"], "kind": symbol["kind"], "line": symbol.get("line") or 0}
                        for symbol in symbol_by_file.get(path, [])[:5]
                    ],
                }
            )
    result.sort(key=lambda item: (_manifest_priority(str(item["path"])), _path_depth(str(item["path"])), str(item["path"])))
    return result


def _subsystems(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for file_item in files:
        path = str(file_item["path"])
        prefix = _subsystem_prefix(path)
        if prefix in SUBSYSTEM_NOISE:
            continue
        group = groups.setdefault(prefix, {"path_prefix": prefix, "files": 0, "languages": Counter(), "roles": Counter()})
        group["files"] += 1
        if file_item.get("language"):
            group["languages"][str(file_item["language"])] += 1
        if file_item.get("role"):
            group["roles"][str(file_item["role"])] += 1
    result = []
    for group in groups.values():
        result.append(
            {
                "path_prefix": group["path_prefix"],
                "files": group["files"],
                "languages": [name for name, _ in group["languages"].most_common(3)],
                "roles": [name for name, _ in group["roles"].most_common(3)],
            }
        )
    result.sort(key=lambda item: (-int(item["files"]), str(item["path_prefix"])))
    return result


def _append_ranked_files(lines: list[str], items: list[dict[str, Any]]) -> None:
    if not items:
        lines.append("-")
        return
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item['path']}")
        lines.append(f"   score: {item['score']:.2f}")
        lines.append(f"   role: {item['role'] or '-'}")
        lines.append(f"   language: {item['language'] or '-'}")
        lines.append("   reasons:")
        for reason in item["reasons"]:
            lines.append(f"   - {reason}")


def _append_entry_points(lines: list[str], items: list[dict[str, Any]]) -> None:
    if not items:
        lines.append("-")
        return
    for item in items:
        detail = f":{item['line']}" if item.get("line") else ""
        lines.append(f"- {item['path']}{detail} {item['kind']} {item['name']}")


def _append_simple_files(lines: list[str], items: list[dict[str, Any]]) -> None:
    if not items:
        lines.append("-")
        return
    for item in items:
        lines.append(f"- {item['path']} ({item['role'] or '-'}, {item['language'] or '-'})")


def _append_subsystems(lines: list[str], items: list[dict[str, Any]]) -> None:
    if not items:
        lines.append("-")
        return
    for item in items:
        languages = ", ".join(item["languages"]) if item["languages"] else "-"
        roles = ", ".join(item["roles"]) if item["roles"] else "-"
        lines.append(f"- {item['path_prefix']}: {item['files']} files; languages: {languages}; roles: {roles}")


def _path_depth(path: str) -> int:
    return len(Path(path).parts)


def _entry_name_hint(name: str) -> bool:
    lower = name.lower()
    return lower in {"main", "app", "application", "server", "serve", "cli", "run"} or lower.endswith("app")


def _entry_priority(item: dict[str, Any]) -> tuple[int, int]:
    kind = str(item.get("kind") or "")
    path = str(item.get("path") or "")
    if kind == "project_script":
        return (0, 0)
    if Path(path).name in ENTRY_FILENAMES:
        return (1, 0)
    if kind == "route":
        return (2, 0)
    if kind == "package_script":
        return (3, 0)
    return (4, 0)


def _manifest_priority(path: str) -> int:
    name = Path(path).name
    if name in {"pyproject.toml", "package.json", "composer.json", "go.mod", "Cargo.toml"}:
        return 0
    if name in README_NAMES or name.lower().startswith("readme."):
        return 1
    if name in MANIFEST_NAMES:
        return 2
    return 3


def _subsystem_prefix(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return "."
    if len(parts) == 1:
        return "."
    if parts[0] in {"src", "lib", "app", "packages", "cmd"} and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result = []
    for entry in entries:
        key = (str(entry["path"]), str(entry["kind"]), str(entry["name"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result
