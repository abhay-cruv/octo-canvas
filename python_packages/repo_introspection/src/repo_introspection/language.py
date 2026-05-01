"""Pick the primary language by counting recognised file extensions."""

from collections import Counter

LANGUAGE_BY_EXT: dict[str, str] = {
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".py": "Python",
    ".rs": "Rust",
    ".go": "Go",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
}

_VENDOR_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "vendor",
        "dist",
        "build",
        "target",
        ".git",
        ".next",
        "__pycache__",
    }
)


def _is_vendor(path: str) -> bool:
    parts = path.split("/")
    return any(p in _VENDOR_DIRS for p in parts)


def detect_primary_language(paths: set[str]) -> str | None:
    """Pick the language with the most files. Tie → alphabetical.

    Vendor-dir files (`node_modules/...`, `.venv/...`, `dist/...`, etc.) are
    ignored so a checked-in dependency tree doesn't dominate the count.
    """
    counts: Counter[str] = Counter()
    for p in paths:
        if _is_vendor(p):
            continue
        idx = p.rfind(".")
        if idx == -1:
            continue
        ext = p[idx:].lower()
        lang = LANGUAGE_BY_EXT.get(ext)
        if lang is not None:
            counts[lang] += 1
    if not counts:
        return None
    top = max(counts.values())
    winners = sorted(lang for lang, n in counts.items() if n == top)
    return winners[0]
