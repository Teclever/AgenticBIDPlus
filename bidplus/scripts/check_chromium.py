"""S0 headless-Chromium proof (DONE-WHEN).

Launches headless Chromium, loads about:blank, prints the browser version, and exits
0 on success. This retires the Playwright-on-headless risk on the dev Mac; the deploy
box proves the same independently (DEPLOY_WORKFLOW.md §2).
"""

from __future__ import annotations

import sys


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto("about:blank")
            version = browser.version
        finally:
            browser.close()

    print(f"OK: headless Chromium launched (version {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
