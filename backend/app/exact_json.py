"""Exact-integer JSON boundary for the audit API.

Python integers have arbitrary precision, but the JSON *number* type does
not survive a round trip through a JavaScript ``Number``: every integer with
absolute value above 2**53 is silently rounded when the browser parses the
response (``JSON.parse``) and again when the request is built.  The frontend
must compare coordinates for uniqueness, re-derive lattice memberships and
re-audit edited inputs, so no business integer may lose digits on the wire.

The exact boundary therefore carries every integer as a tagged string
object ``{"@type": "int", "value": "<canonical decimal digits>"}``.  The
tag survives JSON serialization in both directions verbatim; the real
arbitrary-precision Python ``int`` is reconstructed *before* validation and
solving, and every integer in a response is re-tagged *after* solving.

Booleans are rejected explicitly: without that, ``{"@type": "int", ...}``
membership checks on ``True`` would misbehave and ``isinstance(x, int)``
in the solver accepts ``bool``.

Untagged plain-number payloads are deliberately rejected: accepting them
would make precision loss possible again by simply omitting the tags.
"""

from __future__ import annotations

import json
from typing import Any

INT_TAG = "@type"
INT_TAG_VALUE = "int"
INT_VALUE = "value"


class ExactJSONError(ValueError):
    """Raised when a payload violates the tagged-integer wire contract."""


def _parse_int_literal(token: str, *, what: str) -> int:
    """Parse a JSON integer literal, rejecting floats and truncation."""
    s = token.strip()
    if not s or s == "-":
        raise ExactJSONError(f"{what} is not an integer")
    if s[0] in "+-":
        digits = s[1:]
    else:
        digits = s
    if not digits.isascii() or not digits.isdigit():
        raise ExactJSONError(f"{what} must be an integer, got {token!r}")
    return int(s)


def decode_exact_json(raw: bytes | str) -> Any:
    """Parse a JSON request body, requiring tagged big integers.

    Integers anywhere in the document must use the ``{"@type": "int",
    "value": "..."}`` marker; bare JSON numbers are rejected so that no
    precision-limited value can enter the exact pipeline.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExactJSONError(f"request body is not valid UTF-8: {exc}")
    else:
        text = raw
    try:
        tree = json.loads(text, parse_int=lambda t: _raise_number(t), parse_float=_raise_number)
    except ExactJSONError:
        raise
    except json.JSONDecodeError as exc:
        raise ExactJSONError(f"malformed JSON: {exc.msg}")
    return _untag(tree, path="$")


def _raise_number(token: str) -> Any:
    raise ExactJSONError(
        f"bare JSON number {token!r} is not allowed on the exact integer "
        "boundary; use {\"@type\": \"int\", \"value\": \"...\"}"
    )


def _untag(node: Any, path: str) -> Any:
    # bool is a subclass of int -- check first.  Requests carry no
    # booleans, but the same decoder may be used to inspect a response
    # (e.g. "feasible"), where they are part of normal JSON.
    if isinstance(node, bool):
        return node
    if isinstance(node, int):
        # parse_int always raises; this only guards custom decoders.
        raise ExactJSONError(f"bare integer at {path} must use the int tag")
    if isinstance(node, float):
        raise ExactJSONError(f"bare number at {path} must use the int tag")
    if isinstance(node, str) or node is None:
        return node
    if isinstance(node, list):
        return [_untag(v, f"{path}[{i}]") for i, v in enumerate(node)]
    if isinstance(node, dict):
        tag = node.get(INT_TAG)
        if tag is not None:
            if tag != INT_TAG_VALUE:
                raise ExactJSONError(
                    f"unknown {INT_TAG!r} marker {tag!r} at {path}"
                )
            if set(node) != {INT_TAG, INT_VALUE}:
                raise ExactJSONError(
                    f"tagged integer at {path} must contain exactly "
                    f"{INT_TAG!r} and {INT_VALUE!r}"
                )
            token = node[INT_VALUE]
            if not isinstance(token, str):
                raise ExactJSONError(
                    f"tagged integer value at {path} must be a decimal string"
                )
            return _parse_int_literal(token, what=f"tagged integer at {path}")
        return {k: _untag(v, f"{path}.{k}") for k, v in node.items()}
    raise ExactJSONError(f"unsupported JSON value at {path}: {type(node)!r}")


def encode_exact_json(obj: Any) -> bytes:
    """Serialize a solver response, tagging every integer exactly."""
    return json.dumps(_tag(obj), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _tag(node: Any) -> Any:
    # bool is a subclass of int, so check it first: booleans round-trip
    # through JSON natively and need no integer tag.
    if isinstance(node, bool):
        return node
    if isinstance(node, int):
        return {INT_TAG: INT_TAG_VALUE, INT_VALUE: str(node)}
    if isinstance(node, float):
        raise ExactJSONError(
            "floating-point results are not representable on the exact "
            "integer boundary"
        )
    if isinstance(node, str) or node is None:
        return node
    if isinstance(node, list):
        return [_tag(v) for v in node]
    if isinstance(node, dict):
        return {k: _tag(v) for k, v in node.items()}
    if isinstance(node, tuple):
        return [_tag(v) for v in node]
    raise ExactJSONError(f"cannot serialize {type(node)!r} exactly")
