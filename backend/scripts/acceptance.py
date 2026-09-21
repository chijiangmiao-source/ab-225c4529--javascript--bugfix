#!/usr/bin/env python3
"""One-shot acceptance check for the compose stack.

Runs:
  1. the pure-stdlib exact-arithmetic unit tests (lattice + wire codec);
  2. HTTP acceptance checks against the running backend and the
     nginx-served frontend (including the nginx -> backend proxy);
  3. an independent exact re-verification of every returned lattice
     membership and the optimum on the standard contamination scenario;
  4. the big-integer regression straight against the backend interface;
  5. the SAME regression through a real browser driving the served page
     (fill inputs, click 执行审计), asserting the outgoing request keeps
     six distinct coordinates and the rendered result matches the exact
     backend response value by value (area/basis/origin/coords);
  6. the original defect-detector probe against the shipped JS bundle.

Exits 0 only when everything passes; any failure -> exit 1, so the
`verify` compose service reports the result by its exit code and stops.
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.exact_json import decode_exact_json, encode_exact_json  # noqa: E402
from app.solver import solve  # noqa: E402

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
WEB_URL = os.environ.get("WEB_URL", "http://web:80")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Adjacent integers just above the JavaScript safe-integer boundary.
# In a JS Number, p0==p1 and p3==p4 (6 unique points collapse to 4); the
# exact integer backend solves the original six with area 2.
SAFE_BOUND = 9007199254740992
BIGINT_POINTS = [
    {"id": f"p{i}", "x": SAFE_BOUND + i % 3, "y": 2 * (i // 3)}
    for i in range(6)
]

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


def http_post(url, payload, timeout=60):
    """POST through the exact tagged-integer boundary; decode exactly."""
    req = urllib.request.Request(
        url,
        data=encode_exact_json(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, decode_exact_json(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def http_post_raw(url, raw, timeout=30):
    req = urllib.request.Request(
        url,
        data=raw,
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


def section_1_unit_tests():
    print("== 1. exact-arithmetic unit tests ==")
    for suite in ("tests/test_lattice.py", "tests/test_exact_json.py"):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, suite)],
            cwd=ROOT,
        )
        check(proc.returncode == 0, f"{suite} exit code 0")


def section_2_3_http():
    print("\n== 2. backend HTTP checks ==")
    status, body = http_get(f"{BACKEND_URL}/health")
    check(status == 200 and '"ok"' in body, "backend /health responds ok")

    print("\n== 3. frontend serving and reverse proxy ==")
    status, body = http_get(f"{WEB_URL}/")
    check(status == 200 and 'id="root"' in body, "nginx serves the SPA shell")
    status, body = http_get(f"{WEB_URL}/health")
    check(status == 200 and '"ok"' in body, "nginx proxies /health to backend")


def section_4_sample_audit():
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
          "proxied tagged audit returns the identical exact conclusion")


def section_6_witness():
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


def section_7_contract():
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

    # Exact-boundary contract: no bare JSON number may enter the pipeline,
    # and tagged values must actually be integer strings.
    status, _ = http_post_raw(
        f"{BACKEND_URL}/api/audit",
        json.dumps({"points": SAMPLE_POINTS[:6],
                    "min_cell_area": 2, "max_outliers": 0}).encode(),
    )
    check(status == 422, "bare JSON-number request body rejected")

    tagged = encode_exact_json(
        {"points": SAMPLE_POINTS[:6], "min_cell_area": 2, "max_outliers": 0})
    status, _ = http_post_raw(
        f"{BACKEND_URL}/api/audit",
        tagged.replace(b'"value": "2"', b'"value": "2.0"', 1),
    )
    check(status == 422, "non-integer tagged value rejected")


def section_8_huge_coords():
    print("\n== 8. exactness with 10^18-scale coordinates ==")
    b = 10**18
    # 8 points on the area B^2 lattice (B,0),(0,B).
    big = [{"id": f"p{i}", "x": b * m, "y": b * n}
           for i, (m, n) in enumerate(
               [(-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0), (-1, 1), (1, 1)])]
    status, data = http_post(
        f"{BACKEND_URL}/api/audit",
        {"points": big, "min_cell_area": 2, "max_outliers": 0},
    )
    check(status == 200 and data["feasible"], "huge-coordinate case feasible")
    check(data["result"]["area"] == b * b, f"area is exactly B^2={b*b}")
    check(data["result"]["origin"] == [0, 0], "huge-case origin exact")
    verify_membership(data["result"], big, "bigint")
    return big


def section_9_bigint_backend():
    print("\n== 9. regression data via the existing backend interface ==")
    status, data = http_post(
        f"{BACKEND_URL}/api/audit",
        {"points": BIGINT_POINTS, "min_cell_area": 2, "max_outliers": 0},
    )
    check(status == 200, "above-safe-integer request HTTP 200 (no duplicate 422)")
    check(data["feasible"] is True, "the six distinct integer points are feasible")
    r = data["result"]
    check(r["area"] == 2, f"exact area is 2 (got {r['area']})")
    check(r["outlier_count"] == 0, f"zero outliers (got {r['outlier_count']})")
    check(r["retained_count"] == 6, f"all six points retained (got {r['retained_count']})")
    check(sorted(p["id"] for p in r["retained"]) == [f"p{i}" for i in range(6)],
          "every submitted id comes back retained")
    exact_pairs = {(p["x"], p["y"]) for p in BIGINT_POINTS}
    check(len(exact_pairs) == 6, "precondition: six unique exact coordinates")
    rounded_pairs = {(int(float(str(p["x"]))), int(float(str(p["y"])))) for p in BIGINT_POINTS}
    check(len(rounded_pairs) == 4,
          "precondition: JavaScript-style float rounding collapses them to four")
    verify_membership(r, BIGINT_POINTS, "bigint-regression")
    # The wire itself must carry the digits verbatim, never bare numbers.
    raw_req = encode_exact_json({"points": BIGINT_POINTS,
                                 "min_cell_area": 2, "max_outliers": 0})
    check(b"9007199254740993" in raw_req and b"9007199254740994" in raw_req,
          "request wire text contains the adjacent unsafe integers literally")

    status, raw_resp = http_post_raw(
        f"{BACKEND_URL}/api/audit", raw_req)
    check(status == 200, "raw tagged request HTTP 200")
    check(b"9007199254740993" in raw_resp and b'"@type": "int"' in raw_resp,
          "response wire text carries the unsafe integers as tagged strings")
    # The unsafe digits must never appear as bare JSON number literals.
    check(not re.search(rb":\s*900719925474099[234]\b", raw_resp),
          "response contains no bare unsafe-integer number literals")


def _fill_points(page, points):
    """Replace the editor table contents with exactly `points` rows."""
    rows = page.locator(".point-table tbody tr")
    while rows.count() > len(points):
        rows = page.locator(".point-table tbody tr")
        rows.first.locator("button").click()
    while page.locator(".point-table tbody tr").count() < len(points):
        page.get_by_role("button", name="+ 增加点").click()
    rows = page.locator(".point-table tbody tr")
    for i, p in enumerate(points):
        inputs = rows.nth(i).locator("input")
        inputs.nth(0).fill(p["id"])
        inputs.nth(1).fill(str(p["x"]))
        inputs.nth(2).fill(str(p["y"]))


def _assert_rendered_exact(page, exact, expected_points, label, want_lossy,
                           must_mention=()):
    """Value-by-value: DOM text must equal the exact decoded response."""
    r = exact["result"]
    strong = page.locator(".verdict-ok strong")
    check(strong.nth(0).text_content() == str(r["area"]),
          f"[{label}] rendered area {strong.nth(0).text_content()!r} == {r['area']}")
    check(strong.nth(1).text_content() == str(r["outlier_count"]),
          f"[{label}] rendered outlier count exact")
    check(strong.nth(2).text_content() == str(r["retained_count"]),
          f"[{label}] rendered retained count exact")

    matrices = page.locator("pre.matrix")
    expect_basis = (
        f"⎡ {r['basis']['b1'][0]}  {r['basis']['b2'][0]} ⎤\n"
        f"⎣ {r['basis']['b1'][1]}  {r['basis']['b2'][1]} ⎦"
    )
    check(matrices.nth(0).text_content() == expect_basis,
          f"[{label}] rendered basis matrix matches exact basis")
    check(matrices.nth(1).text_content() == f"({r['origin'][0]}, {r['origin'][1]})",
          f"[{label}] rendered origin ({matrices.nth(1).text_content()!r}) is exact")
    check(
        matrices.nth(2).text_content()
        == f"h={r['hnf']['h']}, r={r['hnf']['r']}, q={r['hnf']['q']}",
        f"[{label}] rendered HNF entries exact",
    )

    cells = page.eval_on_selector_all(
        ".coord-table tbody tr",
        "els => els.map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))",
    )
    by_id = {p["id"]: p for p in r["retained"]}
    check(len(cells) == len(r["retained"]) + len(r["outliers"]),
          f"[{label}] result table covers retained + outliers")
    rendered_pairs = set()
    for row in cells:
        pid = row[0]
        if pid in by_id:
            exp = by_id[pid]
            check(row[1] == f"({exp['x']}, {exp['y']})",
                  f"[{label}] table pixel coords of {pid} exact: {row[1]}")
            check(row[2] == f"({exp['coord'][0]}, {exp['coord'][1]})",
                  f"[{label}] table lattice coords of {pid} exact: {row[2]}")
            check(row[3] == "保留", f"[{label}] {pid} marked retained")
            rendered_pairs.add(row[1])
    check(len(rendered_pairs) == len(expected_points),
          f"[{label}] all {len(expected_points)} distinct points shown without merging")
    # Exact digit strings from the response must appear literally in the
    # page when the scenario calls for it (the unsafe-adjacent case).
    body_text = page.locator("body").inner_text()
    for digits in must_mention:
        check(digits in body_text,
              f"[{label}] exact integer {digits} visible in the page")

    # The SVG is only a finite-precision projection: business values above
    # were compared against exact strings; here we only check the diagram.
    check(page.locator(".lattice-svg .retained-dot").count() == len(r["retained"]),
          f"[{label}] SVG draws one retained dot per retained point")
    lossy = page.locator('[data-testid="projection-lossy"]')
    if want_lossy:
        check(lossy.count() == 1 and lossy.is_visible(),
              f"[{label}] SVG flags finite-precision projection collapse")
    else:
        check(lossy.count() == 0,
              f"[{label}] no false projection-collapse warning")

    # No frontend-fabricated duplicate-coordinate error may be shown.
    error_box = page.locator(".inline-error")
    visible_errors = [error_box.nth(i).text_content()
                      for i in range(error_box.count())
                      if error_box.nth(i).is_visible()]
    check(not any("duplicate" in (t or "") or "重复" in (t or "") for t in visible_errors),
          f"[{label}] no duplicate-coordinate error produced by the frontend")


def _run_browser_scenario(page, points, min_area, max_outliers, label, want_lossy,
                          must_mention=()):
    _fill_points(page, points)
    page.locator(".params input[type='number']").fill(str(min_area))
    page.locator(".params select").select_option(str(max_outliers))
    with page.expect_response(
        lambda resp: resp.request.method == "POST" and "/api/audit" in resp.url,
        timeout=30000,
    ) as info:
        page.get_by_role("button", name="执行审计").click()
    resp = info.value

    # --- the actual business request the page sent ---------------------
    sent = json.loads(resp.request.post_data)
    pairs = [(p["x"]["value"], p["y"]["value"]) for p in sent["points"]]
    expected_pairs = [(str(p["x"]), str(p["y"])) for p in points]
    check(resp.status == 200, f"[{label}] page submission HTTP 200")
    check(pairs == expected_pairs,
          f"[{label}] outgoing request carries the exact coordinates in order")
    check(len(set(pairs)) == len(points),
          f"[{label}] outgoing request still has {len(points)} distinct coordinates")
    check(sent["min_cell_area"]["value"] == str(min_area)
          and sent["max_outliers"]["value"] == str(max_outliers),
          f"[{label}] outgoing request parameters are exact tagged ints")
    check(all(set(p["x"]) == {"@type", "value"} for p in sent["points"]),
          f"[{label}] every request coordinate uses the exact int tag")

    # --- the exact backend response, parsed/displayed by the frontend ---
    exact = decode_exact_json(resp.body())
    check(exact["feasible"] is True, f"[{label}] backend response feasible")
    page.wait_for_selector(".verdict-ok", timeout=10000)
    _assert_rendered_exact(page, exact, points, label, want_lossy,
                           must_mention=must_mention)
    return exact


def section_10_browser():
    print("\n== 10. real browser page submission (headless Chromium) ==")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        check(False, f"playwright import failed: {exc!r}")
        return

    console_errors = []
    with sync_playwright() as pw:
        # channel="chromium" selects the full Chromium build installed by
        # `playwright install chromium` (the default wants the separate
        # chromium-headless-shell package).
        browser = pw.chromium.launch(
            headless=True,
            channel="chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        page.on("console",
                lambda msg: console_errors.append(f"console: {msg.text}")
                if msg.type == "error" else None)
        page.goto(f"{WEB_URL}/", wait_until="networkidle")

        try:
            # Scenario A: the six unsafe-adjacent-integer points.  Their
            # finite SVG projections DO collapse, and the page must say so
            # while keeping all six exact business points.
            _run_browser_scenario(
                page, BIGINT_POINTS, 2, 0, "browser-bigint", want_lossy=True,
                must_mention=("9007199254740992", "9007199254740993",
                              "9007199254740994"))

            # Scenario B: reload and run 10^18-scale data through the same
            # path, so area (10^36), basis (10^18), origin and coordinates
            # are all parsed and rendered by the frontend without loss.
            page.goto(f"{WEB_URL}/", wait_until="networkidle")
            b = 10**18
            big = [{"id": f"q{i}", "x": b * m, "y": b * n}
                   for i, (m, n) in enumerate(
                       [(-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0),
                        (1, 0), (-1, 1), (1, 1)])]
            _run_browser_scenario(
                page, big, 2, 0, "browser-1e18", want_lossy=False,
                must_mention=("1000000000000000000",
                              "1000000000000000000000000000000000000"))
        finally:
            browser.close()

    check(not console_errors,
          "no uncaught browser/console errors during the audits "
          f"({console_errors[:3]})")


def section_11_detector():
    print("\n== 11. original defect detector against the shipped bundle ==")
    # Faithful port of the reproduction one-liner (same solve call, same
    # float collapse, same bundle grep).  After the fix the frontend no
    # longer converts coordinates before POST, so the probe must report
    # NOT_REPRODUCED; the float-collapse preconditions are still asserted so
    # a vacuous pass is impossible.
    exact = solve({"points": BIGINT_POINTS, "min_cell_area": 2, "max_outliers": 0})
    rounded = [
        dict(p, x=int(float(str(p["x"]))), y=int(float(str(p["y"]))))
        for p in BIGINT_POINTS
    ]
    html = urllib.request.urlopen(f"{WEB_URL}/").read().decode()
    src = re.search(r'src="([^"]+\.js)"', html).group(1)
    js = urllib.request.urlopen(f"{WEB_URL}{src}").read()
    preconditions = (
        exact["feasible"]
        and exact["result"]["area"] == 2
        and len({(p["x"], p["y"]) for p in BIGINT_POINTS}) == 6
        and len({(p["x"], p["y"]) for p in rounded}) == 4
    )
    check(preconditions, "detector preconditions hold (area 2; 6 -> 4 under float)")
    bug = preconditions and b"parseInt(" in js and b"Number(" in js
    check(not bug, "shipped JS no longer converts coordinates with parseInt/Number")
    print("  ->  NOT_REPRODUCED" if not bug else "  ->  BUG REPRODUCED")


def main():
    section_1_unit_tests()
    section_2_3_http()
    section_4_sample_audit()
    section_6_witness()
    section_7_contract()
    section_8_huge_coords()
    section_9_bigint_backend()
    section_10_browser()
    section_11_detector()

    print()
    if failures:
        print(f"ACCEPTANCE FAILED: {len(failures)} check(s) failed")
        return 1
    print("ACCEPTANCE PASSED: all checks succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
