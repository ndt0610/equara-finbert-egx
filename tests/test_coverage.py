"""Phần C: luật lọc đúng doanh nghiệp, độ phủ tin theo vốn, đóng góp từ tin đã chấm, vĩ mô tách riêng.

Các số "phải ra" đều tính tay được; ví dụ 50/30/20 và 40% là hai ví dụ đã thống nhất với pi.
Chạy: python -m pytest -q tests/test_coverage.py
"""

from __future__ import annotations

import asyncio
import importlib
import random
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from backend.config import Settings
from backend.providers.news import NewsAggregator, NewsItem, old_alias_filter
from backend.services.sentiment import SentimentService
from backend.upgrades.coverage import CoverageConfig, HoldingScore, group_signal, summarize_portfolio
from backend.upgrades.coverage_service import CoverageService, article_micro_selection, fetch_candidates
from backend.upgrades.relevance import judge, split_candidates
from backend.upgrades.service import UpgradedPortfolioService

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


def sig(score: float) -> dict:
    """Một nhóm tin có điểm cho sẵn (chỉ dùng cho phần gộp theo vốn)."""
    return {"n": 1, "score": score, "label": "Bullish" if score > 0 else "Bearish" if score < 0 else "Neutral"}


def portfolio(*rows, config=None):
    holdings = [HoldingScore(symbol, weight, None if score is None else sig(score)) for symbol, weight, score in rows]
    return holdings, summarize_portfolio(holdings, config)


# ---------------------------------------------------------------------------
# Test tính tay đã thống nhất
# ---------------------------------------------------------------------------
def test_missing_holding_is_not_imputed_and_observed_score_is_030():
    holdings, out = portfolio(("A", 50, 0.6), ("B", 30, -0.2), ("C", 20, None))
    a, b, c = holdings
    assert out["coverage"] == pytest.approx(0.80)
    assert out["score"] == pytest.approx(0.30)  # (50 × 0,6 + 30 × (−0,2)) / 80
    assert "bound" not in out
    assert out["direction"] == "positive"
    assert a.r == pytest.approx(0.625) and b.r == pytest.approx(0.375) and c.r is None
    assert a.contribution == pytest.approx(0.375) and b.contribution == pytest.approx(-0.075) and c.contribution is None


def test_observed_score_is_not_suppressed_by_missing_capital():
    _, out = portfolio(("A", 40, 0.6), ("B", 30, None), ("C", 30, None))
    assert out["coverage"] == pytest.approx(0.40)
    assert out["score"] == pytest.approx(0.60)
    assert "bound" not in out
    assert out["direction"] == "positive"


def test_zero_coverage_leaves_everything_empty_without_error():
    holdings, out = portfolio(("A", 50, None), ("B", 50, None))
    assert out["coverage"] == 0
    assert out["score"] is None and "bound" not in out and out["sum_contributions"] is None
    assert out["direction"] == "no_company_news"
    assert all(h.r is None and h.contribution is None for h in holdings)
    assert out["capital_by_label"]["no_news"] == pytest.approx(1.0)


def test_sum_of_contributions_equals_score_and_capital_by_label_sums_to_100():
    rng = random.Random(20261103)
    for _ in range(300):
        rows = []
        for i in range(rng.randint(1, 5)):
            score = None if rng.random() < 0.3 else rng.uniform(-1, 1)
            rows.append((f"S{i}", rng.choice([0, rng.uniform(0, 100)]), score))
        if sum(w for _, w, _ in rows) <= 0:
            continue
        holdings, out = portfolio(*rows)
        assert sum(out["capital_by_label"].values()) == pytest.approx(1.0)
        if out["score"] is not None:
            assert sum(h.contribution for h in holdings if h.contribution is not None) == pytest.approx(out["score"])
            assert -1 <= out["score"] <= 1
            assert "bound" not in out
            assert out["score_scope"] == "observed_scored_news"


def test_direction_describes_observed_news_regardless_of_capital_share():
    _, out = portfolio(("A", 50, 1.0), ("B", 50, None))
    assert "bound" not in out
    _, out = portfolio(("A", 51, 1.0), ("B", 49, None))
    assert out["direction"] == "positive"


# ---------------------------------------------------------------------------
# Các ca a, b, c, c2 của lệnh kỹ thuật bản 1 (c và c2 chỉ khi bật ngưỡng 65%, mặc định tắt)
# ---------------------------------------------------------------------------
def test_case_a_and_b():
    holdings, out = portfolio(("A", 70, 0.4), ("B", 30, None))
    assert out["coverage"] == pytest.approx(0.7) and out["score"] == pytest.approx(0.4) and holdings[0].contribution == pytest.approx(0.4)
    holdings, out = portfolio(("A", 50, 0.4), ("C", 20, -0.5), ("B", 30, None))
    a, c, _ = holdings
    assert a.r == pytest.approx(0.7143, abs=1e-4) and c.r == pytest.approx(0.2857, abs=1e-4)
    assert a.contribution == pytest.approx(0.2857, abs=1e-4) and c.contribution == pytest.approx(-0.1429, abs=1e-4)
    assert out["score"] == pytest.approx(0.1429, abs=1e-4)


