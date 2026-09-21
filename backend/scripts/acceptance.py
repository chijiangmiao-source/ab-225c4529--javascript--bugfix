#!/usr/bin/env python3
"""One-shot acceptance check for the compose stack.

Runs:
  1. the pure-stdlib exact-arithmetic unit tests;
  2. HTTP acceptance checks against the running backend and the
     nginx-served frontend (including the nginx -> backend proxy);
  3. an independent exact re-verification of every returned lattice
     membership and the optimum on the standard contamination scenario.

Exits 0 only when everything passes; any failure -> exit 1, so the
`verify` compose service reports the result by its exit code and stops.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import solve  # noqa: E402

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
WEB_URL = os.environ.get("WEB_URL", "http://web:80")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The exact defect-detection command from the regression report (the body of
# `docker compose exec -T backend python -c "..."`).  It checks the built JS
# bundle for the lossy coercions and exits 1 while the collision exists.
DETECTOR_SNIPPET = (
    "import re,sys,urllib.request; from app.solver import solve; "
    "B=9007199254740992; "
    "pts=[{'id':f'p{i}','x':B+i%3,'y':2*(i//3)} for i in range(6)]; "
    "exact=solve({'points':pts,'min_cell_area':2,'max_outliers':0}); "
    "rounded=[dict(p,x=int(float(str(p['x']))),y=int(float(str(p['y'])))) for p in pts]; "
    "html=urllib.request.urlopen('http://web/').read().decode(); "
    "src=re.search(r'src=\"([^\"]+\\.js)\"',html).group(1); "
    "js=urllib.request.urlopen('http://web'+src).read(); "
    "bug=exact['feasible'] and exact['result']['area']==2 and "
    "len({(p['x'],p['y']) for p in pts})==6 and "
    "len({(p['x'],p['y']) for p in rounded})==4 and "
    "b'parseInt(' in js and b'Number(' in js; "
    "print('BUG: frontend collapses 6 unique integer coordinates to 4 before POST' "
    "if bug else 'NOT_REPRODUCED'); sys.exit(1 if bug else 0)"
)

# Redirects the detector's hardcoded http://web hostname at WEB_URL without
# touching any detector logic or assertions.  In compose WEB_URL is
# http://web:80 (same service, same port); outside compose it lets the same
# check run against scripts/dev_proxy.py.
DETECTOR_URL_SHIM = (
    "import urllib.request as _u; _o=_u.urlopen; "
    f"_t={WEB_URL!r}; "
    "_u.urlopen=lambda u,*a,**k:_o(u.replace('http://web',_t),*a,**k)\n"
)


failures = []


def check(cond, msg):
    if cond:
        print(f"  ok  {msg}")
    else:
        print(f"FAIL  {msg}")
        failures.append(msg)


def http_get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def http_post(url, payload, timeout=30):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def http_post_raw(url, payload, timeout=30):
    """POST returning (status, raw_bytes) so wire-level digits are testable."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


SAMPLE_POINTS = [
    {"id": "g0", "x": -4, "y": 0}, {"id": "g1", "x": 0, "y": 0},
    {"id": "g2", "x": 4, "y": 0}, {"id": "g3", "x": 8, "y": 0},
    {"id": "g4", "x": -3, "y": 3}, {"id": "g5", "x": 1, "y": 3},
    {"id": "g6", "x": 5, "y": 3}, {"id": "g7", "x": -1, "y": -3},
    {"id": "g8", "x": 3, "y": -3}, {"id": "g9", "x": 2, "y": 6},
    {"id": "b0", "x": -2, "y": 0}, {"id": "b1", "x": 2, "y": 0},
    {"id": "b2", "x": 1, "y": -3},
]


def verify_membership(result, points, label):
    """Independently re-derive every point from basis + integer coords."""
    h, r = result["basis"]["b1"]
    z, q = result["basis"]["b2"]
    ox, oy = result["origin"]
    check(z == 0, f"[{label}] HNF upper-right entry is 0")
    check(h > 0 and q > 0 and 0 <= r < q, f"[{label}] HNF bounds hold")
    check(result["area"] == h * q, f"[{label}] area equals h*q exactly")
    check(0 <= ox < h and 0 <= oy < q, f"[{label}] canonical origin box")
    by_id = {p["id"]: (p["x"], p["y"]) for p in points}
    out = set(result["outliers"])
    check(len(out) + len(result["retained"]) == len(by_id),
          f"[{label}] retained + outliers partition the input")
    non_collinear = 0
    for item in result["retained"]:
        x, y = by_id[item["id"]]
        m, n = item["coord"]
        check(isinstance(m, int) and isinstance(n, int),
              f"[{label}] {item['id']} has integer coordinates")
        check((ox + h * m, oy + r * m + q * n) == (x, y),
              f"[{label}] {item['id']}: o + m*b1 + n*b2 == pixel point")
    rc = [by_id[i["id"]] for i in result["retained"]]
    p0, p1 = rc[0], rc[1]
    check(
        any((p1[0] - p0[0]) * (p[1] - p0[1]) - (p1[1] - p0[1]) * (p[0] - p0[0]) != 0
            for p in rc[2:]),
        f"[{label}] retained points contain three non-collinear points",
    )


