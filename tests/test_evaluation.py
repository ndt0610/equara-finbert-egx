"""Kiểm thử phần tính chỉ số của scripts/evaluate_finbert.py (không cần model, không cần mạng)."""

from __future__ import annotations

import math

import pytest

from scripts.evaluate_finbert import (
    classification_metrics,
    confidence_analysis,
    evaluate,
    finbert_direction,
    mcnemar,
    normalize_label,
    read_labeled_csv,
    read_predictions_csv,
    wilson_interval,
    write_predictions_csv,
)
from scripts.run_upgrade_demo import hf_http_requests


def test_normalize_label_accepts_twitter_numbers_and_names():
    assert normalize_label(0) == "negative" and normalize_label("1") == "positive" and normalize_label("2.0") == "neutral"
    assert normalize_label("Bullish") == "positive" and normalize_label(" bearish ") == "negative"
    assert normalize_label("unknown") is None and normalize_label(7) is None


def test_read_labeled_csv_skips_bad_rows(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("text,label\nStock jumps,1\n,0\nShares crash,0\nOdd,9\nAGM on Friday,neutral\n", encoding="utf-8")
    rows = read_labeled_csv(path)
    assert rows == [
        {"text": "Stock jumps", "gold": "positive"},
        {"text": "Shares crash", "gold": "negative"},
        {"text": "AGM on Friday", "gold": "neutral"},
    ]


def test_wilson_interval_matches_known_value():
    low, high = wilson_interval(80, 100)
    assert low == pytest.approx(0.7112, abs=1e-3) and high == pytest.approx(0.8666, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_mcnemar_counts_and_p_value():
    a = [True] * 30 + [False] * 5 + [True] * 10
    b = [False] * 30 + [True] * 5 + [True] * 10
    result = mcnemar(a, b)
    assert result["only_first_correct"] == 30 and result["only_second_correct"] == 5
    assert result["chi2"] == pytest.approx((25 - 1) ** 2 / 35)
    assert result["p_value"] == pytest.approx(math.erfc(math.sqrt(result["chi2"] / 2)))
    assert mcnemar([True, False], [True, False])["p_value"] == 1.0


def test_classification_metrics_per_class_and_baseline():
    gold = ["positive", "positive", "negative", "neutral"]
    pred = ["positive", "negative", "negative", "neutral"]
    m = classification_metrics(gold, pred, ("positive", "negative", "neutral"))
    assert m["accuracy"] == 0.75 and m["correct"] == 3
    assert m["per_class"]["positive"]["recall"] == 0.5
    assert m["per_class"]["negative"]["precision"] == 0.5
    assert m["confusion"]["positive"]["negative"] == 1
    assert m["majority_label"] == "positive" and m["majority_baseline_accuracy"] == 0.5


def test_finbert_direction_breaks_tie_toward_positive():
    assert finbert_direction({"positive": 0.2, "negative": 0.3, "neutral": 0.5}) == "negative"
    assert finbert_direction({"positive": 0.3, "negative": 0.3, "neutral": 0.4}) == "positive"


def test_evaluate_compares_only_directional_rows_and_counts_forced_neutrals():
    def row(text, gold, pos, neg, general_pos):
        return {"text": text, "gold": gold, "finbert": {"positive": pos, "negative": neg, "neutral": 1 - pos - neg}, "general_positive": general_pos}

    rows = [
        row("Shares crash after loss", "negative", 0.05, 0.9, 0.7),  # chỉ FinBERT đúng
        row("Stock rally continues", "positive", 0.8, 0.1, 0.9),  # cả hai đúng
        row("Profit beats forecast", "positive", 0.3, 0.6, 0.8),  # chỉ model thường đúng
        row("AGM scheduled", "neutral", 0.1, 0.1, 0.6),  # model thường bị ép thành Bull
    ]
    result = evaluate(rows)
    d = result["directional_subset"]
    assert d["n"] == 3
    assert d["finbert"]["accuracy"] == pytest.approx(2 / 3) and d["general"]["accuracy"] == pytest.approx(2 / 3)
    assert d["mcnemar"]["only_first_correct"] == 1 and d["mcnemar"]["only_second_correct"] == 1
    assert result["neutral_subset"] == {"n": 1, "finbert_says_neutral": 1, "general_forced_to_bull_or_bear": 1}
    assert result["finbert_three_class"]["n"] == 4
    wins = result["examples"]["finbert_right_general_wrong"]
    assert [e["text"] for e in wins] == ["Shares crash after loss"]
    assert rows[0]["finbert_score"] == pytest.approx(-0.85)  # điểm = P+ − P− như predict.py của README


def _scored(gold, pos, neg):
    return {"gold": gold, "finbert_score": pos - neg, "finbert_direction": "positive" if pos >= neg else "negative"}


def test_confidence_analysis_buckets_and_vote_shares():
    rows = [
        _scored("neutral", 0.05, 0.0),  # độ rõ 0.05 → khoảng 0.0–0.2
        _scored("positive", 0.15, 0.05),  # 0.10, đúng chiều
        _scored("negative", 0.6, 0.0),  # 0.60, sai chiều
        _scored("positive", 0.95, 0.0),  # 0.95, đúng chiều
        _scored("negative", 0.0, 1.0),  # 1.00 → vẫn thuộc khoảng cuối
    ]
    result = confidence_analysis(rows)
    first, _, third, last = result["buckets"]
    assert first["n"] == 2 and first["neutral_share"] == 0.5 and first["direction_accuracy"] == 1.0
    assert third["n"] == 1 and third["direction_accuracy"] == 0.0
    assert last["n"] == 2 and last["direction_accuracy"] == 1.0 and last["neutral_share"] == 0.0

    equal = result["vote_share_equal"]
    assert equal == {"right_direction": pytest.approx(3 / 5), "wrong_direction": pytest.approx(1 / 5), "neutral_news": pytest.approx(1 / 5)}
    total = 0.05 + 0.10 + 0.60 + 0.95 + 1.0
    conf = result["vote_share_confidence"]
    assert conf["right_direction"] == pytest.approx((0.10 + 0.95 + 1.0) / total)
    assert conf["wrong_direction"] == pytest.approx(0.60 / total)
    assert conf["neutral_news"] == pytest.approx(0.05 / total)
    assert sum(conf.values()) == pytest.approx(1.0)


def test_predictions_csv_round_trip_gives_same_metrics(tmp_path):
    def row(text, gold, pos, neg, general_pos):
        return {"text": text, "gold": gold, "finbert": {"positive": pos, "negative": neg, "neutral": round(1 - pos - neg, 6)}, "general_positive": general_pos}

    rows = [
        row("Shares crash, after loss", "negative", 0.05, 0.9, 0.7),
        row("Stock rally continues", "positive", 0.8, 0.1, 0.9),
        row("Profit beats \"forecast\"", "positive", 0.3, 0.6, 0.8),
        row("AGM scheduled", "neutral", 0.1, 0.1, 0.6),
    ]
    first = evaluate(rows)
    path = tmp_path / "predictions.csv"
    write_predictions_csv(rows, path)
    again = read_predictions_csv(path)
    assert [r["text"] for r in again] == [r["text"] for r in rows]
    assert [r["gold"] for r in again] == [r["gold"] for r in rows]
    second = evaluate(again)
    for key in ("finbert_three_class", "directional_subset", "neutral_subset", "confidence"):
        assert second[key] == first[key]


def test_hf_http_request_count_for_batched_and_cached_flows():
    trace = [
        {"headlines": 6, "model_calls": 6},
        {"headlines": 16, "model_calls": 0},
        {"headlines": 10, "model_calls": 2},
    ]
    counts = hf_http_requests(trace, batch_size=15)
    assert counts["one_per_headline_direct"] == 32 and counts["one_per_headline_cached"] == 8
    assert counts["batched_direct"] == 1 + 2 + 1
    assert counts["batched_cached"] == 1 + 0 + 1


def test_from_run_rebuilds_tables_and_charts_without_a_model(tmp_path, monkeypatch):
    import json
    import sys

    from scripts import evaluate_finbert

    run = tmp_path / "run"
    run.mkdir()
    rows = [
        {"text": "Shares crash", "gold": "negative", "finbert": {"positive": 0.05, "negative": 0.9, "neutral": 0.05}, "general_positive": 0.7},
        {"text": "Stock rally", "gold": "positive", "finbert": {"positive": 0.8, "negative": 0.1, "neutral": 0.1}, "general_positive": 0.9},
        {"text": "AGM scheduled", "gold": "neutral", "finbert": {"positive": 0.1, "negative": 0.1, "neutral": 0.8}, "general_positive": 0.6},
    ]
    evaluate(rows)
    write_predictions_csv(rows, run / "predictions.csv")
    meta = {
        "run_at_utc": "2026-11-01T00:00:00+00:00", "python": "3.12", "dataset": "local CSV", "dataset_file": "x.csv",
        "dataset_revision": None, "finbert_model": "ProsusAI/finbert", "finbert_revision": "0bc2ac10", "finbert_device": "cpu",
        "general_model": "sst2", "general_revision": "abc", "seconds": 1.0,
    }
    (run / "evaluation_results.json").write_text(json.dumps({"meta": meta}), encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["evaluate_finbert", "--from-run", str(run), "--out", str(out)])
    evaluate_finbert.main()

    for name in ("chart4_finbert_vs_general.png", "chart5_confidence_check.png", "BANG_DANH_GIA.md", "evaluation_results.json", "predictions.csv"):
        assert (out / name).stat().st_size > 0
    saved = json.loads((out / "evaluation_results.json").read_text(encoding="utf-8"))
    assert saved["meta"]["finbert_revision"] == "0bc2ac10" and "recomputed_at_utc" in saved["meta"]
    assert saved["evaluation"]["directional_subset"]["n"] == 2
