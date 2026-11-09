"""Công cụ đo cho 3 việc tiếp theo: thu tin hằng ngày, phiếu gán nhãn mù, chấm số đo, tóm tắt độ phủ.
Toàn bộ chạy offline với nguồn tin giả lập."""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.providers.news import NewsItem
from scripts.capture_candidates import build_symbol_rows, capture
from scripts.make_label_sheet import load_rows, select_items, write_sheets
from scripts.score_relevance import cohen_kappa, filter_metrics, read_labels, render, score
from scripts.summarize_captures import summarize
from backend.upgrades.coverage import CoverageConfig
from tests.test_coverage import fake_probs, handler_factory, live_services

NOW = datetime.now(timezone.utc)


def item(title, description=None, hours=1, source="x"):
    return NewsItem(title, f"https://n.example/{abs(hash(title))}", (NOW - timedelta(hours=hours)).isoformat(), source, "micro", "COMI.EGX", description)


def test_rows_mark_what_the_web_would_use():
    lists = {"eodhd": [item("Egypt markets wrap", "CIB shares")], "google1": [item("CIB profit rises"), item("Egypt coming budget")], "google2": None}
    rows = build_symbol_rows("COMI.EGX", lists, now=NOW)
    by_title = {r["title"]: r for r in rows}
    assert by_title["Egypt markets wrap"]["new_reason_code"] == "name_only_in_description"
    assert by_title["CIB profit rises"]["web_source_used"] and by_title["CIB profit rises"]["web_scored"]  # EODHD không có tin phù hợp → web dùng Google
    assert by_title["Egypt coming budget"]["old_filter_keep"] and not by_title["Egypt coming budget"]["new_keep"]
    lists["eodhd"] = [item("CIB raises capital")]
    # Tắt bậc 2 (như bản 1): EODHD đã có tin phù hợp thì web không gọi Google.
    rows = build_symbol_rows("COMI.EGX", lists, now=NOW, config=CoverageConfig(tier2_below=None))
    assert not next(r for r in rows if r["title"] == "CIB profit rises")["web_source_used"]
    # Mặc định: EODHD mới có 1 tin phù hợp (< 10) nên web gọi thêm Google bậc 1, rồi bậc 2.
    rows = build_symbol_rows("COMI.EGX", lists, now=NOW)
    assert next(r for r in rows if r["title"] == "CIB profit rises")["web_source_used"]


def run_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("INFERENCE_PROVIDER", "hf-inference")
    monkeypatch.setenv("HF_INFERENCE_URL", "http://selfhosted.local/models/ProsusAI/finbert")
    monkeypatch.setenv("EODHD_API_TOKEN", "secret_token_khong_ghi")
    from backend.providers.hf_inference import HuggingFaceFinBERT

    async def classify_many(self, texts):
        return [fake_probs(t) for t in texts]

    monkeypatch.setattr(HuggingFaceFinBERT, "classify_many", classify_many)
    return asyncio.run(
        capture(["COMI.EGX", "ETEL.EGX"], tier2=True, score=True, out_root=tmp_path / "captures", transport=httpx.MockTransport(handler_factory([])))
    )


def test_capture_writes_every_candidate_with_probabilities_and_no_secret(tmp_path, monkeypatch):
    out = run_capture(tmp_path, monkeypatch)
    raw = (out / "capture.json").read_text(encoding="utf-8")
    assert "secret_token_khong_ghi" not in raw and "secret_token_khong_ghi" not in (out / "candidates.csv").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["meta"]["eodhd_configured"] is True and data["meta"]["model"]["scored"] is True
    micro = [r for r in data["rows"] if r["kind"] == "micro"]
    assert {r["query_tier"] for r in micro} == {1, 2}
    assert any(r["new_reason_code"] == "sports" for r in micro)  # tin bóng đá ETEL được giữ lại để đo
    assert all(r["probabilities"] for r in data["rows"])
    macro = [r for r in data["rows"] if r["kind"] == "macro"]
    assert {r["list"] for r in macro} == {"macro", "macro_economic"}  # thu cả truy vấn tin kinh tế
    assert all(r["new_reason_code"] == "not_economic" for r in macro if r["list"] == "macro" and r["web_source_used"])