def test_removed_coverage_gate_cannot_hide_observed_score(monkeypatch):
    monkeypatch.setenv("COVERAGE_MIN_FOR_SCORE", "0.99")
    config = CoverageConfig.from_environment()
    _, out = portfolio(("A", 1, 0.4), ("B", 99, None), config=config)
    assert out["score"] == pytest.approx(0.4)
    assert "min_coverage_for_score" not in config.to_dict()
    assert out["represented_symbols"] == ["A"]
    assert out["unscored_symbols"] == ["B"]

def test_all_three_scored_example_and_missing_not_same_as_neutral():
    _, out = portfolio(("A", 50, 0.6), ("B", 30, -0.2), ("C", 20, 0.1))
    assert out["score"] == pytest.approx(0.26)
    assert out["coverage"] == 1
    assert out["unscored_symbols"] == []
    _, neutral = portfolio(("A", 50, 0.6), ("B", 30, -0.2), ("C", 20, 0))
    _, absent = portfolio(("A", 50, 0.6), ("B", 30, -0.2), ("C", 20, None))
    assert neutral["score"] == pytest.approx(0.24)
    assert absent["score"] == pytest.approx(0.30)

def test_balanced_score_is_distinct_from_no_data():
    _, zero = portfolio(("A", 50, 0.4), ("B", 50, -0.4))
    _, empty = portfolio(("A", 100, None))
    assert zero["score"] == 0 and zero["direction"] == "balanced"
    assert empty["score"] is None and empty["direction"] == "no_company_news"


def test_default_config_has_every_experimental_option_off():
    config = CoverageConfig()
    assert config.experimental_options_on() == [] and config.plain_mean
    assert config.lookback_days == 90 and config.max_headlines_per_holding == 15 and config.macro_limit == 4
    assert CoverageConfig.from_environment() == config or CoverageConfig.from_environment().experimental_options_on()


def test_holding_score_is_the_reconstruction_mean():
    rows = [
        {"probabilities": {"positive": 0.6, "negative": 0.1, "neutral": 0.3}},
        {"probabilities": {"positive": 0.1, "negative": 0.5, "neutral": 0.4}},
    ]
    out = group_signal(rows, kind="micro", config=CoverageConfig(), now=NOW)
    assert out["score"] == pytest.approx((0.6 + 0.1) / 2 - (0.1 + 0.5) / 2)
    assert sum(out["shares"]) == pytest.approx(out["score"])
    assert out["label"] == "Neutral"  # trung bình 0,35 / 0,30 / 0,35: không có xác suất lớn nhất duy nhất
    shrunk = group_signal(rows, kind="micro", config=CoverageConfig(prior_strength=0.5), now=NOW)
    assert shrunk["score"] == pytest.approx(0.05 * 2 / 2.5) and sum(shrunk["shares"]) == pytest.approx(shrunk["score"])


# ---------------------------------------------------------------------------
# Luật lọc relevance-v1
# ---------------------------------------------------------------------------
def news(title, description=None, days=0.0, url=None, symbol="COMI.EGX"):
    published = None if days is None else (NOW - timedelta(days=days)).isoformat()
    return NewsItem(title, url, published, "test", "micro", symbol, description)


COMI = ("COMI", "CIB", "Commercial International Bank")
ETEL = ("ETEL", "Telecom Egypt")


def test_whole_word_match_fixes_coming_substring():
    item = news("Egypt prepares for coming debt repayments", "Egypt EGX update")
    assert old_alias_filter(item, COMI)  # bộ lọc cũ: "comi" nằm trong "coming"
    verdict = judge(item, COMI, now=NOW)
    assert not verdict.keep and verdict.reason_code == "name_not_in_title" and verdict.old_filter_keep
    assert judge(news("CIB's profit rises"), COMI, now=NOW).keep


def test_name_must_be_in_title_not_only_description():
    verdict = judge(news("Egypt banks grow", "Commercial International Bank leads"), COMI, now=NOW)
    assert not verdict.keep and verdict.reason_code == "name_only_in_description"


def test_case_f_football_headline_is_not_counted_but_league_table_is():
    verdict = judge(news("Telecom Egypt SC held to a draw in the Premier League", symbol="ETEL.EGX"), ETEL, now=NOW)
    assert not verdict.keep and verdict.reason_code == "sports"
    assert judge(news("CIB tops Egypt league table for syndicated loans"), COMI, now=NOW).keep
    assert judge(news("Telecom Egypt goal: match last year's growth", symbol="ETEL.EGX"), ETEL, now=NOW).keep


ADIB = ("ADIB", "Abu Dhabi Islamic Bank", "Abu Dhabi Islamic Bank Egypt")


