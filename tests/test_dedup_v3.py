"""C3 bản 3: hồi quy cho bước loại trùng của tab 3 (relevance-v3) và khóa hành vi loại trùng của tab 1–2 (C2).

Các lỗi bản 2 mà bản 3 sửa (Codex phát hiện 04/11/2026):
- khóa được ghi vào tập "đã thấy" TRƯỚC khi xét tuổi, nên bản quá hạn đến trước che bản còn hạn cùng khóa;
- vì vậy kết quả phụ thuộc thứ tự bản ghi đến;
- tiêu đề rỗng bị ghi là "trùng".
Tab 1–2 vẫn dùng `deduplicate`/`usable_news` của bản tái dựng, KHÔNG sửa: các test cuối tệp khóa đúng hành vi đó.

Chạy: python -m pytest -q tests/test_dedup_v3.py
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.providers.news import NewsItem, deduplicate, usable_news
from backend.upgrades.relevance import (
    RULES_VERSION,
    dedup_key,
    judge,
    judge_macro,
    pattern_flags,
    screen,
    screen_macro,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
COMI = ("COMI", "CIB", "Commercial International Bank")
URL = "https://example.com/news/cib-profit"


def item(title="CIB profit rises", days=1.0, url=URL, source="test", description=None, kind="micro"):
    published = None if days is None else (NOW - timedelta(days=days)).isoformat()
    return NewsItem(title, url, published, source, kind, "COMI.EGX", description)


def outcome(items, ranks=None, aliases=COMI):
    """Lý do của từng bản ghi, theo nhãn nguồn (`source`) để so được giữa các hoán vị."""
    return {row.source: verdict.reason_code for row, verdict in zip(items, screen(items, aliases, now=NOW, ranks=ranks))}


def test_rules_version_is_v3():
    assert RULES_VERSION == "relevance-v3"


# ---------------------------------------------------------------------------
# Bản quá hạn không che bản còn hạn
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", [URL, None])
def test_stale_copy_first_does_not_hide_fresh_copy(url):
    rows = [item(days=120, url=url, source="cu"), item(days=3, url=url, source="moi")]
    assert outcome(rows) == {"cu": "stale", "moi": None}
    assert outcome(rows[::-1]) == {"cu": "stale", "moi": None}


@pytest.mark.parametrize("url", [URL, None])
def test_stale_copy_first_does_not_hide_undated_copy(url):
    rows = [item(days=120, url=url, source="cu"), item(days=None, url=url, source="khong_ngay")]
    assert outcome(rows) == {"cu": "stale", "khong_ngay": None}


@pytest.mark.parametrize("url", [URL, None])
def test_permutations_of_stale_fresh_undated_give_one_result(url):
    rows = [item(days=120, url=url, source="cu"), item(days=5, url=url, source="moi"), item(days=None, url=url, source="khong_ngay")]
    expected = {"cu": "stale", "moi": None, "khong_ngay": "duplicate"}
    for order in itertools.permutations(rows):
        assert outcome(list(order)) == expected, [row.source for row in order]


def test_newest_dated_copy_wins_and_undated_only_when_no_date():
    rows = [item(days=10, source="d10"), item(days=2, source="d2"), item(days=30, source="d30"), item(days=None, source="nd")]
    for order in itertools.permutations(rows):
        assert outcome(list(order)) == {"d10": "duplicate", "d2": None, "d30": "duplicate", "nd": "duplicate"}
    only_undated = [item(days=None, source="b"), item(days=None, source="a")]
    for order in itertools.permutations(only_undated):
        assert outcome(list(order)) == {"a": None, "b": "duplicate"}  # hòa ngày và bậc: phá hòa theo trường còn lại


def test_unparseable_date_counts_as_undated():
    rows = [NewsItem("CIB profit rises", URL, "not a date", "hong", "micro", "COMI.EGX"), item(days=4, source="moi")]
    assert outcome(rows) == {"hong": "duplicate", "moi": None}


def test_equal_dates_keep_lower_query_tier():
    rows = [item(days=1, source="bac2"), item(days=1, source="bac1")]
    assert outcome(rows, ranks=[2, 1]) == {"bac2": "duplicate", "bac1": None}
    assert outcome(rows[::-1], ranks=[1, 2]) == {"bac2": "duplicate", "bac1": None}


def test_newer_date_beats_lower_tier():
    rows = [item(days=5, source="bac1_cu_hon"), item(days=1, source="bac2_moi_hon")]
    assert outcome(rows, ranks=[1, 2]) == {"bac1_cu_hon": "duplicate", "bac2_moi_hon": None}


def test_random_mixed_batches_are_order_independent():
    rng = random.Random(20261104)
    urls = [URL, "https://example.com/b", None]
    titles = ["CIB profit rises", "CIB opens branch", "Egypt economy grows", ""]
    for _ in range(200):
        rows, ranks = [], []
        for index in range(rng.randint(2, 7)):
            days = rng.choice([None, 0.5, 2.0, 2.0, 40.0, 95.0, 300.0])
            rows.append(item(title=rng.choice(titles), days=days, url=rng.choice(urls), source=f"s{index}"))
            ranks.append(rng.choice([1, 2]))
        expected = outcome(rows, ranks)
        order = list(range(len(rows)))
        for _ in range(6):
            rng.shuffle(order)
            assert outcome([rows[i] for i in order], [ranks[i] for i in order]) == expected


# ---------------------------------------------------------------------------
# Khóa trùng: URL trước, tiêu đề chỉ khi không có URL
# ---------------------------------------------------------------------------
def test_same_title_different_urls_are_both_kept():
    rows = [item(url="https://a.example/x", source="a"), item(url="https://b.example/y", source="b")]
    assert outcome(rows) == {"a": None, "b": None}


def test_same_url_after_normalisation_is_one_record():
    rows = [
        item(url="HTTPS://Example.com/news/cib-profit/?utm=1#top", source="a", days=2),
        item(url=URL, source="b", days=1),
    ]
    assert dedup_key(rows[0]) == dedup_key(rows[1])
    assert outcome(rows) == {"a": "duplicate", "b": None}


def test_same_url_different_titles_still_one_record():
    rows = [item(title="CIB profit rises", source="a", days=1), item(title="Egypt bank news roundup", source="b", days=3)]
    assert outcome(rows) == {"a": None, "b": "duplicate"}


def test_without_url_the_normalised_title_is_the_key():
    rows = [item(title="CIB profit rises!", url=None, source="a"), item(title="cib  profit rises", url=None, source="b")]
    for order in itertools.permutations(rows):
        assert outcome(list(order)) == {"a": None, "b": "duplicate"}


# ---------------------------------------------------------------------------
# Thiếu tiêu đề: không phải "trùng"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("title", ["", "   ", "!!! ...", None])
def test_empty_title_and_empty_url_is_missing_title_not_duplicate(title):
    rows = [item(title=title, url=None, source="a"), item(title=title, url=None, source="b")]
    assert outcome(rows) == {"a": "missing_title", "b": "missing_title"}
    assert judge(rows[0], COMI, now=NOW).reason_code == "missing_title"


def test_empty_title_with_url_is_missing_title_and_does_not_hide_titled_copy():
    rows = [item(title="", source="rong", days=0.5), item(title="CIB profit rises", source="co_tieu_de", days=3)]
    for order in itertools.permutations(rows):
        assert outcome(list(order)) == {"rong": "missing_title", "co_tieu_de": None}


def test_stale_comes_before_missing_title():
    assert judge(item(title="", days=200), COMI, now=NOW).reason_code == "stale"


# ---------------------------------------------------------------------------
# Tin vĩ mô dùng cùng chính sách
# ---------------------------------------------------------------------------
def macro(title="Egypt inflation slows", days=1.0, url=URL, source="test"):
    return item(title=title, days=days, url=url, source=source, kind="macro")


def macro_outcome(rows):
    return {row.source: verdict.reason_code for row, verdict in zip(rows, screen_macro(rows, now=NOW))}


def test_macro_stale_first_does_not_hide_fresh_and_is_order_independent():
    rows = [macro(days=150, source="cu"), macro(days=2, source="moi"), macro(days=None, source="khong_ngay")]
    for order in itertools.permutations(rows):
        assert macro_outcome(list(order)) == {"cu": "stale", "moi": None, "khong_ngay": "duplicate"}


def test_macro_missing_title_and_different_urls():
    assert judge_macro(macro(title=""), now=NOW).reason_code == "missing_title"
    rows = [macro(url="https://a.example/1", source="a"), macro(url="https://b.example/2", source="b")]
    assert macro_outcome(rows) == {"a": None, "b": None}


# ---------------------------------------------------------------------------
# Các luật nội dung không đổi; dấu hiệu phụ chỉ để hiển thị
# ---------------------------------------------------------------------------
def test_content_rules_unchanged_for_single_records():
    assert judge(item(title="Egypt prepares for coming debt repayments"), COMI, now=NOW).reason_code == "name_not_in_title"
    assert judge(item(title="Egypt banks grow", description="Commercial International Bank leads"), COMI, now=NOW).reason_code == "name_only_in_description"
    assert judge(item(title="CIB Equity Price and Quote - London Stock Exchange"), COMI, now=NOW).reason_code == "not_news_page"
    assert judge(item(title="CIB profit rises", days=91), COMI, now=NOW).reason_code == "stale"
    assert judge(item(title="CIB profit rises", days=89), COMI, now=NOW).keep


def test_pattern_flags_show_price_page_logged_as_name_missing():
    title = "CBKD Stock Price and Chart — LSIN:CBKD - TradingView"  # bản ghi thật ngày 04/11 (GDR London của CIB)
    verdict = judge(item(title=title), COMI, now=NOW)
    assert verdict.reason_code == "name_not_in_title"  # lý do đầu tiên: luật tên xét trước trang dữ liệu
    assert pattern_flags(title) == ["not_news_page"]  # dấu hiệu phụ: tiêu đề cũng khớp mẫu trang dữ liệu
    assert pattern_flags("Telecom Egypt SC held to a draw in the Premier League") == ["sports"]
    assert pattern_flags("CIB profit rises") == []
    assert pattern_flags(None) == []


def test_ranks_length_must_match():
    with pytest.raises(ValueError):
        screen([item(), item(url=None)], COMI, now=NOW, ranks=[1])


# ---------------------------------------------------------------------------
# Khóa hành vi C2 (tab 1–2 và API gốc): KHÔNG được đổi theo bản 3
# ---------------------------------------------------------------------------
def fresh(title="CIB profit rises", days=1.0, url=URL):
    published = None if days is None else (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return NewsItem(title, url, published, "test", "micro", "COMI.EGX")


def test_c2_deduplicate_keeps_first_copy_of_a_key():
    stale_first = [fresh(days=120), fresh(days=3)]
    assert deduplicate(stale_first) == [stale_first[0]]  # C2: bản đến trước được giữ, kể cả khi đã quá hạn


def test_c2_usable_news_stale_first_hides_fresh_copy():
    rows, status = usable_news([fresh(days=120), fresh(days=3)], "ok")
    assert rows == [] and status == "stale:1"  # hành vi C2 được giữ nguyên để tab 1–2 còn đối chứng
    rows, status = usable_news([fresh(days=3), fresh(days=120)], "ok")
    assert len(rows) == 1 and status == "ok:1"


def test_c2_same_title_different_urls_both_kept_and_empty_key_dropped():
    rows = [fresh(url="https://a.example/x"), fresh(url="https://b.example/y")]
    assert deduplicate(rows) == rows
    assert deduplicate([fresh(title="", url=None)]) == []  # C2: không có khóa thì bỏ hẳn, không đếm
    assert deduplicate([fresh(title="CIB profit rises!", url=None), fresh(title="cib  profit rises", url=None)])[0].title == "CIB profit rises!"