def main():
    print("== 1. exact-arithmetic unit tests ==")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", "test_lattice.py")],
        cwd=ROOT,
    )
    check(proc.returncode == 0, "unit test suite exit code 0")

    print("\n== 2. backend HTTP checks ==")
    status, body = http_get(f"{BACKEND_URL}/health")
    check(status == 200 and '"ok"' in body, "backend /health responds ok")

    print("\n== 3. frontend serving and reverse proxy ==")
    status, body = http_get(f"{WEB_URL}/")
    check(status == 200 and 'id="root"' in body, "nginx serves the SPA shell")
    status, body = http_get(f"{WEB_URL}/health")
    check(status == 200 and '"ok"' in body, "nginx proxies /health to backend")

    print("\n== 4. audit: contaminated mesh -> coarsest area-12 cell ==")
    status, data = http_post(
        f"{BACKEND_URL}/api/audit",
        {"points": SAMPLE_POINTS, "min_cell_area": 12, "max_outliers": 3},
    )
    check(status == 200, "audit endpoint HTTP 200")
    check(data["feasible"] is True, "scenario is feasible")
    r = data["result"]
    check(r["area"] == 12, f"coarsest cell area is 12 (got {r['area']})")
    check(r["outlier_count"] == 3, f"exactly 3 outliers (got {r['outlier_count']})")
    check(r["outliers"] == ["b0", "b1", "b2"],
          f"outlier ids are b0,b1,b2 (got {r['outliers']})")
    check(r["retained_count"] == 10, "all 10 genuine spots retained")
    verify_membership(r, SAMPLE_POINTS, "success")

    print("\n== 5. same request through the nginx proxy ==")
    status, data2 = http_post(
        f"{WEB_URL}/api/audit",
        {"points": SAMPLE_POINTS, "min_cell_area": 12, "max_outliers": 3},
    )
    check(status == 200 and data2["feasible"] and data2["result"]["area"] == 12,
          "proxied audit returns the identical conclusion")

    print("\n== 6. infeasible case: input retained + max-area witness ==")
    tight = [
        {"id": f"p{i}", "x": i - 4, "y": 2 * ((i - 4) % 2)} for i in range(10)
    ]
    status, data = http_post(
        f"{BACKEND_URL}/api/audit",
        {"points": tight, "min_cell_area": 1000, "max_outliers": 3},
    )
    check(status == 200 and data["feasible"] is False, "request is infeasible")
    check(data["witness"] is not None, "a verifiable witness is returned")
    check(data["witness"]["area"] < 1000, "witness area is below the target")
    check(len(data["input"]["points"]) == 10, "the full input is echoed back")
    verify_membership(data["witness"], tight, "witness")

    print("\n== 7. contract validation ==")
    bad_payloads = [
        ({"points": SAMPLE_POINTS[:5], "min_cell_area": 2, "max_outliers": 0},
         "fewer than 6 points rejected"),
        ({"points": SAMPLE_POINTS, "min_cell_area": 1, "max_outliers": 0},
         "min_cell_area < 2 rejected"),
        ({"points": SAMPLE_POINTS, "min_cell_area": 1_000_001, "max_outliers": 0},
         "min_cell_area > 1e6 rejected"),
        ({"points": SAMPLE_POINTS, "min_cell_area": 12, "max_outliers": 4},
         "max_outliers > 3 rejected"),
    ]
    for payload, label in bad_payloads:
        status, _ = http_post(f"{BACKEND_URL}/api/audit", payload)
        check(status == 422, label)

    print("\n== 8. exactness with 10^18-scale coordinates ==")
    B = 10**18
    # 8 points on the area B^2 lattice (B,0),(0,B).
    big = [{"id": f"p{i}", "x": B * m, "y": B * n}
           for i, (m, n) in enumerate(
               [(-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0), (-1, 1), (1, 1)])]
    status, data = http_post(
        f"{BACKEND_URL}/api/audit",
        {"points": big, "min_cell_area": 2, "max_outliers": 0},
    )
    check(status == 200 and data["feasible"], "huge-coordinate case feasible")
    check(data["result"]["area"] == B * B, f"area is exactly B^2={B*B}")
    verify_membership(data["result"], big, "bigint")

    print("\n== 9. exactness at the 2^53 boundary through the real HTTP API ==")
    # 2^53 is the first integer that a JavaScript double cannot distinguish
    # from 2^53+1.  The frontend used to round these before POSTing; the
    # backend HTTP boundary must accept the six distinct integers and solve
    # them exactly.
    B53 = 2**53
    boundary = [
        {"id": f"p{i}", "x": B53 + i % 3, "y": 2 * (i // 3)} for i in range(6)
    ]

    # Independent in-process exact answer for the same raw integer point set.
    exact = solve({"points": boundary, "min_cell_area": 2, "max_outliers": 0})
    check(exact["feasible"], "raw 2^53-boundary points are feasible in-process")
    check(exact["result"]["area"] == 2, "in-process exact area is 2")
    check(exact["result"]["outlier_count"] == 0, "in-process exact outliers are 0")
    check(len({(p["x"], p["y"]) for p in boundary}) == 6,
          "the six input integers are pairwise distinct")

    # Same data through the real HTTP endpoint (not a direct solve-only
    # check): no duplicate-coordinates 422, exact area/zero-outlier result.
    status, raw = http_post_raw(
        f"{BACKEND_URL}/api/audit",
        {"points": boundary, "min_cell_area": 2, "max_outliers": 0},
    )
    check(status == 200, "boundary points accepted over HTTP (no duplicate 422)")
    check(b"9007199254740992" in raw and b"9007199254740993" in raw
          and b"9007199254740994" in raw,
          "raw response bytes carry all three distinct >2^53 integer digits")
    wire = json.loads(raw.decode("utf-8"))
    check(wire["feasible"] is True, "HTTP boundary case feasible")
    rb = wire["result"]
    check(rb["area"] == 2, f"HTTP exact area is 2 (got {rb['area']})")
    check(rb["outlier_count"] == 0, f"HTTP outliers are 0 (got {rb['outlier_count']})")
    check(rb["retained_count"] == 6, f"HTTP retains all six points (got {rb['retained_count']})")
    check(len(rb["retained"]) == 6 and len(rb["outliers"]) == 0,
          "result partitions six retained / zero outliers")
    check(len({(p["x"], p["y"]) for p in rb["retained"]}) == 6,
          "retained coordinates remain six distinct exact integers")
    check(rb["retained"][0]["x"] in (B53, B53 + 1, B53 + 2), "coordinates kept at full precision")
    check(len({(p["x"], p["y"]) for p in wire["input"]["points"]}) == 6,
          "echoed input keeps six distinct exact coordinates")
    verify_membership(rb, boundary, "2^53-boundary")

    # The HTTP boundary (pydantic StrictInt) must not silently coerce a
    # fractional JSON number to an integer.
    fractional_body = (
        '{"points":['
        + ",".join(
            f'{{"id":"{p["id"]}","x":{p["x"]}.0,"y":{p["y"]}}}' for p in boundary
        )
        + '],"min_cell_area":2,"max_outliers":0}'
    )
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/audit",
        data=fractional_body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as fr:
            fstatus = fr.status
    except urllib.error.HTTPError as e:
        fstatus = e.code
    check(fstatus == 422, "fractional JSON coordinate rejected at the wire boundary")

    # The proxied path through nginx returns the identical exact conclusion.
    status, proxied = http_post(
        f"{WEB_URL}/api/audit",
        {"points": boundary, "min_cell_area": 2, "max_outliers": 0},
    )
    check(status == 200 and proxied["feasible"]
          and proxied["result"]["area"] == 2
          and proxied["result"]["outlier_count"] == 0
          and proxied["result"]["retained_count"] == 6,
          "nginx-proxied boundary request returns the exact same conclusion")

    print("\n== 10. original defect detector must now report NOT_REPRODUCED ==")
    # The exact detector from the defect report, run as a subprocess so its
    # own exit code and stdout are honored literally: it exits 1 printing
    # "BUG: ..." while the defect exists, and must exit 0 printing
    # NOT_REPRODUCED once the frontend stops coercing coordinates.  The
    # detector text hardcodes the compose hostname http://web; a transparent
    # urlopen shim redirects it at WEB_URL (which is http://web:80 inside
    # compose, or the local dev proxy when running without Docker).
    detector = subprocess.run(
        [sys.executable, "-c", DETECTOR_URL_SHIM + DETECTOR_SNIPPET],
        capture_output=True,
        text=True,
    )
    print(detector.stdout, end="")
    if detector.stderr:
        print(detector.stderr, end="", file=sys.stderr)
    check(detector.returncode == 0, "detector exits 0 after the fix")
    check("NOT_REPRODUCED" in detector.stdout, "detector prints NOT_REPRODUCED")
    check("BUG:" not in detector.stdout, "detector no longer reports the collision")

    print()
    if failures:
        print(f"ACCEPTANCE FAILED: {len(failures)} check(s) failed")
        return 1
    print("ACCEPTANCE PASSED: all checks succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