def test_adib_parent_bank_headlines_are_not_adib_egypt():
    """Tiêu đề thật của ngân hàng mẹ ở UAE (GlobalCapital, MEA Finance, tìm ngày 04/11/2026): bản 1 giữ nhầm."""
    for title in (
        "ADIB markets new AT1 as call date looms",
        "Abu Dhabi Islamic Bank says time is right for Iraq launch",
        "ADIB delivers strong Q1 2026 performance as profit and balance sheet growth gain momentum",
    ):
        verdict = judge(news(title, symbol="ADIB.EGX"), ADIB, now=NOW)
        assert not verdict.keep and verdict.reason_code == "ambiguous_name", title
        assert "UAE" in verdict.reason and "Ai Cập" in verdict.reason
        assert verdict.old_filter_keep  # bộ lọc cũ (và luật bản 1) giữ các tin này
    # Tin thật của ADIB Egypt (lượt 03/11) vẫn được giữ; tiêu đề tự dựng có "Egypt"/"Misr" cũng vậy.
    for title in (
        "Abu Dhabi Islamic Bank Egypt stock adds payment security certification - ad-hoc-news.de",
        "ADIB-Egypt posts EGP 1.2bn profit",
        "ADIB Misr launches new card",
    ):
        assert judge(news(title, symbol="ADIB.EGX"), ADIB, now=NOW).keep, title


def test_real_telecom_egypt_football_and_company_titles():
    """Tiêu đề thật tìm ngày 04/11/2026 (misrconnect, filgoal, arabfinance, meatechwatch)."""
    assert judge(news("Shocking Egypt Cup Upset: Telecom Egypt Eliminates Al Ahly in Round of 32"), ETEL, now=NOW).reason_code == "sports"
    assert judge(news("Preview: Telecom's survival hope lies in Ittihad's hands"), ETEL, now=NOW).reason_code == "name_not_in_title"
    for title in (
        "Telecom Egypt consolidated profits leap in H1 2026",
        "Telecom Egypt considers early activation of new spectrum in 2027",
        "Telecom Egypt Targets Strong Revenue Growth and Profitability in 2026 Budget",
        "Telecom Egypt joins FTSE emerging markets index after mid-cap upgrade - ArabFinance",
    ):
        assert judge(news(title), ETEL, now=NOW).keep, title


def test_macro_box_keeps_only_economic_headlines():
    """2 tin vĩ mô thật của cả lượt 01/11 và 03/11 là tin chính trị; 4 tin kịch bản 01/11 là tin kinh tế."""
    from backend.upgrades.relevance import judge_macro

    def macro(title):
        return NewsItem(title=title, url=None, published_at=NOW.isoformat(), source="BBC RSS", kind="macro")

    for title in (
        "Democratic senator blames Egypt press crackdown on US military aid decision",
        "Egypt court fines journalist Lina Attalah and orders news site's closure",
    ):
        verdict = judge_macro(macro(title), now=NOW)
        assert not verdict.keep and verdict.reason_code == "not_economic", title
    for title in (
        "Egypt secures $1.2 billion IMF loan disbursement after programme review",
        "Egypt's annual inflation accelerates to 26%, highest in five months",
        "Egypt's central bank unexpectedly raises interest rates by 200 basis points",
        "Egypt's non-oil private sector PMI unchanged at 49.5 in October",
    ):
        assert judge_macro(macro(title), now=NOW).keep, title


def test_label_counts_explain_neutral_label_with_positive_score():
    """COMI ngày 03/11: 2 tiêu đề tích cực, 4 trung tính, 0 tiêu cực → nhãn Neutral nhưng điểm +0,383."""
    rows = [{"probabilities": p} for p in (
        {"positive": 0.84, "negative": 0.01, "neutral": 0.15},
        {"positive": 0.94, "negative": 0.02, "neutral": 0.04},
        {"positive": 0.15, "negative": 0.01, "neutral": 0.84},
        {"positive": 0.17, "negative": 0.01, "neutral": 0.82},
        {"positive": 0.10, "negative": 0.01, "neutral": 0.89},
        {"positive": 0.18, "negative": 0.03, "neutral": 0.79},
    )]
    signal = group_signal(rows, kind="micro", config=CoverageConfig(), now=NOW)
    assert signal["label"] == "Neutral" and signal["score"] > 0.3
    assert signal["label_counts"] == {"Bullish": 2, "Neutral": 4, "Bearish": 0}
    # Thanh "vốn theo nhãn" xếp mã này vào Neutral; kết quả kèm câu giải thích nêu đúng điểm của mã.
    summary = summarize_portfolio([HoldingScore("COMI.EGX", 50, signal), HoldingScore("FWRY.EGX", 50, None)])
    assert summary["capital_by_label"]["Neutral"] == 0.5 and summary["score"] > 0.3
    assert f"COMI {signal['score']:+.3f}" in summary["capital_by_label_note"]
    assert summarize_portfolio([HoldingScore("FWRY.EGX", 100, None)])["capital_by_label_note"] is None


def test_data_pages_are_not_news():
    for title in (
        "COMMERCIAL INTERNATIONAL BANK EGYPT (COMI) Equity Price and Quote - London Stock Exchange",
        "Commercial International Bank Seasonal Returns Chart - Yahoo! Finance Canada",
        "COMI Historical Data - Investing.com",
    ):
        verdict = judge(news(title), COMI, now=NOW)
        assert not verdict.keep and verdict.reason_code == "not_news_page", title
    assert judge(news("Telecom Egypt charts growth plan", symbol="ETEL.EGX"), ETEL, now=NOW).keep


