"""Workspace-scoped search payloads for the WebUI."""

from __future__ import annotations

import ast
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from teai_builder.security.workspace_access import WorkspaceScope

_IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}

DEFAULT_WORKSPACE_SEARCH_LIMIT = 40
MAX_WORKSPACE_SEARCH_LIMIT = 100
MAX_WORKSPACE_SEARCH_SCAN = 20_000
DEFAULT_WORKSPACE_CONTENT_SEARCH_LIMIT = 40
MAX_WORKSPACE_CONTENT_SEARCH_LIMIT = 100
MAX_WORKSPACE_CONTENT_MATCHES = 300
MAX_WORKSPACE_CONTENT_FILE_BYTES = 256 * 1024
DEFAULT_WORKSPACE_SYMBOL_SEARCH_LIMIT = 40
MAX_WORKSPACE_SYMBOL_SEARCH_LIMIT = 100
MAX_WORKSPACE_SYMBOLS = 3_000
MAX_WORKSPACE_SYMBOL_FILE_BYTES = 256 * 1024
DEFAULT_WORKSPACE_REFERENCE_SEARCH_LIMIT = 40
MAX_WORKSPACE_REFERENCE_SEARCH_LIMIT = 100
MAX_WORKSPACE_REFERENCE_SYMBOL_CANDIDATES = 24
MAX_WORKSPACE_REFERENCE_MATCHES = 400
DEFAULT_WORKSPACE_PROBLEMS_LIMIT = 40
MAX_WORKSPACE_PROBLEMS_LIMIT = 100
MAX_WORKSPACE_PROBLEMS = 400

_SYMBOL_KIND_PRIORITY = {
    "class": 46,
    "function": 42,
    "method": 40,
    "interface": 38,
    "enum": 36,
    "struct": 35,
    "trait": 34,
    "type": 32,
    "module": 30,
    "constant": 26,
}


def workspace_search_payload(
    *,
    scope: WorkspaceScope,
    query: str = "",
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
) -> dict[str, Any]:
    """Return fuzzy-ranked file matches for quick-open inside one workspace."""

    workspace_root = scope.project_path.resolve(strict=False)
    sanitized_limit = max(1, min(limit, MAX_WORKSPACE_SEARCH_LIMIT))
    normalized_query = " ".join(query.strip().lower().split())
    terms = [term for term in re.split(r"\s+", normalized_query) if term]

    entries, scanned_files, truncated = _collect_workspace_files(workspace_root)
    ranked: list[tuple[int, str, str, str]] = []

    for rel_path, path, filename in entries:
        score = _score_path_match(rel_path, filename, terms)
        if score is None:
            continue
        ranked.append((score, rel_path, str(path), filename))

    ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1].lower()))
    items = [
        {
            "path": abs_path,
            "display_path": rel_path,
            "name": name,
            "score": score,
        }
        for score, rel_path, abs_path, name in ranked[:sanitized_limit]
    ]
    return {
        "query": normalized_query,
        "workspace_root": str(workspace_root),
        "items": items,
        "scanned_files": min(scanned_files, MAX_WORKSPACE_SEARCH_SCAN),
        "truncated": truncated,
    }


def workspace_content_search_payload(
    *,
    scope: WorkspaceScope,
    query: str,
    limit: int = DEFAULT_WORKSPACE_CONTENT_SEARCH_LIMIT,
) -> dict[str, Any]:
    """Return ranked content matches inside one workspace."""

    workspace_root = scope.project_path.resolve(strict=False)
    sanitized_limit = max(1, min(limit, MAX_WORKSPACE_CONTENT_SEARCH_LIMIT))
    normalized_query = " ".join(query.strip().lower().split())
    terms = [term for term in re.split(r"\s+", normalized_query) if term]
    entries, scanned_files, truncated = _collect_workspace_files(workspace_root)

    if not terms:
        return {
            "query": normalized_query,
            "workspace_root": str(workspace_root),
            "items": [],
            "scanned_files": scanned_files,
            "truncated": truncated,
        }

    ranked: list[tuple[int, dict[str, Any]]] = []
    for rel_path, path, filename in entries:
        for match in _content_matches_for_file(path, rel_path, filename, terms):
            ranked.append((match["score"], match))
            if len(ranked) >= MAX_WORKSPACE_CONTENT_MATCHES:
                truncated = True
                break
        if len(ranked) >= MAX_WORKSPACE_CONTENT_MATCHES:
            break

    ranked.sort(
        key=lambda item: (
            -item[0],
            len(item[1]["display_path"]),
            item[1]["line"],
            item[1]["display_path"].lower(),
        )
    )
    return {
        "query": normalized_query,
        "workspace_root": str(workspace_root),
        "items": [item for _, item in ranked[:sanitized_limit]],
        "scanned_files": scanned_files,
        "truncated": truncated,
    }


