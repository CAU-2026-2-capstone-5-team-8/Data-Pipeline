"""Generic JSON-backed loader for curated, version-controlled source allowlists.

Each allowlist entry (one exact-edition publisher page, open textbook, etc.) lives in
its own JSON file under configs/sources/<kind>/<slug>.json instead of being a Python
dict literal. The frozen dataclasses that describe each source kind stay in their
existing modules (publisher_sources.py, open_textbook_sources.py, ...); only the data
moves here. Adding one book is therefore a config file addition/PR, not a code change.
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter


def _build[T](cls: type[T], data: dict[str, Any]) -> T:
    """Validate and construct one dataclass from its JSON-decoded field dict."""
    fields = {field.name for field in dataclasses.fields(cls)}
    unknown = set(data) - fields
    if unknown:
        raise ValueError(f"{cls.__name__} config has unknown fields: {sorted(unknown)}")
    return TypeAdapter(cls).validate_python(data)


def config_path(*parts: str) -> Path:
    """Resolve configuration in a source checkout or an installed wheel."""
    package_root = Path(__file__).resolve().parent / "configs"
    repository_root = Path(__file__).resolve().parents[2] / "configs"
    root = package_root if package_root.is_dir() else repository_root
    return root.joinpath(*parts)


def load_registry_dir[T](cls: type[T], directory: Path) -> dict[str, T]:
    """Load every `<slug>.json` file in a directory into `{slug: cls(...)}`.

    The dataclass must declare a `slug` field. Each file's stem must equal that
    field's value, so a rename is never silently ignored.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"source config directory not found: {directory}")
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
    if not registry:
        raise ValueError(f"source config directory has no entries: {directory}")
    return registry