def test_tradingview_estimates_page_is_data_but_estimates_news_is_kept():
    """Tiêu đề thật Codex thấy ngày 04/11 (Windows, truy vấn rộng FWRY): bản 1 giữ, bản 2 loại.
    Chỉ loại đúng dạng "tên trang – SÀN:MÃ"; tin có chữ "estimates" vẫn giữ."""
    fawry = ("FWRY", "Fawry")
    page = judge(news("Fawry For Banking Technology And Electronic Payment Estimates – EGX:FWRY - TradingView", symbol="FWRY.EGX"), fawry, now=NOW)
    assert not page.keep and page.reason_code == "not_news_page" and page.old_filter_keep
    for title in ("Fawry beats profit estimates - Reuters", "Fawry (EGX:FWRY) earnings beat estimates", "Fawry raises 2026 forecast"):
        assert judge(news(title, symbol="FWRY.EGX"), fawry, now=NOW).keep, title


def test_stale_duplicate_and_undated():
    assert judge(news("CIB profit rises", days=91), COMI, now=NOW).reason_code == "stale"
    assert judge(news("CIB profit rises", days=89), COMI, now=NOW).keep
    assert judge(news("CIB profit rises", days=None), COMI, now=NOW).keep  # không có ngày: giữ, như bản tái dựng
    kept, rejected = split_candidates([news("CIB profit rises!"), news("CIB  profit rises")], COMI, now=NOW)
    assert len(kept) == 1 and rejected[0][1].reason_code == "duplicate"


def test_fixture_micro_headlines_all_pass_and_extra_fixture_rows_all_fail():
    import json

    from backend.providers.news import company_aliases

    rows = json.loads((ROOT / "fixtures" / "news.json").read_text(encoding="utf-8"))["items"]
    for row in rows:
        if row["kind"] == "micro":
            item = NewsItem(row["title"], None, None, "x", "micro", row["symbol"], None)
            assert judge(item, company_aliases(row["symbol"]), now=NOW).keep, row["title"]
    extra = json.loads((ROOT / "fixtures" / "coverage_candidates.json").read_text(encoding="utf-8"))["items"]
    reasons = set()
    for row in extra:
        item = NewsItem(row["title"], None, None, "x", "micro", row["symbol"], row.get("description"))
        verdict = judge(item, company_aliases(row["symbol"]), now=NOW)
        assert not verdict.keep and verdict.old_filter_keep, row["title"]  # bộ lọc cũ giữ, luật mới loại
        reasons.add(verdict.reason_code)
    assert reasons == {"not_news_page", "name_not_in_title", "sports", "name_only_in_description"}


# ---------------------------------------------------------------------------
# API ở chế độ fixture
# ---------------------------------------------------------------------------
@pytest.fixture()
def fixture_client(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "fixture")
    import backend.app as app_module

    app_module = importlib.reload(app_module)
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as client:
        yield client


def test_coverage_get_equals_post_and_sums_add_up(fixture_client):
    got = fixture_client.get("/api/v2/sentiment/portfolio/coverage?positions=COMI:50,ETEL:30,FWRY:20")
    posted = fixture_client.post(
        "/api/v2/sentiment/portfolio/coverage",
        json={"positions": [{"symbol": "COMI", "weight": 50}, {"symbol": "ETEL", "weight": 30}, {"symbol": "FWRY", "weight": 20}]},
    )
    assert got.status_code == posted.status_code == 200
    a, b = got.json(), posted.json()
    for body in (a, b):
        body.pop("timing_ms")
        body.pop("cache")
    assert a == b
    p = a["portfolio"]
    assert p["coverage"] == pytest.approx(1.0) and "bound" not in p
    assert sum(h["contribution"] for h in a["holdings"]) == pytest.approx(p["score"])
    for h in a["holdings"]:
        assert sum(row["contribution"] for row in h["headlines"]) == pytest.approx(h["contribution"])
        assert sum(row["share_of_holding_score"] for row in h["headlines"]) == pytest.approx(h["score"])
        assert h["rejected"] and all(row["reason"] for row in h["rejected"])  # fixture có tin bị loại cho cả 3 mã


@pytest.mark.parametrize("symbols", [["COMI", "ETEL", "FWRY"], ["COMI", "ETEL", "FWRY", "ADIB", "EFIH"], ["ADIB"]])
def test_article_box_equals_original_portfolio_tab(fixture_client, symbols):
    original = fixture_client.get(f"/api/sentiment/portfolio?symbols={','.join(symbols)}").json()
    query = ",".join(f"{s}:{10 * (i + 1)}" for i, s in enumerate(symbols))
    article = fixture_client.get(f"/api/v2/sentiment/portfolio/coverage?positions={query}").json()["article_method"]
    assert article["score"] == pytest.approx(original["score"])
    assert article["sentiment"] == original["sentiment"]
    assert [row["title"] for row in article["headlines"]] == [row["title"] for row in original["headlines"]]


