"""Exact-integer wire codec tests (pure stdlib)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.exact_json import (  # noqa: E402
    ExactJSONError,
    decode_exact_json,
    encode_exact_json,
)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_roundtrip_huge_integers():
    payload = {
        "points": [
            {"id": "p0", "x": 9007199254740992, "y": 0},
            {"id": "p1", "x": 9007199254740993, "y": 0},
            {"id": "p2", "x": 9007199254740994, "y": 2},
        ],
        "min_cell_area": 2,
        "max_outliers": 0,
    }
    raw = encode_exact_json(payload)
    text = raw.decode("utf-8")
    # Adjacent integers beyond 2**53 must survive as distinct quoted digits.
    check("9007199254740993" in text, "digits survive serialization")
    back = decode_exact_json(raw)
    check(back == payload, f"exact round trip lost information: {back}")
    xs = {p["x"] for p in back["points"]}
    check(len(xs) == 3, "adjacent huge integers stay distinct")


def test_wire_uses_tags_not_bare_numbers():
    raw = encode_exact_json({"x": 123456789012345678901234567890})
    check(b'{"@type": "int", "value": "123456789012345678901234567890"}' in raw,
          "integer is tagged on the wire")


def test_bare_numbers_rejected():
    for body in (b'{"x": 1}', b'{"x": 1.5}', b'[1, 2]', b'{"x": 1e3}'):
        try:
            decode_exact_json(body)
        except ExactJSONError:
            continue
        raise AssertionError(f"bare number payload accepted: {body}")


def test_malformed_tags_rejected():
    bad = [
        b'{"x": {"@type": "int", "value": "1.5"}}',
        b'{"x": {"@type": "int", "value": "abc"}}',
        b'{"x": {"@type": "big", "value": "1"}}',
        b'{"x": {"@type": "int", "value": true}}',
        b'{"x": {"@type": "int"}}',
        b'{"x": {"@type": "int", "value": "1", "extra": 2}}',
    ]
    for body in bad:
        try:
            decode_exact_json(body)
        except ExactJSONError:
            continue
        raise AssertionError(f"malformed tag accepted: {body}")


def test_booleans_and_strings_pass():
    check(decode_exact_json(b'{"feasible": true, "reason": "x"}') ==
          {"feasible": True, "reason": "x"}, "plain bool/string response decodes")
    check(encode_exact_json({"feasible": True}) == b'{"feasible": true}',
          "booleans serialize without a tag")


def test_negative_and_zero_normalization():
    check(decode_exact_json(b'{"x": {"@type": "int", "value": "-0"}}') == {"x": 0},
          "-0 is the integer zero")
    check(decode_exact_json(b'{"x": {"@type": "int", "value": "-42"}}') == {"x": -42},
          "negative integers decode")


def test_float_results_are_not_serializable():
    try:
        encode_exact_json({"area": 2.0})
    except ExactJSONError:
        pass
    else:
        raise AssertionError("float result must not cross the exact boundary")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
