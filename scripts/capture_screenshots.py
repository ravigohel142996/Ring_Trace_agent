#!/usr/bin/env python3
"""
scripts/capture_screenshots.py
---------------------------------
Reproducible screenshot capture for the RingTrace dashboard, for judges /
contributors running this LOCALLY or in CI (anywhere with normal outbound
network access and the ability to install a browser).

WHY THIS SCRIPT EXISTS (read this before assuming screenshots are faked):
The sandbox this project was engineered in has no root/sudo (apt-get is
blocked), no Docker/Podman, and outbound access to the Playwright/Chromium
CDN (playwright.azureedge.net) is blocked. That makes it IMPOSSIBLE to
install a real browser and capture real screenshots inside that sandbox.
Rather than fabricate screenshots (explicitly against this project's rules),
this script is provided so YOU can generate real, honest screenshots of the
actual running app in an environment that has normal network/browser access
— e.g. your laptop, or a GitHub Actions runner.

Usage:
    pip install playwright
    playwright install chromium
    # In one terminal:
    streamlit run app/dashboard.py --server.address 0.0.0.0 --server.port 8501
    # In another terminal:
    python scripts/capture_screenshots.py --base-url http://localhost:8501

Captures, into docs/screenshots/:
    01_investigation_input.png   — Section A, before running an investigation
    02_why_this_action.png       — The "Why This Action?" panel after Case C (A1027)
    03_agent_trace.png           — Section B, live tool-call trace
    04_graph_view.png            — Section C, interactive graph visualization
    05_risk_panel.png            — Section D, raw vs. graph-guardrailed risk gauge
    06_evidence.png              — Section E, numbered reasoning trail
    07_final_decision.png        — Section F, verdict banner + execute action
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8501")
    parser.add_argument("--account-id", default="A1027", help="Demo account to drive the screenshots with.")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright is not installed. Run:\n"
              "    pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(args.base_url, timeout=30_000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(out_dir / "01_investigation_input.png"))

        # Enter the account ID and run the investigation.
        text_input = page.get_by_label("Account / Alert ID")
        text_input.fill(args.account_id)
        page.get_by_text("Run Investigation").click()
        page.wait_for_timeout(6000)  # let the investigation + graph render complete

        page.get_by_text("Why This Action?").click()
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / "02_why_this_action.png"))

        page.get_by_text("B. Agent Trace").click()
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / "03_agent_trace.png"))

        page.get_by_text("C. Graph View").click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out_dir / "04_graph_view.png"))

        page.get_by_text("D. Risk").click()
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / "05_risk_panel.png"))

        page.get_by_text("E. Evidence").click()
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / "06_evidence.png"))

        page.get_by_text("F. Decision").click()
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / "07_final_decision.png"))

        browser.close()

    print(f"Done. Screenshots written to {out_dir}/")


if __name__ == "__main__":
    main()