def test_unknown_symbol_is_shown_as_no_news(fixture_client):
    body = fixture_client.get("/api/v2/sentiment/portfolio/coverage?positions=COMI:40,HRHO:60").json()
    hrho = body["holdings"][1]
    assert hrho["has_news"] is False and hrho["n"] == 0 and hrho["contribution"] is None and hrho["label"] == "no_news"
    assert body["portfolio"]["coverage"] == pytest.approx(0.4) and body["portfolio"]["score"] == pytest.approx(body["holdings"][0]["score"])


def test_case_d_macro_news_never_moves_company_score(fixture_client, monkeypatch):
    before = fixture_client.get("/api/v2/sentiment/portfolio/coverage?positions=COMI:60,ETEL:40").json()
    service = fixture_client.app.state.service
    for row in service.fixture_data["items"]:
        if row["kind"] == "macro":
            monkeypatch.setitem(row, "probabilities", {"positive": 0.01, "negative": 0.98, "neutral": 0.01})
    after = fixture_client.get("/api/v2/sentiment/portfolio/coverage?positions=COMI:60,ETEL:40").json()
    assert after["portfolio"]["score"] == pytest.approx(before["portfolio"]["score"])
    assert after["macro"]["score"] == pytest.approx(-0.97) and after["macro"]["score"] < before["macro"]["score"]
    assert after["article_method"]["score"] < before["article_method"]["score"]  # cách bài báo thì bị kéo xuống


def test_case_e_adib_like_numbers():
    """Ca dựng theo số của lượt Windows 03/11 (không phải bản chụp thật): 2 tin ADIB gần trung tính, 2 tin vĩ mô rất âm."""
    from backend.services.sentiment import aggregate_probabilities

    company = [{"positive": 0.10, "negative": 0.104, "neutral": 0.796}, {"positive": 0.05, "negative": 0.054, "neutral": 0.896}]
    macro = [{"positive": 0.02, "negative": 0.921, "neutral": 0.059}] * 2
    s = group_signal([{"probabilities": p} for p in company], kind="micro", config=CoverageConfig(), now=NOW)["score"]
    m = group_signal([{"probabilities": p} for p in macro], kind="macro", config=CoverageConfig(), now=NOW)["score"]
    _, _, article = aggregate_probabilities(company + macro)
    assert s == pytest.approx(-0.004) and m == pytest.approx(-0.901) and article == pytest.approx(-0.4525)


def test_bad_requests_are_rejected(fixture_client):
    for query in ("COMI:0", "COMI:50,COMI:50", "COMI:abc", "A:1,B:1,C:1,D:1,E:1,F:1", "COMI:inf"):
        assert fixture_client.get(f"/api/v2/sentiment/portfolio/coverage?positions={query}").status_code == 422, query
    assert fixture_client.get("/api/v2/coverage/config").json()["experimental_options_on"] == []


def test_no_trading_advice_wording_in_upgrade_tab(fixture_client):
    body = fixture_client.get("/api/v2/sentiment/portfolio/coverage?positions=COMI:50,ETEL:50").json()
    words = re.compile(r"\b(mua|bán|buy|sell|nên đầu tư|khuyến nghị mua)\b", re.IGNORECASE)
    strings = [body["disclaimer"], *body["notes"], body["portfolio"]["direction_text"], body["macro"]["note"]]
    assert "không phải tư vấn đầu tư" in body["disclaimer"]
    assert not any(words.search(text) for text in strings[1:])
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    panel = html.split('id="weightedPanel"', 1)[1].split("</section>", 1)[0]
    assert not words.search(panel) and "β" not in panel
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    coverage_js = js.split("// [NÂNG CẤP C]", 1)[1]
    assert not words.search(coverage_js.split("function tgNumber", 1)[0].replace("không phải tư vấn đầu tư", ""))


# ---------------------------------------------------------------------------
# Chế độ live với nguồn tin giả lập (không ra internet)
# ---------------------------------------------------------------------------
SECRET = "eodhd_secret_khong_duoc_hien"


def rss(entries) -> bytes:
    body = ""
    for title, description, days in entries:
        date = "" if days is None else f"<pubDate>{format_datetime(NOW - timedelta(days=days))}</pubDate>"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
        body += f"<item><title>{title}</title><link>https://news.example/{slug}</link>{date}<description>{description}</description></item>"
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode()


COMI_FEED = [
    ("Egypt prepares for coming debt repayments", "Egypt EGX update", 0.1),  # cũ giữ ("comi"), mới loại
    ("Egypt banks grow", "Commercial International Bank leads", 0.2),  # chỉ có trong mô tả
    ("CIB profit rises 20%", "CIB", 1.0),
    ("CIB profit rises 20%", "CIB", 1.0),  # trùng
    ("CIB old news", "CIB", 120),  # quá 90 ngày
    ("COMMERCIAL INTERNATIONAL BANK EGYPT Equity Price and Quote - London Stock Exchange", "", 2.0),
    ("CIB undated update", "CIB", None),
] + [(f"CIB filler story {i}", "CIB", 3.0 + i) for i in range(20)] + [
    ("CIB very fresh story beyond position 20", "CIB", 0.01),  # sau mục thứ 20 mà bộ lọc cũ giữ
]
TIER2_FEED = [("CIB tier two story", "CIB", 0.5), ("CIB profit rises 20%", "CIB", 1.0)]


