#!/usr/bin/env python3
"""UI regression checks for the nine issues raised by the role-played reviewers.

These are the checks behind docs/testing-summary.md: they drive a *running*
app in a real browser and assert the behaviours that were fixed. Start the app
first (`make app`), then run this.

    make verify-ui                     # or:
    python tests/verify_ui.py --url http://localhost:8501

Requires Playwright for Python with a Chromium build:

    pip install playwright && playwright install chromium

(the demo image already has both: `docker run --rm --entrypoint python \\
   -v "$PWD:/workspace" cuad-demo-builder /workspace/tests/verify_ui.py \\
   --url http://host.docker.internal:8501`)

Every check is read-only against the app, with one exception: check 4 changes
and then restores the status of a throwaway account whose name starts with
`test-`, and skips itself if there is no such account, so a real login is never
suspended.

Exits non-zero if any check fails. Screenshots land in build/verify-ui/.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - environment guard
    sys.exit(
        "playwright is not importable.\n"
        "  pip install playwright && playwright install chromium\n"
        "or run this file inside the demo image (see the module docstring)."
    )

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def read_credentials(path: Path) -> dict[str, str]:
    """Map role -> password from credentials.txt (written by `make users`)."""
    if not path.exists():
        sys.exit(f"{path} not found; run `make users` first.")
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] in {"lawyer", "admin", "auditor"}:
            found.setdefault(parts[1], parts[2])
    for role in ("lawyer", "admin", "auditor"):
        if role not in found:
            sys.exit(f"no {role} login in {path}")
    return found


def new_page(width: int, height: int):
    """A fresh tab at a given viewport size (one context, many pages)."""
    page = CONTEXT.new_page()
    page.set_viewport_size({"width": width, "height": height})
    return page


def login(page, username: str, password: str) -> None:
    page.goto(APP, wait_until="domcontentloaded")
    page.locator('input[aria-label="Username"]').fill(username)
    page.locator('input[aria-label="Password"]').fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.get_by_text("Sign out").first.wait_for(timeout=45_000)


def search(page, term: str) -> None:
    page.locator('input[aria-label="Search"]').fill(term)
    page.locator('[data-testid="stSidebar"] button', has_text="Search").first.click()
    page.wait_for_timeout(3_000)


def body(page) -> str:
    return page.locator("body").inner_text()


def span_counts(page) -> tuple[int, int]:
    """(first_row, total) from the 'Showing X–Y of N' caption."""
    match = re.search(r"Showing (\d+)–(\d+) of (\d+) matching clause spans", body(page))
    return (int(match.group(1)), int(match.group(3))) if match else (0, 0)


def run(page, shots: Path, creds: dict[str, str]) -> None:
    # --- 1 + 3 + 8: clause totals, honest header, plural --------------------
    login(page, "lawyer-001", creds["lawyer"])
    search(page, "indemnif")

    first, total = span_counts(page)
    check("1a clause search shows a total", first == 1 and total > 60,
          f"first row {first}, total {total}")

    next_button = page.locator("button", has_text=re.compile(r"^Next 60")).first
    if next_button.count():
        next_button.click()
        page.wait_for_timeout(3_500)
        second_first, second_total = span_counts(page)
        check("1b clause search pages forward",
              second_first == 61 and second_total == total,
              f"page 2 starts at {second_first}, total {second_total}")
    else:
        check("1b clause search pages forward", False, "no Next control")

    text = body(page)
    check("3 no misleading '0 contracts' header",
          "0 contracts" not in text and "clause-text matches are shown below" in text,
          (re.search(r"No contract title[^\n]*", text) or ["(missing)"]).group(0)[:90])

    search(page, "2Themart")
    header = re.search(r"\d+ contracts?", body(page))
    check("8 singular header", bool(header) and header.group(0) == "1 contract",
          header.group(0) if header else "(no header)")

    # --- 2: a register row opens its document -------------------------------
    search(page, "")
    page.get_by_text(re.compile(r"510 contracts")).wait_for(timeout=20_000)
    page.wait_for_timeout(2_500)
    box = page.locator('[data-testid="stDataFrame"] canvas').first.bounding_box()
    open_button = page.locator('[data-testid="stMain"] button').filter(
        has_text=re.compile(r"^Open$")
    ).first
    disabled_first = not open_button.is_enabled()
    page.mouse.click(box["x"] + 8, box["y"] + 36 + 17)  # the row's selection cell
    page.wait_for_timeout(3_000)
    enabled = open_button.is_enabled()
    opened = False
    if enabled:
        open_button.click()
        page.wait_for_timeout(4_000)
        opened = "nav=document" in page.url
    check("2 register row opens a document", disabled_first and enabled and opened,
          f"disabled first={disabled_first}, enabled after select={enabled}, opened={opened}")
    page.screenshot(path=str(shots / "02-register.png"))

    # --- 7: the user list keeps every column when narrow --------------------
    page.close()
    narrow = new_page(1000, 900)
    login(narrow, "admin", creds["admin"])
    narrow.get_by_role("button", name="Admin").click()
    narrow.wait_for_timeout(3_500)
    geometry = narrow.evaluate(
        """() => {
          const t = document.querySelector('table.users');
          return t ? {
            headers: [...t.querySelectorAll('th')].map(h => h.textContent.trim()),
            overflow: t.scrollWidth - t.clientWidth,
          } : null;
        }"""
    )
    check("7 user list fits a narrow window",
          bool(geometry)
          and geometry["overflow"] <= 0
          and "Last login (UTC)" in geometry["headers"],
          str(geometry))
    narrow.screenshot(path=str(shots / "07-admin-users-narrow.png"))
    narrow.close()

    # --- 4: per-account actions act on the right account --------------------
    picker = new_page(1400, 1000)
    login(picker, "admin", creds["admin"])
    picker.get_by_role("button", name="Admin").click()
    picker.wait_for_timeout(3_500)
    account_row = picker.locator('[data-testid="stHorizontalBlock"]').filter(
        has_text="test-user-01"
    ).first
    if account_row.count():
        def row_status() -> str:
            match = re.search(r"·\s*(active|suspended)", account_row.inner_text())
            return match.group(1) if match else "?"

        before_row = row_status()
        action = account_row.get_by_role(
            "button", name=re.compile(r"^(Suspend|Reactivate)$")
        ).first
        action_label = action.inner_text().strip()
        action.click()
        picker.wait_for_timeout(4_000)
        after_row = row_status()
        expected = "active" if action_label == "Reactivate" else "suspended"
        check("4a an account action applies to that account",
              after_row == expected,
              f"clicked {action_label!r}: {before_row!r} -> {after_row!r}")
        # flip it back, so the account is left as found
        account_row.get_by_role(
            "button", name=re.compile(r"^(Suspend|Reactivate)$")
        ).first.click()
        picker.wait_for_timeout(4_000)
        check("4b the reverse action restores the account",
              row_status() == before_row,
              f"ended as {row_status()!r}, wanted {before_row!r}")
    else:
        check("4a an account action applies to that account", True,
              "SKIPPED: no throwaway test-* account")
        check("4b the reverse action restores the account", True, "SKIPPED")
    picker.close()

    # --- 5 + 6: report totals, and a refusal that is recorded ---------------
    auditor = new_page(1400, 1000)
    login(auditor, "auditor", creds["auditor"])
    auditor.wait_for_timeout(3_000)
    text = body(auditor)
    check("5a reports show a row count",
          bool(re.search(r"All \d+ row\(s\) shown\.|Showing \d+ of \d+", text)),
          (re.search(r"All \d+ row\(s\) shown\.|Showing \d+ of \d+", text) or ["(none)"]).group(0))
    check("5b rows-per-list control exists", "Rows per list" in text)
    auditor.screenshot(path=str(shots / "05-reports.png"))

    auditor.evaluate(
        "() => history.replaceState({}, '', '/?nav=document&doc="
        "2themartcominc-19990826-10-12g-ex-10-10-6700288-ex-10-10-co-branding"
        "-agreement-agency-agreement')"
    )
    auditor.locator("label", has_text="Searches").first.click(force=True)  # rerun, URL intact
    auditor.wait_for_timeout(4_000)
    check("6a a refused page is refused",
          "Not authorised for this page." in body(auditor))

    # ...and the refusal reached the audit trail, read back through the app.
    # The denied page stopped rendering at require_role(), so get back to the
    # reports via the sidebar before reading the log.
    auditor.get_by_role("button", name="Reports").click()
    auditor.wait_for_timeout(3_500)
    auditor.locator("label", has_text="Activity").first.click(force=True)
    auditor.wait_for_timeout(4_000)
    # The report tables are canvas grids, so cell text is not in innerText;
    # read the accessibility cells instead.
    in_log = auditor.evaluate(
        """() => [...document.querySelectorAll('[role="gridcell"]')]
                  .some(c => c.textContent.includes('ACCESS_DENIED'))"""
    )
    check("6b the refusal is in the audit log", in_log)
    auditor.screenshot(path=str(shots / "06-activity.png"))
    auditor.close()

    # --- 9: a deep link resumes after the sign-in it forces -----------------
    deep = new_page(1400, 1000)
    deep.goto(f"{APP}/?nav=contracts&q=indemnif", wait_until="domcontentloaded")
    deep.wait_for_timeout(3_500)
    landing = body(deep)
    check("9a a reload asks for a password",
          "Sign in" in landing and "Ada Whitfield" not in landing)
    check("9b the login screen names the destination",
          "Sign in to continue to" in landing,
          (re.search(r"Sign in to continue to[^\n]*", landing) or ["(none)"]).group(0)[:80])
    deep.locator('input[aria-label="Username"]').fill("lawyer-001")
    deep.locator('input[aria-label="Password"]').fill(creds["lawyer"])
    deep.get_by_role("button", name="Sign in").click()
    deep.wait_for_timeout(4_500)
    check("9c the deep link resumes after sign-in",
          "nav=contracts" in deep.url and "Clause text matches" in body(deep),
          deep.url)
    deep.screenshot(path=str(shots / "09-deeplink.png"))
    deep.close()


def main() -> int:
    global APP, CONTEXT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8501")
    parser.add_argument("--credentials", default=str(ROOT / "credentials.txt"))
    parser.add_argument("--out", default=str(ROOT / "build" / "verify-ui"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    APP = args.url.rstrip("/")
    shots = Path(args.out)
    shots.mkdir(parents=True, exist_ok=True)
    creds = read_credentials(Path(args.credentials))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        CONTEXT = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = CONTEXT.new_page()
        try:
            run(page, shots, creds)
        except Exception as exc:  # noqa: BLE001 - report, then summarise everything
            check("run completed without error", False, f"{type(exc).__name__}: {exc}")
        finally:
            browser.close()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed"
          f" (screenshots in {shots})")
    if failed:
        print("failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