def workspace_symbol_search_payload(
    *,
    scope: WorkspaceScope,
    query: str = "",
    limit: int = DEFAULT_WORKSPACE_SYMBOL_SEARCH_LIMIT,
) -> dict[str, Any]:
    """Return ranked symbol matches inside one workspace."""

    workspace_root = scope.project_path.resolve(strict=False)
    sanitized_limit = max(1, min(limit, MAX_WORKSPACE_SYMBOL_SEARCH_LIMIT))
    normalized_query = " ".join(query.strip().lower().split())
    terms = [term for term in re.split(r"\s+", normalized_query) if term]
    entries, scanned_files, truncated = _collect_workspace_files(workspace_root)

    ranked: list[tuple[int, dict[str, Any]]] = []
    for rel_path, path, filename in entries:
        for symbol in _symbols_for_file(path, rel_path, filename):
            score = _score_symbol_match(symbol, terms)
            if score is None:
                continue
            ranked.append((score, {**symbol, "score": score}))
            if len(ranked) >= MAX_WORKSPACE_SYMBOLS:
                truncated = True
                break
        if len(ranked) >= MAX_WORKSPACE_SYMBOLS:
            break

    ranked.sort(
        key=lambda item: (
            -item[0],
            len(item[1]["display_path"]),
            item[1]["line"],
            item[1]["name"].lower(),
            item[1]["display_path"].lower(),
        )
    )
    return {
        "query": normalized_query,
        "workspace_root": str(workspace_root),
        "items": [item for _, item in ranked[:sanitized_limit]],
        "scanned_files": scanned_files,
        "truncated": truncated,
    }


def workspace_reference_search_payload(
    *,
    scope: WorkspaceScope,
    query: str,
    limit: int = DEFAULT_WORKSPACE_REFERENCE_SEARCH_LIMIT,
) -> dict[str, Any]:
    """Return ranked cross-workspace references for matching symbols."""

    workspace_root = scope.project_path.resolve(strict=False)
    sanitized_limit = max(1, min(limit, MAX_WORKSPACE_REFERENCE_SEARCH_LIMIT))
    normalized_query = " ".join(query.strip().lower().split())
    terms = [term for term in re.split(r"\s+", normalized_query) if term]
    entries, scanned_files, truncated = _collect_workspace_files(workspace_root)

    if not terms:
        return {
            "query": normalized_query,
            "workspace_root": str(workspace_root),
            "items": [],
            "scanned_files": scanned_files,
            "truncated": truncated,
        }

    symbol_candidates = _reference_symbol_candidates(entries, terms)
    if len(symbol_candidates) >= MAX_WORKSPACE_REFERENCE_SYMBOL_CANDIDATES:
        truncated = True

    ranked: list[tuple[int, dict[str, Any]]] = []
    for rel_path, path, filename in entries:
        for match in _reference_matches_for_file(
            path=path,
            rel_path=rel_path,
            filename=filename,
            symbol_candidates=symbol_candidates,
        ):
            ranked.append((match["score"], match))
            if len(ranked) >= MAX_WORKSPACE_REFERENCE_MATCHES:
                truncated = True
                break
        if len(ranked) >= MAX_WORKSPACE_REFERENCE_MATCHES:
            break

    ranked.sort(
        key=lambda item: (
            -item[0],
            len(item[1]["display_path"]),
            item[1]["line"],
            item[1]["name"].lower(),
            item[1]["display_path"].lower(),
        )
    )
    return {
        "query": normalized_query,
        "workspace_root": str(workspace_root),
        "items": [item for _, item in ranked[:sanitized_limit]],
        "scanned_files": scanned_files,
        "truncated": truncated,
    }


