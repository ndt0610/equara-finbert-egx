"""Local visual smoke check for the US workbench using installed Edge."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "ui_review"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def layout(page, label):
    result = page.evaluate("""() => {
      const edge = document.documentElement.clientWidth;
      return {
        width: edge,
        scrollWidth: document.scrollingElement.scrollWidth,
        tableOverflow: [...document.querySelectorAll('#usResult .table-wrap, #usAuditPanel .table-wrap')]
          .map(el => el.scrollWidth - el.clientWidth).filter(x => x > 1),
        offenders: [...document.querySelectorAll('body *')].filter(el => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.right > edge + 1;
        }).slice(0, 8).map(el => `${el.tagName.toLowerCase()}.${el.className || ''}: ${Math.round(el.getBoundingClientRect().right)}`)
      };
    }""")
    print(label, result)
    page.screenshot(path=str(OUT / f"{label}.png"), full_page=False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(EDGE), headless=True)
        for width in (320, 390, 768, 1280):
            page = browser.new_page(viewport={"width": width, "height": 900}, device_scale_factor=1)
            page.goto("http://127.0.0.1:8124/", wait_until="networkidle")
            layout(page, f"{width}-initial")
            page.locator("#usDataMode").select_option("captured")
            page.locator("#usLoadTen").click()
            page.locator("#usTimeMode").select_option("replay")
            page.locator("#usDecisionCutoff").fill("2026-11-13T21:15:00Z")
            page.locator("#usForm button[type=submit]").click()
            page.get_by_role("heading", name="Snapshot từ sổ cái cục bộ").wait_for(timeout=30000)
            page.locator("#usResult h2").scroll_into_view_if_needed()
            layout(page, f"{width}-result")
            page.locator("#usResult .us-inspector summary").click()
            page.locator("#usResult .us-inspector").scroll_into_view_if_needed()
            layout(page, f"{width}-inspector")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
