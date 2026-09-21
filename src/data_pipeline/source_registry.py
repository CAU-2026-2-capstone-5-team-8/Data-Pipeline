"""Generic JSON-backed loader for curated, version-controlled source allowlists.

Each allowlist entry (one exact-edition publisher page, open textbook, etc.) lives in
its own JSON file under configs/sources/<kind>/<slug>.json instead of being a Python
dict literal. The frozen dataclasses that describe each source kind stay in their
existing modules (publisher_sources.py, open_textbook_sources.py, ...); only the data
moves here. Adding one book is therefore a config file addition/PR, not a code change.
"""

import dataclasses
import json
import types
import typing
from pathlib import Path
from typing import Any


def _coerce(value: Any, annotation: Any) -> Any:
    """Convert one JSON-decoded value into the shape a dataclass field expects."""
    if value is None:
        return None
    origin = typing.get_origin(annotation)
    if origin is tuple:
        if not isinstance(value, list):
            raise TypeError(f"expected a JSON array for {annotation!r}, got {type(value).__name__}")
        args = typing.get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_coerce(item, args[0]) for item in value)
        if len(args) != len(value):
            raise TypeError(f"expected {len(args)} items for {annotation!r}, got {len(value)}")
        return tuple(_coerce(item, arg) for item, arg in zip(value, args, strict=True))
    if origin in (typing.Union, types.UnionType):
        non_none = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _coerce(value, non_none[0]) if len(non_none) == 1 else value
    if dataclasses.is_dataclass(annotation) and isinstance(value, dict):
        return _build(annotation, value)
    return value


def _build[T](cls: type[T], data: dict[str, Any]) -> T:
    """Construct one frozen dataclass instance from its JSON-decoded field dict."""
    hints = typing.get_type_hints(cls)
    kwargs = {
        name: _coerce(data[name], annotation) for name, annotation in hints.items() if name in data
    }
    unknown = set(data) - set(hints)
    if unknown:
        raise ValueError(f"{cls.__name__} config has unknown fields: {sorted(unknown)}")
    return cls(**kwargs)


def load_registry_dir[T](cls: type[T], directory: Path) -> dict[str, T]:
    """Load every `<slug>.json` file in a directory into `{slug: cls(...)}`.

    The dataclass must declare a `slug` field. Each file's stem must equal that
    field's value, so a rename is never silently ignored.
    """
    registry: dict[str, T] = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        spec = _build(cls, data)
        slug = spec.slug
        if path.stem != slug:
            raise ValueError(f"source file {path.name} does not match its slug {slug!r}")
        if slug in registry:
            raise ValueError(f"duplicate source slug: {slug}")
        registry[slug] = spec
    return registry