def handler_factory(calls, eodhd_rows=None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        host = request.url.host
        if host == "eodhd.com":
            if "s" in parse_qs(request.url.query.decode()):
                return httpx.Response(200, json=eodhd_rows or [])
            return httpx.Response(200, json=[])
        if host == "news.google.com":
            query = parse_qs(request.url.query.decode())["q"][0]
            if "Egypt economy" in query:
                return httpx.Response(200, content=rss([("Egypt economy outlook", "Egypt", 0.5)]))
            if "EGX stock" in query and "Commercial International Bank" in query:
                return httpx.Response(200, content=rss(COMI_FEED))
            if "Commercial International Bank" in query:
                return httpx.Response(200, content=rss(TIER2_FEED))
            return httpx.Response(200, content=rss([("Telecom Egypt SC wins derby", "Telecom Egypt", 0.3), ("Telecom Egypt expands fibre", "Telecom Egypt", 0.4)]))
        if host == "feeds.bbci.co.uk":
            return httpx.Response(200, content=rss([(f"Egypt macro {i}", "Egypt", 0.1 * i) for i in range(1, 7)]))
        return httpx.Response(404)

    return handler


def live_settings(monkeypatch, eodhd: bool) -> Settings:
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("INFERENCE_PROVIDER", "hf-inference")
    monkeypatch.setenv("HF_INFERENCE_URL", "http://selfhosted.local/models/ProsusAI/finbert")
    if eodhd:
        monkeypatch.setenv("EODHD_NEWS_API_TOKEN", SECRET)
    else:
        monkeypatch.delenv("EODHD_NEWS_API_TOKEN", raising=False)
    return Settings.from_environment()


def fake_probs(title: str) -> dict[str, float]:
    pos = (len(title) % 7) / 10
    neg = (sum(map(ord, title)) % 5) / 10
    return {"positive": pos, "negative": neg, "neutral": round(1 - pos - neg, 10)}


def live_services(monkeypatch, eodhd=False, eodhd_rows=None, config=None):
    calls: list[str] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler_factory(calls, eodhd_rows)))
    base = SentimentService(client, live_settings(monkeypatch, eodhd))
    scored: list[list[str]] = []

    async def classify_many(texts):
        scored.append(list(texts))
        return [fake_probs(t) for t in texts]

    monkeypatch.setattr(base.inference, "classify_many", classify_many)
    coverage = CoverageService(UpgradedPortfolioService(base), config or CoverageConfig())
    return base, coverage, calls, scored


def test_article_selection_rebuilt_from_same_fetch_matches_collect_stock(monkeypatch):
    base, coverage, _, _ = live_services(monkeypatch)
    expected, _ = asyncio.run(base.news.collect_stock("COMI.EGX", limit=2))
    bundle = asyncio.run(fetch_candidates(base.news, "COMI.EGX", CoverageConfig(), eodhd_configured=False))
    rebuilt = article_micro_selection(bundle, eodhd_configured=False)
    assert [i.title for i in rebuilt] == [i.title for i in expected]
    assert "CIB very fresh story beyond position 20" not in [i.title for i in rebuilt]  # giữ đúng cắt [:20] của bản cũ
    assert rebuilt[0].title == "Egypt prepares for coming debt repayments"  # bản cũ chọn cả tin "coming"


def test_live_article_box_equals_live_portfolio_tab_and_one_fetch_per_source(monkeypatch):
    base, coverage, calls, scored = live_services(monkeypatch)
    original = asyncio.run(base.analyze_portfolio(["COMI.EGX", "ETEL.EGX"]))
    calls.clear()
    body = asyncio.run(coverage.analyze([("COMI.EGX", 60), ("ETEL.EGX", 40)]))
    assert body["article_method"]["score"] == pytest.approx(original["score"])
    assert [r["title"] for r in body["article_method"]["headlines"]] == [r["title"] for r in original["headlines"]]
    google_calls = [c for c in calls if "news.google.com" in c]
    # COMI: bậc 1 (23 tin phù hợp ≥ 10, không gọi bậc 2). ETEL: bậc 1 rồi bậc 2 (1 tin phù hợp < 10).
    # Vĩ mô: tin BBC không có tin kinh tế nào → gọi truy vấn Google tin kinh tế một lần. Không gọi lại cho ô cách bài báo.
    assert len(google_calls) == 4 and sum("EGX+stock" in c for c in google_calls) == 2
    tier2 = {r["symbol"]: r["status"] for r in body["providers"] if r.get("tier") == 2}
    assert tier2 == {"COMI.EGX": "skipped_enough_relevant", "ETEL.EGX": "candidates:2"}
    comi, etel = body["holdings"]
    titles = [h["title"] for h in comi["headlines"]]
    assert "Egypt prepares for coming debt repayments" not in titles and "CIB profit rises 20%" in titles
    assert comi["n"] == 15 and len(comi["not_scored"]) == 8  # 23 tin phù hợp, chấm 15 tin mới nhất
    assert comi["headlines"][0]["title"] == "CIB very fresh story beyond position 20"  # luật mới xét mọi ứng viên
    reasons = {r["reason_code"] for r in comi["rejected"]}
    assert reasons == {"name_not_in_title", "name_only_in_description", "duplicate", "stale", "not_news_page"}
    assert [h["title"] for h in etel["headlines"]] == ["Telecom Egypt expands fibre"]
    assert body["config"]["experimental_options_on"] == [] and body["config"]["tier2_below"] == 10
    # Ô vĩ mô của phần C: 4 tin BBC "Egypt macro i" không nói về kinh tế → bị loại; tin kinh tế từ Google được giữ.
    assert [h["title"] for h in body["macro"]["headlines"]] == ["Egypt economy outlook"]
    assert {r["reason_code"] for r in body["macro"]["rejected"]} == {"not_economic"} and len(body["macro"]["rejected"]) == 4
    # Ô cách bài báo vẫn dùng đúng 4 tin vĩ mô BBC như tab 2.
    assert sum(r["kind"] == "macro" for r in body["article_method"]["headlines"]) == sum(r["kind"] == "macro" for r in original["headlines"])
    # một lần chấm cho mọi tiêu đề cần, không lặp tiêu đề
    assert len(scored[-1]) == len(set(scored[-1]))