def workspace_problems_payload(
    *,
    scope: WorkspaceScope,
    query: str = "",
    limit: int = DEFAULT_WORKSPACE_PROBLEMS_LIMIT,
) -> dict[str, Any]:
    """Return ranked workspace diagnostics for parse and merge-conflict issues."""

    workspace_root = scope.project_path.resolve(strict=False)
    sanitized_limit = max(1, min(limit, MAX_WORKSPACE_PROBLEMS_LIMIT))
    normalized_query = " ".join(query.strip().lower().split())
    terms = [term for term in re.split(r"\s+", normalized_query) if term]
    entries, scanned_files, truncated = _collect_workspace_files(workspace_root)

    ranked: list[tuple[int, dict[str, Any]]] = []
    for rel_path, path, filename in entries:
        for problem in _diagnostics_for_file(path, rel_path, filename):
            score = _score_problem_match(problem, terms)
            if score is None:
                continue
            ranked.append((score, {**problem, "score": score}))
            if len(ranked) >= MAX_WORKSPACE_PROBLEMS:
                truncated = True
                break
        if len(ranked) >= MAX_WORKSPACE_PROBLEMS:
            break

    ranked.sort(
        key=lambda item: (
            -item[0],
            0 if item[1]["severity"] == "error" else 1,
            len(item[1]["display_path"]),
            item[1]["line"],
            item[1]["display_path"].lower(),
        )
    )
    return {
        "query": normalized_query,
        "workspace_root": str(workspace_root),
        "items": [item for _, item in ranked[:sanitized_limit]],
        "scanned_files": scanned_files,
        "truncated": truncated,
    }


def _is_ignored_dir(name: str) -> bool:
    return name.startswith(".") and name not in {".config", ".github"}


def _collect_workspace_files(
    workspace_root: Path,
) -> tuple[list[tuple[str, Path, str]], int, bool]:
    entries: list[tuple[str, Path, str]] = []
    scanned_files = 0
    truncated = False

    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirnames[:] = sorted(
            [
                name
                for name in dirnames
                if name not in _IGNORED_DIR_NAMES and not _is_ignored_dir(name)
            ],
            key=str.lower,
        )
        filenames.sort(key=str.lower)
        for filename in filenames:
            scanned_files += 1
            if scanned_files > MAX_WORKSPACE_SEARCH_SCAN:
                truncated = True
                break
            path = Path(dirpath) / filename
            try:
                rel_path = path.relative_to(workspace_root).as_posix()
            except ValueError:
                continue
            entries.append((rel_path, path, filename))
        if truncated:
            break

    return entries, min(scanned_files, MAX_WORKSPACE_SEARCH_SCAN), truncated


def _score_path_match(rel_path: str, filename: str, terms: list[str]) -> int | None:
    rel_lower = rel_path.lower()
    name_lower = filename.lower()
    depth = rel_path.count("/")
    extension = Path(filename).suffix.lower()

    if not terms:
        score = 140 - min(depth, 8) * 9 - min(len(rel_path), 120) // 6
        if extension in {".ts", ".tsx", ".py", ".rs", ".js", ".jsx", ".json", ".md"}:
            score += 6
        return score

    score = 0
    for term in terms:
        term_score = _score_single_term(term, rel_lower, name_lower)
        if term_score is None:
            return None
        score += term_score
    score -= min(depth, 8) * 5
    score -= min(len(rel_path), 160) // 10
    return score


def _score_single_term(term: str, rel_lower: str, name_lower: str) -> int | None:
    if name_lower == term:
        return 220
    if rel_lower == term:
        return 210
    if name_lower.startswith(term):
        return 170
    if f"/{term}" in rel_lower or rel_lower.startswith(term):
        return 145
    if term in name_lower:
        return 115
    if term in rel_lower:
        return 90
    fuzzy = _fuzzy_subsequence_bonus(term, rel_lower)
    if fuzzy is None:
        return None
    return fuzzy


def _fuzzy_subsequence_bonus(term: str, rel_lower: str) -> int | None:
    position = -1
    span_start = -1
    last_match = -1
    for char in term:
        position = rel_lower.find(char, position + 1)
        if position == -1:
            return None
        if span_start == -1:
            span_start = position
        last_match = position
    span = max(1, last_match - span_start + 1)
    compactness_bonus = max(0, 70 - span)
    return 55 + compactness_bonus


