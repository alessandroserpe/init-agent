"""Small extension-based language and role detection."""

from __future__ import annotations

from pathlib import Path


LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".php": "php",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".sh": "shell",
    ".bat": "batch",
    ".ps1": "powershell",
    ".go": "go",
    ".rs": "rust",
}

ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
}

CONFIG_NAMES = {
    "pyproject.toml",
    "package.json",
    "composer.json",
    "tsconfig.json",
    "vite.config.js",
    "webpack.config.js",
    "dockerfile",
    ".env",
    ".gitignore",
}


def detect_language(path: str | Path) -> str:
    file_path = Path(path)
    return LANGUAGE_BY_EXTENSION.get(file_path.suffix.lower(), "unknown")


def detect_role(path: str | Path) -> str:
    file_path = Path(path)
    lower = file_path.as_posix().lower()
    name = file_path.name.lower()
    suffix = file_path.suffix.lower()

    if name in CONFIG_NAMES or "config" in name or suffix in {".toml", ".yaml", ".yml", ".json"}:
        return "config"
    if name.startswith("readme") or suffix in {".md", ".rst"} or "/docs/" in lower:
        return "documentation"
    if suffix in ASSET_EXTENSIONS:
        return "asset"
    if _is_test_path(file_path):
        return "test"
    if "migration" in lower or "/migrations/" in lower:
        return "migration"
    if "route" in lower or "/routes/" in lower:
        return "route"
    if "/views/" in lower or "/templates/" in lower or suffix in {".html", ".tsx", ".jsx"}:
        return "view"
    if suffix in {".py", ".php", ".js", ".jsx", ".ts", ".tsx", ".sql", ".sh", ".go", ".rs"}:
        return "source"
    return "unknown"


def _is_test_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    stem = path.stem.lower()
    if parts.intersection({"test", "tests", "testing", "__tests__"}):
        return True
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go") or name.endswith("_test.rs"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    if stem.endswith(".test") or stem.endswith(".spec"):
        return True
    return False
