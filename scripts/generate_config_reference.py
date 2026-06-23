#!/usr/bin/env python3
"""Generate the configuration reference from the live Pydantic schema."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import types
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.aliases import AliasChoices, AliasPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from teai_builder.config.schema import Config, _resolve_tool_config_refs

OUTPUT_PATH = ROOT / "docs" / "configuration-reference.md"


def _anchor_for(model: type[BaseModel]) -> str:
    return model.__name__.lower()


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _format_default(value: Any) -> str:
    if isinstance(value, str):
        return f"`{value}`"
    if value is None:
        return "`null`"
    if isinstance(value, (bool, int, float)):
        return f"`{json.dumps(value)}`"
    if isinstance(value, (list, dict)):
        return f"`{json.dumps(value, ensure_ascii=True)}`"
    return f"`{value!r}`"


def _format_alias_part(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, AliasChoices):
        result: list[str] = []
        for choice in value.choices:
            result.extend(_format_alias_part(choice))
        return result
    if isinstance(value, AliasPath):
        return [".".join(str(part) for part in value.path)]
    return [str(value)]


def _format_aliases(field: Any) -> str:
    names: list[str] = []
    for item in (
        getattr(field, "alias", None),
        getattr(field, "validation_alias", None),
        getattr(field, "serialization_alias", None),
    ):
        for name in _format_alias_part(item):
            if name and name not in names:
                names.append(name)
    if not names:
        return "-"
    return ", ".join(f"`{name}`" for name in names)


def _format_type(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is None:
        if annotation is Any:
            return "Any"
        if annotation is type(None):
            return "`null`"
        if inspect.isclass(annotation):
            if issubclass(annotation, BaseModel):
                return f"[`{annotation.__name__}`](#{_anchor_for(annotation)})"
            return f"`{annotation.__name__}`"
        return f"`{annotation}`"

    if origin in (Union, types.UnionType):
        return " | ".join(_format_type(arg) for arg in get_args(annotation))
    if origin is Literal:
        values = ", ".join(repr(arg) for arg in get_args(annotation))
        return f"`Literal[{values}]`"
    if origin in (list, set, frozenset):
        args = get_args(annotation)
        inner = _format_type(args[0]) if args else "Any"
        return f"`{origin.__name__}`[{inner}]"
    if origin is tuple:
        args = get_args(annotation)
        inner = ", ".join(_format_type(arg) for arg in args) if args else "Any"
        return f"`tuple[{inner}]`"
    if origin is dict:
        key, value = get_args(annotation) or (Any, Any)
        return f"`dict[{_format_type(key)}, {_format_type(value)}]`"

    name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
    args = get_args(annotation)
    if args:
        rendered = ", ".join(_format_type(arg) for arg in args)
        return f"`{name}[{rendered}]`"
    return f"`{name}`"


def _iter_model_types(annotation: Any) -> list[type[BaseModel]]:
    origin = get_origin(annotation)
    if origin is None:
        if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
            return [annotation]
        return []

    result: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        for model in _iter_model_types(arg):
            if model not in result:
                result.append(model)
    return result


def _collect_models(model: type[BaseModel]) -> list[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    ordered: list[type[BaseModel]] = []

    def visit(current: type[BaseModel]) -> None:
        if current in seen:
            return
        seen.add(current)
        ordered.append(current)
        for field in current.model_fields.values():
            for nested in _iter_model_types(field.annotation):
                visit(nested)

    visit(model)
    return ordered


def _section_for(model: type[BaseModel]) -> str:
    lines: list[str] = []
    lines.append(f"## {model.__name__}")
    lines.append("")

    doc = inspect.getdoc(model)
    if doc:
        lines.append(doc.splitlines()[0])
        lines.append("")

    lines.append("| Field | Type | Default | Aliases |")
    lines.append("| --- | --- | --- | --- |")
    for name, field in model.model_fields.items():
        default = "`required`"
        if not field.is_required():
            if field.default_factory is not None:
                factory_name = getattr(field.default_factory, "__name__", field.default_factory.__class__.__name__)
                default = f"`factory:{factory_name}`"
            else:
                default = _format_default(field.default)
        lines.append(
            "| {name} | {typ} | {default} | {aliases} |".format(
                name=f"`{name}`",
                typ=_escape(_format_type(field.annotation)),
                default=_escape(default),
                aliases=_escape(_format_aliases(field)),
            )
        )
    lines.append("")
    return "\n".join(lines)


def build_document() -> str:
    _resolve_tool_config_refs()
    models = _collect_models(Config)
    sections = "\n".join(_section_for(model) for model in models)
    return "\n".join(
        [
            "<!-- Generated by scripts/generate_config_reference.py. Do not edit by hand. -->",
            "# Configuration Reference",
            "",
            "This file is generated from `teai_builder/config/schema.py`.",
            "",
            "- Regenerate: `python scripts/generate_config_reference.py`",
            "- Verify freshness: `python scripts/generate_config_reference.py --check`",
            "- Environment prefix: `TEAI_BUILDER_` with `__` for nested keys",
            "",
            "## Scope",
            "",
            "The root config model is [`Config`](#config). Nested sections document the",
            "current schema used by the CLI, gateway, API server, and WebUI settings APIs.",
            "",
            sections.rstrip(),
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the generated file is out of date")
    args = parser.parse_args()

    content = build_document()
    current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else None

    if args.check:
        if current != content:
            print(f"{OUTPUT_PATH} is out of date. Run python scripts/generate_config_reference.py", file=sys.stderr)
            return 1
        print(f"{OUTPUT_PATH} is up to date.")
        return 0

    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