def _content_matches_for_file(
    path: Path,
    rel_path: str,
    filename: str,
    terms: list[str],
) -> list[dict[str, Any]]:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_WORKSPACE_CONTENT_FILE_BYTES + 1)
    except OSError:
        return []

    if b"\0" in raw[:4096]:
        return []

    preview_bytes = raw[:MAX_WORKSPACE_CONTENT_FILE_BYTES]
    try:
        content = preview_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = preview_bytes.decode("utf-8", errors="replace")

    filename_lower = filename.lower()
    rel_lower = rel_path.lower()
    matches: list[dict[str, Any]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        line_lower = line.lower()
        if any(term not in line_lower for term in terms):
            continue
        column = min(line_lower.find(term) for term in terms) + 1
        matches.append(
            {
                "path": f"{path}:{line_number}",
                "display_path": rel_path,
                "name": filename,
                "line": line_number,
                "column": column,
                "preview": _content_preview(line, column),
                "score": _score_content_match(
                    rel_lower=rel_lower,
                    filename_lower=filename_lower,
                    filename=filename,
                    terms=terms,
                    line_lower=line_lower,
                    line_number=line_number,
                ),
            }
        )
        if len(matches) >= 3:
            break
    return matches


def _score_content_match(
    *,
    rel_lower: str,
    filename_lower: str,
    filename: str,
    terms: list[str],
    line_lower: str,
    line_number: int,
) -> int:
    score = 0
    for term in terms:
        if filename_lower == term:
            score += 180
        elif filename_lower.startswith(term):
            score += 120
        elif term in filename_lower:
            score += 80
        elif term in rel_lower:
            score += 45

    best_column = min(line_lower.find(term) for term in terms)
    if best_column == 0:
        score += 42
    elif best_column > 0:
        score += max(10, 30 - min(best_column, 20))

    extension = Path(filename).suffix.lower()
    if extension in {".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java"}:
        score += 34
    elif extension in {".md", ".rst", ".txt"}:
        score -= 8
    score -= min(line_number, 400) // 8
    score -= min(len(rel_lower), 180) // 12
    return score


def _content_preview(line: str, column: int, max_width: int = 180) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if len(stripped) <= max_width:
        return stripped
    focus = max(0, column - 1)
    start = max(0, focus - max_width // 3)
    end = min(len(stripped), start + max_width)
    if end - start < max_width:
        start = max(0, end - max_width)
    snippet = stripped[start:end]
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(stripped):
        snippet = f"{snippet}..."
    return snippet


def _diagnostics_for_file(path: Path, rel_path: str, filename: str) -> list[dict[str, Any]]:
    content = _read_searchable_text(path, MAX_WORKSPACE_SYMBOL_FILE_BYTES)
    if content is None:
        return []

    diagnostics = _conflict_marker_diagnostics(content, path, rel_path, filename)
    extension = path.suffix.lower()
    if extension == ".py":
        diagnostics.extend(_python_diagnostics(content, path, rel_path, filename))
    elif extension == ".json":
        diagnostics.extend(_json_diagnostics(content, path, rel_path, filename))
    elif extension in {".toml", ".tml"}:
        diagnostics.extend(_toml_diagnostics(content, path, rel_path, filename))
    return diagnostics


def _conflict_marker_diagnostics(
    content: str,
    path: Path,
    rel_path: str,
    filename: str,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped.startswith(("<<<<<<<", "=======", ">>>>>>>")):
            continue
        column = max(1, len(line) - len(stripped) + 1)
        diagnostics.append(
            _problem_item(
                path=path,
                rel_path=rel_path,
                filename=filename,
                message="Merge conflict marker detected.",
                severity="error",
                source="merge",
                line=line_number,
                column=column,
                preview=_content_preview(line, column),
            )
        )
        if len(diagnostics) >= 3:
            break
    return diagnostics


def _python_diagnostics(content: str, path: Path, rel_path: str, filename: str) -> list[dict[str, Any]]:
    try:
        ast.parse(content)
    except SyntaxError as error:
        line = max(1, getattr(error, "lineno", 1) or 1)
        column = max(1, (getattr(error, "offset", 1) or 1))
        source_line = (content.splitlines()[line - 1] if line - 1 < len(content.splitlines()) else "")
        return [
            _problem_item(
                path=path,
                rel_path=rel_path,
                filename=filename,
                message=error.msg or "Python syntax error.",
                severity="error",
                source="python",
                line=line,
                column=column,
                preview=_content_preview(source_line, column),
            )
        ]
    return []


def _json_diagnostics(content: str, path: Path, rel_path: str, filename: str) -> list[dict[str, Any]]:
    try:
        json.loads(content)
    except json.JSONDecodeError as error:
        line = max(1, error.lineno)
        column = max(1, error.colno)
        lines = content.splitlines()
        source_line = lines[line - 1] if line - 1 < len(lines) else ""
        return [
            _problem_item(
                path=path,
                rel_path=rel_path,
                filename=filename,
                message=error.msg or "JSON syntax error.",
                severity="error",
                source="json",
                line=line,
                column=column,
                preview=_content_preview(source_line, column),
            )
        ]
    return []


def _toml_diagnostics(content: str, path: Path, rel_path: str, filename: str) -> list[dict[str, Any]]:
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        line = 1
        column = 1
        message = str(error) or "TOML syntax error."
        location = re.search(r"\(at line (\d+), column (\d+)\)", message)
        if location:
            line = max(1, int(location.group(1)))
            column = max(1, int(location.group(2)))
        lines = content.splitlines()
        source_line = lines[line - 1] if line - 1 < len(lines) else ""
        return [
            _problem_item(
                path=path,
                rel_path=rel_path,
                filename=filename,
                message=message,
                severity="error",
                source="toml",
                line=line,
                column=column,
                preview=_content_preview(source_line, column),
            )
        ]
    return []


def _problem_item(
    *,
    path: Path,
    rel_path: str,
    filename: str,
    message: str,
    severity: str,
    source: str,
    line: int,
    column: int,
    preview: str,
) -> dict[str, Any]:
    return {
        "path": f"{path}:{line}:{column}",
        "display_path": rel_path,
        "name": filename,
        "message": message,
        "severity": severity,
        "source": source,
        "line": line,
        "column": column,
        "preview": preview,
    }


def _symbols_for_file(path: Path, rel_path: str, filename: str) -> list[dict[str, Any]]:
    content = _read_searchable_text(path, MAX_WORKSPACE_SYMBOL_FILE_BYTES)
    if content is None:
        return []

    extension = path.suffix.lower()
    if extension == ".py":
        return _python_symbols(content, path, rel_path)
    if extension in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}:
        return _javascript_like_symbols(content, path, rel_path)
    if extension == ".go":
        return _go_symbols(content, path, rel_path)
    if extension == ".rs":
        return _rust_symbols(content, path, rel_path)
    if extension == ".java":
        return _java_symbols(content, path, rel_path)
    return []


def _reference_symbol_candidates(
    entries: list[tuple[str, Path, str]],
    terms: list[str],
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    for rel_path, path, filename in entries:
        for symbol in _symbols_for_file(path, rel_path, filename):
            score = _score_symbol_match(symbol, terms)
            if score is None:
                continue
            ranked.append((score, {**symbol, "score": score}))
    ranked.sort(
        key=lambda item: (
            -item[0],
            len(item[1]["display_path"]),
            item[1]["line"],
            item[1]["name"].lower(),
        )
    )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for score, symbol in ranked:
        key = (
            str(symbol["name"]).lower(),
            str(symbol.get("container_name") or "").lower(),
            str(symbol["display_path"]).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append({**symbol, "score": score})
        if len(unique) >= MAX_WORKSPACE_REFERENCE_SYMBOL_CANDIDATES:
            break
    return unique


def _reference_matches_for_file(
    *,
    path: Path,
    rel_path: str,
    filename: str,
    symbol_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    content = _read_searchable_text(path, MAX_WORKSPACE_SYMBOL_FILE_BYTES)
    if content is None:
        return []

    extension = path.suffix.lower()
    if extension not in {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".go", ".rs", ".java"}:
        return []

    matches: list[dict[str, Any]] = []
    lines = content.splitlines()
    for line_number, line in enumerate(lines, start=1):
        line_lower = line.lower()
        for symbol in symbol_candidates:
            symbol_name = str(symbol["name"])
            symbol_name_lower = symbol_name.lower()
            if symbol_name_lower not in line_lower:
                continue
            regex = re.compile(rf"(?<![\w$]){re.escape(symbol_name)}(?![\w$])")
            match = regex.search(line)
            if match is None:
                continue
            if str(symbol["display_path"]) == rel_path and int(symbol["line"]) == line_number:
                continue
            column = match.start() + 1
            preview = _content_preview(line, column)
            matches.append(
                {
                    "path": f"{path}:{line_number}:{column}",
                    "display_path": rel_path,
                    "name": symbol_name,
                    "kind": symbol["kind"],
                    "container_name": symbol.get("container_name"),
                    "line": line_number,
                    "column": column,
                    "preview": preview,
                    "definition_path": symbol["path"],
                    "definition_display_path": symbol["display_path"],
                    "score": _score_reference_match(
                        symbol=symbol,
                        rel_path=rel_path,
                        filename=filename,
                        line_lower=line_lower,
                        line_number=line_number,
                        column=column,
                    ),
                }
            )
            if len(matches) >= 4:
                break
        if len(matches) >= 4:
            break
    return matches


def _score_reference_match(
    *,
    symbol: dict[str, Any],
    rel_path: str,
    filename: str,
    line_lower: str,
    line_number: int,
    column: int,
) -> int:
    symbol_name_lower = str(symbol["name"]).lower()
    filename_lower = filename.lower()
    rel_lower = rel_path.lower()
    definition_path = str(symbol["display_path"]).lower()
    score = int(symbol.get("score", 0)) + 25
    if symbol_name_lower == filename_lower.removesuffix(Path(filename_lower).suffix):
        score += 24
    if definition_path == rel_lower:
        score += 18
    if column == 1:
        score += 16
    elif column > 1:
        score += max(6, 22 - min(column, 16))
    if "return" in line_lower or "." in line_lower or "(" in line_lower:
        score += 10
    score -= min(line_number, 400) // 10
    return score


def _score_problem_match(problem: dict[str, Any], terms: list[str]) -> int | None:
    message_lower = str(problem["message"]).lower()
    severity_lower = str(problem["severity"]).lower()
    source_lower = str(problem["source"]).lower()
    preview_lower = str(problem["preview"]).lower()
    rel_lower = str(problem["display_path"]).lower()
    line_number = int(problem["line"])
    depth = rel_lower.count("/")

    if not terms:
        score = 230 if severity_lower == "error" else 170
        if source_lower in {"python", "json", "toml"}:
            score += 18
        if source_lower == "merge":
            score += 10
        score -= min(depth, 8) * 4
        score -= min(line_number, 400) // 14
        return score

    score = 30
    haystack = " ".join([message_lower, severity_lower, source_lower, preview_lower, rel_lower])
    for term in terms:
        if term == severity_lower:
            score += 120
            continue
        if term == source_lower:
            score += 110
            continue
        if term in message_lower:
            score += 95
            continue
        if term in rel_lower:
            score += 72
            continue
        if term in preview_lower:
            score += 55
            continue
        fuzzy = _fuzzy_subsequence_bonus(term, haystack)
        if fuzzy is None:
            return None
        score += fuzzy - 24
    if severity_lower == "error":
        score += 36
    score -= min(depth, 8) * 3
    score -= min(line_number, 400) // 18
    return score


def _read_searchable_text(path: Path, max_bytes: int) -> str | None:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    preview_bytes = raw[:max_bytes]
    try:
        return preview_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return preview_bytes.decode("utf-8", errors="replace")


def _python_symbols(content: str, path: Path, rel_path: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    symbols: list[dict[str, Any]] = []

    def visit(node: ast.AST, containers: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                symbols.append(
                    _symbol_item(
                        path=path,
                        rel_path=rel_path,
                        name=child.name,
                        kind="class",
                        line=child.lineno,
                        column=getattr(child, "col_offset", 0) + 1,
                        container_name=".".join(containers) or None,
                    )
                )
                visit(child, [*containers, child.name])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    _symbol_item(
                        path=path,
                        rel_path=rel_path,
                        name=child.name,
                        kind="method" if containers else "function",
                        line=child.lineno,
                        column=getattr(child, "col_offset", 0) + 1,
                        container_name=".".join(containers) or None,
                    )
                )
                visit(child, [*containers, child.name])
            else:
                visit(child, containers)

    visit(tree, [])
    return symbols


def _javascript_like_symbols(content: str, path: Path, rel_path: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    class_pattern = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)",
        re.MULTILINE,
    )
    for match in class_pattern.finditer(content):
        line, column = _line_column_from_offset(content, match.start("name"))
        class_name = match.group("name")
        symbols.append(
            _symbol_item(
                path=path,
                rel_path=rel_path,
                name=class_name,
                kind="class",
                line=line,
                column=column,
            )
        )
        open_brace = content.find("{", match.end())
        if open_brace == -1:
            continue
        close_brace = _brace_block_end(content, open_brace)
        if close_brace is None:
            continue
        body = content[open_brace + 1 : close_brace]
        body_offset = open_brace + 1
        method_pattern = re.compile(
            r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+)*"
            r"(?P<name>[A-Za-z_$][\w$]*)\s*\([^;\n{}=]*\)\s*\{",
            re.MULTILINE,
        )
        for method_match in method_pattern.finditer(body):
            method_name = method_match.group("name")
            if method_name == "constructor":
                continue
            line, column = _line_column_from_offset(content, body_offset + method_match.start("name"))
            symbols.append(
                _symbol_item(
                    path=path,
                    rel_path=rel_path,
                    name=method_name,
                    kind="method",
                    line=line,
                    column=column,
                    container_name=class_name,
                )
            )

    for kind, pattern in (
        (
            "interface",
            re.compile(r"^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)", re.MULTILINE),
        ),
        (
            "type",
            re.compile(r"^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\b", re.MULTILINE),
        ),
        (
            "enum",
            re.compile(r"^\s*(?:export\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)", re.MULTILINE),
        ),
        (
            "function",
            re.compile(
                r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\(",
                re.MULTILINE,
            ),
        ),
        (
            "function",
            re.compile(
                r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
                r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
                re.MULTILINE,
            ),
        ),
        (
            "function",
            re.compile(
                r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
                r"(?:async\s*)?function\b",
                re.MULTILINE,
            ),
        ),
    ):
        for match in pattern.finditer(content):
            line, column = _line_column_from_offset(content, match.start("name"))
            symbols.append(
                _symbol_item(
                    path=path,
                    rel_path=rel_path,
                    name=match.group("name"),
                    kind=kind,
                    line=line,
                    column=column,
                )
            )

    return _dedupe_symbols(symbols)


def _go_symbols(content: str, path: Path, rel_path: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for kind, pattern in (
        (
            "struct",
            re.compile(r"^\s*type\s+(?P<name>[A-Za-z_]\w*)\s+struct\b", re.MULTILINE),
        ),
        (
            "interface",
            re.compile(r"^\s*type\s+(?P<name>[A-Za-z_]\w*)\s+interface\b", re.MULTILINE),
        ),
        (
            "type",
            re.compile(r"^\s*type\s+(?P<name>[A-Za-z_]\w*)\s+\w+", re.MULTILINE),
        ),
    ):
        for match in pattern.finditer(content):
            line, column = _line_column_from_offset(content, match.start("name"))
            symbols.append(
                _symbol_item(
                    path=path,
                    rel_path=rel_path,
                    name=match.group("name"),
                    kind=kind,
                    line=line,
                    column=column,
                )
            )
    func_pattern = re.compile(
        r"^\s*func\s*(?:\(\s*(?P<receiver>[^)]+)\)\s*)?(?P<name>[A-Za-z_]\w*)\s*\(",
        re.MULTILINE,
    )
    for match in func_pattern.finditer(content):
        receiver = match.group("receiver") or ""
        container_name = None
        if receiver:
            container_match = re.search(r"([A-Za-z_]\w*)\s*$", receiver.replace("*", " "))
            if container_match:
                container_name = container_match.group(1)
        line, column = _line_column_from_offset(content, match.start("name"))
        symbols.append(
            _symbol_item(
                path=path,
                rel_path=rel_path,
                name=match.group("name"),
                kind="method" if container_name else "function",
                line=line,
                column=column,
                container_name=container_name,
            )
        )
    return _dedupe_symbols(symbols)


def _rust_symbols(content: str, path: Path, rel_path: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for kind, pattern in (
        (
            "struct",
            re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ),
        (
            "enum",
            re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ),
        (
            "trait",
            re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?trait\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ),
        (
            "type",
            re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?type\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ),
        (
            "function",
            re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)\s*\(", re.MULTILINE),
        ),
    ):
        for match in pattern.finditer(content):
            line, column = _line_column_from_offset(content, match.start("name"))
            symbols.append(
                _symbol_item(
                    path=path,
                    rel_path=rel_path,
                    name=match.group("name"),
                    kind=kind,
                    line=line,
                    column=column,
                )
            )

    impl_pattern = re.compile(r"^\s*impl(?:<[^>]+>)?\s+(?P<name>[A-Za-z_]\w*)[^{]*\{", re.MULTILINE)
    for match in impl_pattern.finditer(content):
        container_name = match.group("name")
        open_brace = content.find("{", match.end() - 1)
        if open_brace == -1:
            continue
        close_brace = _brace_block_end(content, open_brace)
        if close_brace is None:
            continue
        body = content[open_brace + 1 : close_brace]
        body_offset = open_brace + 1
        for method_match in re.finditer(
            r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)\s*\(",
            body,
            re.MULTILINE,
        ):
            line, column = _line_column_from_offset(content, body_offset + method_match.start("name"))
            symbols.append(
                _symbol_item(
                    path=path,
                    rel_path=rel_path,
                    name=method_match.group("name"),
                    kind="method",
                    line=line,
                    column=column,
                    container_name=container_name,
                )
            )
    return _dedupe_symbols(symbols)


def _java_symbols(content: str, path: Path, rel_path: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for kind, pattern in (
        (
            "class",
            re.compile(r"^\s*(?:public|protected|private|abstract|final|static|\s)+class\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ),
        (
            "interface",
            re.compile(r"^\s*(?:public|protected|private|abstract|static|\s)+interface\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ),
        (
            "enum",
            re.compile(r"^\s*(?:public|protected|private|static|\s)+enum\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ),
        (
            "function",
            re.compile(
                r"^\s*(?:public|protected|private|static|final|synchronized|abstract|\s)+"
                r"[\w<>\[\], ?]+\s+(?P<name>[A-Za-z_]\w*)\s*\(",
                re.MULTILINE,
            ),
        ),
    ):
        for match in pattern.finditer(content):
            line, column = _line_column_from_offset(content, match.start("name"))
            symbols.append(
                _symbol_item(
                    path=path,
                    rel_path=rel_path,
                    name=match.group("name"),
                    kind=kind,
                    line=line,
                    column=column,
                )
            )
    return _dedupe_symbols(symbols)


def _dedupe_symbols(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, int]] = set()
    unique: list[dict[str, Any]] = []
    for symbol in symbols:
        key = (symbol["display_path"], symbol["name"], symbol["line"], symbol["column"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(symbol)
    return unique


def _symbol_item(
    *,
    path: Path,
    rel_path: str,
    name: str,
    kind: str,
    line: int,
    column: int,
    container_name: str | None = None,
) -> dict[str, Any]:
    return {
        "path": f"{path}:{line}:{column}",
        "display_path": rel_path,
        "name": name,
        "kind": kind,
        "container_name": container_name,
        "line": line,
        "column": column,
    }


def _line_column_from_offset(content: str, offset: int) -> tuple[int, int]:
    line = content.count("\n", 0, offset) + 1
    line_start = content.rfind("\n", 0, offset)
    column = offset - line_start
    return line, column


def _brace_block_end(content: str, open_brace: int) -> int | None:
    depth = 0
    for index in range(open_brace, len(content)):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _score_symbol_match(symbol: dict[str, Any], terms: list[str]) -> int | None:
    name_lower = str(symbol["name"]).lower()
    kind_lower = str(symbol["kind"]).lower()
    container_lower = str(symbol.get("container_name") or "").lower()
    path_lower = str(symbol["display_path"]).lower()
    depth = path_lower.count("/")
    line = int(symbol["line"])

    if not terms:
        score = 150 + _SYMBOL_KIND_PRIORITY.get(kind_lower, 18)
        score -= min(depth, 8) * 4
        score -= min(line, 400) // 16
        score -= min(len(name_lower), 80) // 6
        return score

    score = _SYMBOL_KIND_PRIORITY.get(kind_lower, 18)
    for term in terms:
        term_score = _score_symbol_term(
            term,
            name_lower=name_lower,
            kind_lower=kind_lower,
            container_lower=container_lower,
            path_lower=path_lower,
        )
        if term_score is None:
            return None
        score += term_score
    score -= min(depth, 8) * 3
    score -= min(line, 400) // 20
    return score


def _score_symbol_term(
    term: str,
    *,
    name_lower: str,
    kind_lower: str,
    container_lower: str,
    path_lower: str,
) -> int | None:
    if name_lower == term:
        return 240
    if name_lower.startswith(term):
        return 185
    if term in name_lower:
        return 135
    if container_lower == term:
        return 110
    if container_lower.startswith(term):
        return 90
    if term in container_lower:
        return 72
    if term == kind_lower:
        return 55
    if term in path_lower:
        return 48
    fuzzy = _fuzzy_subsequence_bonus(term, name_lower)
    if fuzzy is None:
        return None
    return fuzzy + 12
