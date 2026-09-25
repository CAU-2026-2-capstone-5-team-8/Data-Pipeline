"""Deterministic canonical identifiers and content hashes."""

import hashlib
import json
import unicodedata
from typing import Any


def sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def sha256_bytes(value: bytes) -> str:
    """Hash raw binary evidence without a lossy text conversion."""
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(encoded)


def stable_id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(parts)
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def normalize_bibliographic_text(value: str) -> str:
    """Normalize text for matching while preserving Unicode and technical symbols."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: list[str] = []
    for character in normalized:
        if character.isalnum():
            tokens.append(character)
        elif character == "+":
            tokens.append(" plus ")
        elif character == "#":
            tokens.append(" sharp ")
        else:
            tokens.append(" ")
    return " ".join("".join(tokens).split())


def is_valid_isbn_10(value: str) -> bool:
    """Return whether a normalized ISBN-10 has a valid check digit."""
    if len(value) != 10 or not value[:9].isdigit() or not (value[-1].isdigit() or value[-1] == "X"):
        return False
    digits = [int(character) for character in value[:9]]
    digits.append(10 if value[-1] == "X" else int(value[-1]))
    return sum((10 - index) * digit for index, digit in enumerate(digits)) % 11 == 0


def isbn_10_to_13(value: str) -> str:
    """Return the 978-prefixed ISBN-13 that a normalized ISBN-10 identifies."""
    stem = f"978{value[:9]}"
    total = sum((1 if index % 2 == 0 else 3) * int(stem[index]) for index in range(12))
    return f"{stem}{(10 - total % 10) % 10}"


def is_valid_isbn_13(value: str) -> bool:
    """Return whether a normalized ISBN-13 has a valid check digit."""
    if len(value) != 13 or not value.isdigit():
        return False
    total = sum((1 if index % 2 == 0 else 3) * int(value[index]) for index in range(12))
    return (10 - total % 10) % 10 == int(value[-1])
