r"""Kiểm tra bằng Chromium, chạy tay (không nằm trong pytest vì cần một server đang chạy).

1. Tab 1 và tab 2: gửi đúng các đầu vào fixture đã lưu từ bản gốc, xác nhận trình duyệt gọi GET, JSON
   bằng JSON của POST và bằng phản hồi của bản gốc, đồng hồ có đúng 3 nhãn vạch, một cung, góc kim
   (score + 1) × 90 độ.
2. Tab "Danh mục theo vốn" (giao diện C3), chế độ fixture:
   a. danh mục mặc định: JSON trên trang = JSON của POST; phần vốn có tin, số thanh, tổng các thanh = S;
      đủ 100% vốn có tin thì không có dải khoảng mà có câu giải thích;
   b. một mã không tìm thấy tin (HRHO): dòng xám không có thanh, dải khoảng khớp JSON;
   c. so A/B (nút điền ví dụ, và một ví dụ thiếu tin): trang gửi đúng MỘT yêu cầu; S của A khớp backend,
      S của B khớp một POST riêng với phần vốn của B (fixture cố định nên so được), tổng các thanh = S_B − S_A;
   d. màn hình điện thoại 390 px và màn rất hẹp 320 px (bản 3.1): không tràn ngang, kể cả khi mở mọi mục chi tiết,
      không bảng nào phải cuộn ngang; ở 320 px kiểm cả tab 1 và tab 2 sau khi có kết quả. Đo bằng
      document.documentElement.clientWidth (không tính thanh cuộn dọc), không dùng window.innerWidth;
   e. (bản 3) phễu đếm từng mã = số trong JSON, danh sách bị loại nhóm theo lý do đầu tiên đúng số, khối
      "Khớp tên theo bộ lọc Tab 1–2" đúng số bản ghi, không còn các cụm chữ đã bỏ.

Cài (một lần, trong venv của dự án, sau khi đã cài phần lõi từ requirements.lock.txt như README):
    python -m pip install -r requirements-dev.txt        # có playwright==1.64.1; Windows: .\.venv\Scripts\python.exe -m pip ...
  Trình duyệt, chọn MỘT trong hai cách:
    - dùng Chrome hoặc Chromium đã cài trên máy, truyền đường dẫn qua --chromium (không tải thêm gì), ví dụ
      Windows: --chromium "C:\Program Files\Google\Chrome\Application\chrome.exe"
      Linux:   --chromium /usr/bin/chromium
    - hoặc tải Chromium riêng của Playwright: python -m playwright install chromium (khi đó bỏ --chromium).

Chạy (2 cửa sổ, cùng thư mục gốc dự án):
    DEMO_MODE=fixture python -m uvicorn backend.app:app --port 8000
    python tests/check_browser.py --base-url http://127.0.0.1:8000 --out artifacts/browser_check [--chromium ĐƯỜNG_DẪN]
  Trên PowerShell, dòng đầu là:  $env:DEMO_MODE="fixture"; python -m uvicorn backend.app:app --port 8000
  Không cần thêm -X utf8 (bản 3.2): script tự đổi đầu ra sang UTF-8, nên lệnh trên chạy được cả khi đầu ra
  bị chuyển hướng trên Windows (bảng mã cp1252).
  Đạt khi lệnh in bảng có 12 dòng kết quả (4 dòng tab 1–2, 8 dòng tab 3 và màn hẹp) và không có AssertionError; bảng cũng được ghi vào artifacts/browser_check/NETWORK.md.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PHONE_WIDTHS = (390, 320)  # bản 3.1: thêm 320 px (màn hẹp nhất thường gặp; Codex đo khung thật innerWidth 319)
OVERFLOW_JS = "() => document.scrollingElement.scrollWidth - document.documentElement.clientWidth"
CULPRITS_JS = """() => {
  const edge = document.documentElement.clientWidth;
  return [...document.querySelectorAll('body *')]
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > edge + 0.5; })
    .slice(0, 5)
    .map((el) => `${el.tagName.toLowerCase()}.${el.classList[0] || ''} right=${Math.round(el.getBoundingClientRect().right)}`);
}"""


def utf8_console() -> None:
    """Bản 3.2: trên Windows, khi đầu ra bị chuyển hướng (pipe, file, công cụ chạy lệnh), Python ghi bằng bảng mã
    cp1252 và chết ở chữ Việt đầu tiên (UnicodeEncodeError). Đổi stdout và stderr sang UTF-8 để lệnh chạy được
    nguyên văn, không cần thêm -X utf8. Chỉ đổi cách in chữ, không đổi phép kiểm hay số nào."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> None:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "browser_check"))
    parser.add_argument("--original", default=str(ROOT / "tests" / "data" / "fixture-responses-original.json"))
    parser.add_argument("--chromium", help="Đường dẫn tới chrome.exe / chromium có sẵn trên máy. Bỏ trống thì dùng Chromium do 'python -m playwright install chromium' tải về.")
    parser.add_argument("--original-port-key", default="8011", help="Trong file đã lưu, khóa có cổng này là phản hồi của bản gốc.")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    original = json.loads(Path(args.original).read_text(encoding="utf-8"))
    base = args.base_url.rstrip("/")
    table = ["| Tab | Đầu vào | HTTP | JSON GET = POST = bản gốc | Góc kim |", "|---|---|---|---|---|"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium) if args.chromium else pw.chromium.launch()
        page = browser.new_page()
        page.goto(base + "/")
        for key, item in original.items():
            if f" {args.original_port_key} " not in key or item["http"] != 200 or not item["body"]:
                continue
            body = item["body"]
            stock = "symbol" in body
            tab = "stock" if stock else "portfolio"
            value = body["symbol"] if stock else ",".join(body["symbols"])
            page.locator(f"#{tab}Tab").click()
            page.locator("#stockSymbol" if stock else "#portfolioSymbols").fill(value)
            with page.expect_response(lambda r: "/api/sentiment/" in r.url) as event:
                page.locator(f"#{tab}Form button").click()
            response = event.value
            data = response.json()
            posted = httpx.post(response.url.split("?")[0], json=body).json()
            assert response.request.method == "GET" and response.status == 200 and data == posted == item["response"], key
            gauge = page.get_by_role("img", name=f"SentimentGauge: {data['sentiment']}, {data['score']:.3f}", exact=True)
            assert gauge.locator("text").all_text_contents() == ["−1", "0", "+1"]
            assert gauge.locator('path[fill="none"]').count() == 1
            angle = float(gauge.locator(".needle").get_attribute("transform").split("(")[1].split()[0])
            assert math.isclose(angle, (data["score"] + 1) * 90, abs_tol=1e-8)
            gauge.screenshot(path=str(out / f"{tab}-{value}.png"))
            table.append(f"| {tab} | {value} | GET 200 | OK | {angle:.4f}° |")
        assert len(table) == 6, "Thiếu đầu vào của bản gốc"

        page.locator("#weightedTab").click()
        table += coverage_checks(page, base, out)
        browser.close()
    (out / "NETWORK.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print("\n".join(table))


def vi_number(value: float, digits: int) -> str:
    """Số như trên trang tab 3: dấu phẩy thập phân, dấu trừ "−"."""
    text = f"{abs(value):.{digits}f}".replace(".", ",")
    if float(f"{abs(value):.{digits}f}") == 0:
        return text
    return ("+" if value > 0 else "−") + text


def fill_positions(page, rows, compare=False):
    if page.locator("#compareToggle").is_checked() != compare:
        page.locator("#compareToggle").click()
    symbols = page.locator("#positionRows input[name=symbol]")
    weights = page.locator("#positionRows input[name=weight]")
    weights_b = page.locator("#positionRows input[name=weightB]")
    for index in range(5):
        symbol, a, b = rows[index] if index < len(rows) else ("", "", "")
        symbols.nth(index).fill(symbol)
        weights.nth(index).fill(str(a))
        if compare:
            weights_b.nth(index).fill(str(b))


def submit_coverage(page):
    sent = []
    listener = lambda request: sent.append(request) if "/api/v2/sentiment/portfolio/coverage" in request.url else None
    page.on("request", listener)
    with page.expect_response(lambda r: "/api/v2/sentiment/portfolio/coverage" in r.url) as event:
        page.locator("#weightedForm button[type=submit]").click()
    page.wait_for_selector(".cov-disclaimer")
    page.remove_listener("request", listener)
    response = event.value
    return response, response.json(), json.loads(response.request.post_data), len(sent)


# Bản 3: các cụm chữ không được còn trong tab 3 (đã thay bằng "qua luật hiện tại", "tiêu đề được chấm", ...).
FORBIDDEN_TAB3 = ("tin riêng", "có giữ", "cũng loại", "Bộ lọc của bản tái dựng", "thiếu số liệu", "tin liên quan", "được giữ", "tin cũ hơn không chấm")
REASON_ORDER = ["stale", "missing_title", "duplicate", "name_only_in_description", "name_not_in_title", "ambiguous_name", "sports", "not_news_page"]


def funnel_label(h, cap):
    over = len(h["not_scored"])
    passed = len(h["headlines"]) + over
    return (
        f"Phễu đếm {h['short']}: {h['candidates_total']} ứng viên, {len(h['rejected'])} tự động loại, "
        f"{passed} qua luật hiện tại, {len(h['headlines'])} được chấm, {over} ngoài giới hạn {cap}"
    )


def funnel_checks(page, data):
    """Phễu, nhóm lý do, khối Tab 1–2 và chữ cấm, so với JSON của chính lượt đó. Trả về số mã đã kiểm."""
    cap = data["config"]["max_headlines_per_holding"]
    text = page.locator("#result").text_content() + page.locator("#weightedPanel").text_content()
    for phrase in FORBIDDEN_TAB3:
        assert phrase not in text, phrase
    labels = page.locator("#result .cov-funnel").evaluate_all("nodes => nodes.map((n) => n.getAttribute('aria-label'))")
    checked = 0
    for h in data["holdings"]:
        assert h["candidates_total"] == len(h["rejected"]) + len(h["headlines"]) + len(h["not_scored"]), h["symbol"]
        expected = funnel_label(h, cap)
        if h["w"] > 0 or any(label == expected for label in labels):
            assert expected in labels, (expected, labels)
            checked += 1
        counts = Counter(row["reason_code"] for row in h["rejected"])
        if not counts:
            continue
        row_box = page.locator(".cov-row", has=page.locator(".cov-row-name > strong").get_by_text(h["short"], exact=True))
        if row_box.count() == 0:
            continue
        fold = row_box.first.locator(".cov-rejected")
        assert fold.count() == 1 and f"Bị luật tự động loại ({len(h['rejected'])})" in fold.locator("summary").text_content(), h["symbol"]
        heads = fold.first.locator("h5").all_text_contents()
        order = sorted(counts, key=lambda code: REASON_ORDER.index(code) if code in REASON_ORDER else len(REASON_ORDER))
        assert [head.rsplit("(", 1)[1].rstrip(")") for head in heads] == [str(counts[code]) for code in order], (h["symbol"], heads)
        assert fold.first.locator(".cov-record").count() == len(h["rejected"])
        # Không hiện tỷ lệ % bị loại: chỉ xét chữ của khối (tiêu đề tin có thể chứa "%").
        labels_text = fold.first.locator("summary, h5, .cov-reason-counts, .method-note").all_text_contents()
        assert not any("%" in part for part in labels_text), labels_text
        for row in h["rejected"]:
            for flag in row.get("pattern_flags") or []:
                if flag != row["reason_code"]:
                    assert fold.first.locator(".cov-record", has_text=row["title"][:40]).locator(".cov-record-note").count() >= 1, row["title"]
    old = sum(1 for h in data["holdings"] for row in h["rejected"] if row["old_filter_keep"])
    summary = page.locator(".cov-fold > summary", has_text="Khớp tên theo bộ lọc Tab 1–2").inner_text()
    assert f": {old} bản ghi bị luật hiện tại loại nhưng khớp tên" in summary, summary
    return checked


def strip_volatile(body):
    body = dict(body)
    body.pop("timing_ms", None)
    body.pop("cache", None)
    return body


def coverage_checks(page, base, out):
    rows_out = []
    url = base + "/api/v2/sentiment/portfolio/coverage"

    # a. Danh mục mặc định (đủ 100% vốn có tin).
    response, data, sent, calls = submit_coverage(page)
    posted = httpx.post(url, json=sent).json()
    assert response.status == 200 and calls == 1 and strip_volatile(data) == strip_volatile(posted)
    p = data["portfolio"]
    summary = page.locator(".cov-summary").inner_text()
    assert f"{round(p['coverage'] * 100)}% vốn" in summary and vi_number(p["score"], 2) in summary, summary
    assert data["data_mode"].upper() in summary
    with_news = [h for h in data["holdings"] if h["has_news"] and h["w"] > 0]
    assert page.locator(".cov-row-fill").count() == len(with_news)
    sum_text = page.locator(".cov-sum").first.inner_text()
    assert f"= {vi_number(sum(h['contribution'] for h in with_news), 4)}" in sum_text and vi_number(p["score"], 4) == vi_number(sum(h["contribution"] for h in with_news), 4), sum_text
    assert page.locator(".cov-bound-track").count() == 0 and "Các mã tham gia điểm tổng hợp" in page.locator("#result").inner_text()
    page.locator("#result").screenshot(path=str(out / "coverage-default.png"))
    weights = ",".join(f"{q['symbol']}:{q['weight']:g}" for q in sent["positions"])
    rows_out.append(f"| coverage | {weights} | POST 200 | JSON = POST · C {p['coverage']:.0%} · {len(with_news)} thanh · tổng thanh = S · không có dải khoảng | — |")
    checked = funnel_checks(page, data)
    rows_out.append(f"| coverage | {weights} | — | phễu {checked} mã = JSON · nhóm lý do đúng số · khối Tab 1–2 đúng số · không còn chữ cấm | — |")

    # b. Một mã không tìm thấy tin.
    fill_positions(page, [("COMI", 50, ""), ("ETEL", 30, ""), ("HRHO", 20, "")])
    response, data, sent, calls = submit_coverage(page)
    p = data["portfolio"]
    assert response.status == 200 and calls == 1 and p["coverage"] < 1 and "bound" not in p
    empty = page.locator(".cov-row-empty")
    assert empty.count() == 1 and empty.locator(".cov-row-fill").count() == 0 and "chưa có điểm" in empty.inner_text()
    assert "HRHO: chưa có tin được chấm" in page.locator("#result").inner_text()
    assert page.locator(".cov-bound-track").count() == 0
    funnel_checks(page, data)
    page.locator("#result").screenshot(path=str(out / "coverage-missing.png"))
    rows_out.append("| coverage | COMI:50,ETEL:30,HRHO:20 | POST 200 | HRHO chưa có điểm, không suy diễn | — |")

    # c. So A/B: nút điền ví dụ, rồi một ví dụ thiếu tin.
    if not page.locator("#compareToggle").is_checked():
        page.locator("#compareToggle").click()
    page.locator("#comparePreset").click()
    cases = [("ví dụ A 5×20 / B 50-30-20", None), ("A thiếu tin", [("COMI", 50, 20), ("HRHO", 50, 50), ("ETEL", 0, 30)])]
    for name, rows in cases:
        if rows:
            fill_positions(page, rows, compare=True)
        symbols = page.locator("#positionRows input[name=symbol]")
        values_b = page.locator("#positionRows input[name=weightB]")
        weights_b = [(symbols.nth(i).input_value(), float(values_b.nth(i).input_value() or 0)) for i in range(5)]
        response, data, sent, calls = submit_coverage(page)
        assert response.status == 200 and calls == 1, (name, calls)
        posted_b = httpx.post(url, json={"positions": [{"symbol": s_, "weight": w} for s_, w in weights_b if s_ and w > 0]}).json()
        s_a, s_b = data["portfolio"]["score"], posted_b["portfolio"]["score"]
        cards = page.locator(".cov-ab-card .cov-ab-score").all_inner_texts()
        assert cards[0] == vi_number(s_a, 2) and cards[1] == vi_number(s_b, 2) and cards[2] == vi_number(s_b - s_a, 2), (name, cards)
        calc = page.locator(".cov-calc").text_content()
        assert f"= {vi_number(s_b, 6)}" in calc and f"= {vi_number(s_b - s_a, 6)}" in calc and "Khớp" in calc, calc
        delta_sum = page.locator(".cov-switch-panel:not(.hidden) .cov-sum").inner_text()
        assert f"= {vi_number(s_b - s_a, 4)}" in delta_sum, delta_sum
        bounds = page.locator(".cov-bound-track").count()
        expected_bounds = 0
        assert bounds == expected_bounds, (name, bounds, expected_bounds)
        funnel_checks(page, data)
        page.locator("#result").screenshot(path=str(out / f"coverage-compare-{len(rows_out)}.png"))
        rows_out.append(f"| coverage A/B | {name} | 1 POST 200 | S_A {s_a:+.6f} = backend · S_B {s_b:+.6f} = POST riêng · B − A {s_b - s_a:+.6f} = tổng thanh | — |")

    # d. Màn hẹp 390 px và 320 px: không tràn ngang (đóng rồi mở mọi mục chi tiết), không bảng nào phải cuộn ngang.
    for width in PHONE_WIDTHS:
        page.set_viewport_size({"width": width, "height": 844})
        overflow = page.evaluate(OVERFLOW_JS)
        assert overflow <= 0, (width, overflow, page.evaluate(CULPRITS_JS))
        page.locator("#result").screenshot(path=str(out / f"coverage-compare-phone-{width}.png"))
        page.evaluate("() => { window.__wasOpen = [...document.querySelectorAll('#result details')].map((d) => d.open); document.querySelectorAll('#result details').forEach((d) => { d.open = true; }); }")
        opened = page.evaluate(OVERFLOW_JS)
        assert opened <= 0, (width, opened, page.evaluate(CULPRITS_JS))
        # Bảng của tab 3 thành thẻ trên màn hẹp: không khung bảng nào phải cuộn ngang bên trong.
        scrollers = page.evaluate("() => [...document.querySelectorAll('#result .table-wrap')].filter((w) => w.scrollWidth > w.clientWidth + 1).length")
        assert scrollers == 0, (width, scrollers)
        page.locator(".cov-row").first.screenshot(path=str(out / f"coverage-phone-holding-open-{width}.png"))
        page.evaluate("() => document.querySelectorAll('#result details').forEach((d, i) => { d.open = window.__wasOpen[i]; })")
        rows_out.append(f"| coverage A/B | màn {width} px | — | không tràn ngang ({overflow} px; mở mọi mục: {opened} px; {scrollers} bảng phải cuộn ngang) | — |")

    # Tab 1 và tab 2 ở 320 px, sau khi có kết quả (chân trang "Luồng xử lý" dùng chung mọi tab).
    width = min(PHONE_WIDTHS)
    page.set_viewport_size({"width": width, "height": 844})
    tab_overflow = []
    for tab in ("stock", "portfolio"):
        page.locator(f"#{tab}Tab").click()
        with page.expect_response(lambda r: "/api/sentiment/" in r.url) as event:
            page.locator(f"#{tab}Form button").click()
        assert event.value.status == 200, tab
        page.locator("#result:not(.hidden)").wait_for()
        value = page.evaluate(OVERFLOW_JS)
        assert value <= 0, (tab, width, value, page.evaluate(CULPRITS_JS))
        tab_overflow.append(f"{tab} {value} px")
    page.screenshot(path=str(out / f"portfolio-phone-{width}.png"), full_page=True)
    rows_out.append(f"| tab 1 + tab 2 | màn {width} px, có kết quả | GET 200 | không tràn ngang ({'; '.join(tab_overflow)}) | — |")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator("#weightedTab").click()
    return rows_out


if __name__ == "__main__":
    main()