def test_eodhd_used_first_and_google_only_when_eodhd_has_no_relevant_news(monkeypatch):
    fresh = (NOW - timedelta(hours=2)).isoformat()
    rows = [{"title": "CIB raises capital", "link": "https://e.example/1", "date": fresh, "content": "CIB"}]
    # Tắt bậc 2: đúng thứ tự của collect_stock, EODHD có tin phù hợp thì không gọi Google.
    _, coverage, calls, _ = live_services(monkeypatch, eodhd=True, eodhd_rows=rows, config=CoverageConfig(tier2_below=None))
    body = asyncio.run(coverage.analyze([("COMI.EGX", 100)]))
    assert [h["source"] for h in body["holdings"][0]["headlines"]] == ["EODHD"]
    assert not any("news.google.com" in c and "Commercial" in c for c in calls)
    assert SECRET not in str(body)
    # Mặc định: EODHD mới có 1 tin phù hợp (< 10) → tìm thêm Google bậc 1; đủ 10 thì không gọi bậc 2.
    _, coverage, calls, _ = live_services(monkeypatch, eodhd=True, eodhd_rows=rows)
    body = asyncio.run(coverage.analyze([("COMI.EGX", 100)]))
    holding = body["holdings"][0]
    assert any("news.google.com" in c and "EGX+stock" in c for c in calls)
    assert {h["source"] for h in holding["headlines"]} == {"EODHD", "Google News RSS"} and holding["n"] == 15
    assert [r["status"] for r in body["providers"] if r.get("tier") == 2] == ["skipped_enough_relevant"]
    assert SECRET not in str(body)

    rows = [{"title": "Egypt markets wrap", "link": "https://e.example/2", "date": fresh, "content": "CIB shares"}]
    base, coverage, calls, _ = live_services(monkeypatch, eodhd=True, eodhd_rows=rows)
    original = asyncio.run(base.analyze_portfolio(["COMI.EGX"]))
    body = asyncio.run(coverage.analyze([("COMI.EGX", 100)]))
    assert any("news.google.com" in c and "Commercial" in c for c in calls)  # EODHD không có tin phù hợp → Google
    assert body["holdings"][0]["headlines"][0]["source"] == "Google News RSS"
    assert body["article_method"]["score"] == pytest.approx(original["score"])  # cách bài báo vẫn dùng tin EODHD
    assert SECRET not in str(body)


def test_tier2_by_default_below_10_relevant_and_can_be_turned_off(monkeypatch):
    """Bậc 2 bật mặc định (coverage-v2): truy vấn bậc 1 hẹp làm độ phủ đo độ hẹp của truy vấn, không đo tin."""
    assert CoverageConfig().tier2_below == 10
    for raw, expected in (("", 10), ("0", None), ("off", None), ("6", 6)):
        monkeypatch.setenv("COVERAGE_TIER2_BELOW", raw)
        assert CoverageConfig.from_environment().tier2_below == expected
    monkeypatch.delenv("COVERAGE_TIER2_BELOW")
    assert CoverageConfig(tier2_below=None).experimental_options_on() == ["tắt truy vấn bậc 2"]
    _, coverage, calls, _ = live_services(monkeypatch, config=CoverageConfig(tier2_below=None))
    body = asyncio.run(coverage.analyze([("ETEL.EGX", 100)]))
    assert not any(r.get("tier") == 2 for r in body["providers"]) and body["holdings"][0]["tier2_called"] is False
    _, coverage, calls, _ = live_services(monkeypatch, config=CoverageConfig(tier2_below=30))
    body = asyncio.run(coverage.analyze([("COMI.EGX", 100)]))
    tier2 = [r for r in body["providers"] if r.get("tier") == 2]
    assert tier2 and tier2[0]["status"].startswith("candidates:")
    assert "CIB tier two story" in [h["title"] for h in body["holdings"][0]["headlines"]]
    assert any(r["reason_code"] == "duplicate" and r["query_tier"] == 2 for r in body["holdings"][0]["rejected"])
    _, coverage, _, _ = live_services(monkeypatch, config=CoverageConfig(tier2_below=5))
    body = asyncio.run(coverage.analyze([("COMI.EGX", 100)]))
    assert [r["status"] for r in body["providers"] if r.get("tier") == 2] == ["skipped_enough_relevant"]