def test_capture_marks_exactly_what_the_web_scores(tmp_path, monkeypatch):
    """Cùng nguồn tin giả lập: tin capture đánh dấu "web chấm" phải trùng đúng tin tab 3 chấm, cả tin riêng và vĩ mô."""
    out = run_capture(tmp_path, monkeypatch)
    rows = json.loads((out / "capture.json").read_text(encoding="utf-8"))["rows"]
    _, coverage, _, _ = live_services(monkeypatch, eodhd=True)
    body = asyncio.run(coverage.analyze([("COMI.EGX", 60), ("ETEL.EGX", 40)]))
    for h in body["holdings"]:
        marked = sorted(r["title"] for r in rows if r["kind"] == "micro" and r["symbol"] == h["symbol"] and r["web_scored"])
        assert marked == sorted(row["title"] for row in h["headlines"]), h["symbol"]
    marked_macro = sorted(r["title"] for r in rows if r["kind"] == "macro" and r["web_scored"])
    assert marked_macro == sorted(row["title"] for row in body["macro"]["headlines"]) == ["Egypt economy outlook"]


def test_label_sheets_are_blind_and_scores_are_measured(tmp_path, monkeypatch):
    out = run_capture(tmp_path, monkeypatch)
    items = select_items(load_rows([out]), "relevance")
    files = write_sheets(items, tmp_path / "labels", "relevance")
    with files["rater_1"].open(encoding="utf-8-sig") as handle:
        sheet = list(csv.DictReader(handle))
    assert set(sheet[0]) == {"item_id", "cong_ty", "tieu_de", "link", "nhan", "ghi_chu"}  # không lộ kết quả của máy
    assert len(sheet) == len(items) and len({r["item_id"] for r in sheet}) == len(sheet)
    with files["key"].open(encoding="utf-8") as handle:
        key = list(csv.DictReader(handle))
    # Hai người gán: người 1 theo đúng luật mới, người 2 khác ở đúng một tin.
    truth = {r["item_id"]: ("1" if r["new_keep"] == "True" else "0") for r in key}
    flipped = next(iter(truth))
    for name, labels in (("rater_1", truth), ("rater_2", {**truth, flipped: "0" if truth[flipped] == "1" else "1"})):
        with files[name].open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["item_id", "cong_ty", "tieu_de", "link", "nhan", "ghi_chu"])
            for r in sheet:
                writer.writerow([r["item_id"], r["cong_ty"], r["tieu_de"], r["link"], labels[r["item_id"]], ""])
    result = score(read_labels(files["rater_1"], "relevance"), read_labels(files["rater_2"], "relevance"), key, "relevance")
    assert result["disagreements"] == [flipped] and len(result["gold"]) == len(sheet) - 1
    assert result["new_rules"]["precision"]["value"] == 1.0 and result["new_rules"]["recall"]["value"] == 1.0
    assert result["old_filter"]["precision"]["value"] < 1.0  # bộ lọc cũ giữ cả tin "coming", tin thể thao, trang báo giá
    report = render(result)
    assert "Không có ngưỡng đạt hay không đạt" in report and "Wilson 95%" in report
    assert "Luật mới (relevance-v3)" in report and result["rules_versions"] == ["relevance-v3"]  # phiên bản lấy từ lượt thu


def test_cohen_kappa_textbook_example_and_metrics():
    a = [1] * 20 + [1] * 5 + [0] * 10 + [0] * 15
    b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)  # p_o = 0,7; p_e = 0,5
    assert cohen_kappa([1, 1], [1, 1]) is None
    m = filter_metrics({"a": 1, "b": 0, "c": 1, "d": 0}, {"a": True, "b": True, "c": False, "d": False})
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1) and m["precision"]["value"] == 0.5


def test_summary_counts_and_coverage(tmp_path, monkeypatch):
    out = run_capture(tmp_path, monkeypatch)
    result = summarize([out], {"COMI.EGX": 50, "ETEL.EGX": 30, "FWRY.EGX": 20})
    row = result["captures"][0]["per_symbol"]
    assert row["COMI.EGX"]["web_scored"] == 15 and row["ETEL.EGX"]["web_scored"] == 1
    assert result["coverage"]["min"] == pytest.approx(0.8) and result["coverage"]["captures_above_half"] == 1