def test_second_request_reuses_news_and_scores(monkeypatch):
    _, coverage, calls, scored = live_services(monkeypatch)
    first = asyncio.run(coverage.analyze([("COMI.EGX", 50), ("ETEL.EGX", 50)]))
    n_calls = len(calls)
    second = asyncio.run(coverage.analyze([("COMI.EGX", 50), ("ETEL.EGX", 50)]))
    assert len(calls) == n_calls  # tin dùng lại trong 10 phút
    assert second["cache"]["inference_this_request"]["model_calls"] == 0  # xác suất dùng lại theo tiêu đề
    assert second["portfolio"] == first["portfolio"]
    assert all(row["status"].startswith("cache_hit(") for row in second["providers"] if "fetched_at" in row)


def test_missing_hf_token_stops_before_inference(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("INFERENCE_PROVIDER", "hf-inference")
    monkeypatch.delenv("HF_INFERENCE_URL", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    calls: list[str] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler_factory(calls)))
    base = SentimentService(client, Settings.from_environment())
    coverage = CoverageService(UpgradedPortfolioService(base))
    from backend.services.sentiment import AnalysisError

    with pytest.raises(AnalysisError) as error:
        asyncio.run(coverage.analyze([("COMI.EGX", 100)]))
    assert error.value.code == "missing_hf_token" and error.value.status_code == 424


def test_self_hosted_server_revision_is_forwarded_without_token():
    """Việc sót của vòng A: /api/health báo revision của máy chủ tự dựng thay vì null."""
    from backend.providers.hf_inference import HuggingFaceFinBERT

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok", "revision": "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    local = HuggingFaceFinBERT(client, "hf_secret", endpoint="http://127.0.0.1:8001/models/ProsusAI/finbert")
    assert asyncio.run(local.server_revision()) == "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
    assert asyncio.run(local.server_revision()) == "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
    assert len(seen) == 1 and str(seen[0].url) == "http://127.0.0.1:8001/health" and "authorization" not in seen[0].headers
    hosted = HuggingFaceFinBERT(client, "hf_secret")
    assert asyncio.run(hosted.server_revision()) is None and len(seen) == 1  # không hỏi huggingface.co


def test_portfolio_ui_has_observed_scope_without_hypothetical_bounds():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Các mã tham gia điểm tổng hợp" in js
    assert "không gán điểm 0" in js
    assert "boundSection" not in js and "view.bound" not in js


def test_case_e_real_adib_run_and_replay_of_03_11():
    """Lượt thật trên Windows 03/11/2026 22:29 (docs/du_lieu_03-11): tính lại không cần mạng, không cần model."""
    import json

    from backend.services.sentiment import aggregate_probabilities
    from scripts.replay_saved_runs import load_runs, replay

    folder = ROOT / "docs" / "du_lieu_03-11"
    adib = json.loads((folder / "ADIB-web.json").read_text(encoding="utf-8"))
    _, _, tab1 = aggregate_probabilities([h["probabilities"] for h in adib["headlines"]])
    assert tab1 == pytest.approx(adib["score"]) and round(tab1, 3) == -0.453  # cách bài báo, tab 1
    runs = load_runs(folder)
    only_adib = replay(runs, [("ADIB.EGX", 100)])
    assert only_adib["details"][0]["rejected"][0][1].startswith("Trang dữ liệu")  # trang "Seasonal Returns Chart"
    assert only_adib["portfolio"]["score"] == pytest.approx(0.018, abs=5e-4)  # gần trung tính
    assert only_adib["macro"] is None  # 2 tin vĩ mô thật là tin chính trị, không phải tin kinh tế
    assert [reason for _, reason in only_adib["macro_rejected"]] == ["Tin chung về Ai Cập, tiêu đề không nói về kinh tế hay thị trường"] * 2
    five = replay(runs, [(s, 20) for s in ("COMI.EGX", "ETEL.EGX", "FWRY.EGX", "ADIB.EGX", "EFIH.EGX")])
    assert five["portfolio"]["coverage"] == pytest.approx(0.8)  # FWRY: truy vấn bậc 1 không trả tin riêng nào
    assert five["portfolio"]["score"] == pytest.approx(0.293, abs=5e-4)
    assert five["portfolio"]["direction"] == "positive"
    assert five["article"]["score"] == pytest.approx(-0.058, abs=5e-4)  # gộp chung bị 2 tin vĩ mô kéo xuống
