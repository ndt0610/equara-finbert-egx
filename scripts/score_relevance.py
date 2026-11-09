"""Chấm số đo từ hai phiếu gán nhãn (scripts/make_label_sheet.py). Chỉ báo số đo, KHÔNG có ngưỡng đạt/không đạt.

--kind relevance (mặc định):
  - Tỷ lệ hai người đồng ý và Cohen κ.
  - Trên các tin hai người cùng nhãn: precision và recall của bộ lọc cũ (alias trong tiêu đề hoặc mô tả)
    và của luật lọc ghi trong lượt thu (cột relevance_rules của file khóa), kèm khoảng Wilson 95%.
  - Với mỗi lý do loại: bao nhiêu tin bị loại mà người gán cho là đúng doanh nghiệp (để sửa luật).
--kind sentiment:
  - Tỷ lệ đồng ý và Cohen κ trên 3 nhãn; ghi file `text,label` gồm các tin hai người cùng nhãn, dùng được
    với `python -m scripts.evaluate_finbert --data-csv <file>` để đo độ chính xác và độ tin cậy của FinBERT.

Chạy:
    python -m scripts.score_relevance labels/relevance/nhan_nguoi_1.csv labels/relevance/nhan_nguoi_2.csv \
        --key labels/relevance/khoa_dap_an_KHONG_GUI_NGUOI_GAN.csv --out labels/relevance/KET_QUA.md
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from scripts.evaluate_finbert import wilson_interval

YES = {"1", "co", "có", "yes", "y", "true"}
NO = {"0", "khong", "không", "no", "n", "false"}
SENTIMENT = {"positive": "positive", "pos": "positive", "negative": "negative", "neg": "negative", "neutral": "neutral", "neu": "neutral"}


def parse_label(value: str, kind: str) -> Any:
    text = (value or "").strip().casefold()
    if kind == "relevance":
        return 1 if text in YES else 0 if text in NO else None
    return SENTIMENT.get(text)


def read_labels(path: str | Path, kind: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return {row["item_id"]: parse_label(row.get("nhan", ""), kind) for row in csv.DictReader(handle)}


def cohen_kappa(a: Sequence[Any], b: Sequence[Any]) -> float | None:
    """κ = (p_o − p_e) / (1 − p_e). None khi không xác định (ít hơn 1 cặp, hoặc p_e = 1)."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[c] * count_b[c] for c in set(a) | set(b)) / (n * n)
    if expected >= 1:
        return None
    return (observed - expected) / (1 - expected)


def _rate(hit: int, total: int) -> dict[str, Any]:
    if total == 0:
        return {"value": None, "hit": hit, "total": total, "wilson95": None}
    return {"value": hit / total, "hit": hit, "total": total, "wilson95": wilson_interval(hit, total)}


def filter_metrics(gold: dict[str, int], predicted: dict[str, bool]) -> dict[str, Any]:
    ids = [i for i in gold if i in predicted]
    tp = sum(1 for i in ids if predicted[i] and gold[i] == 1)
    fp = sum(1 for i in ids if predicted[i] and gold[i] == 0)
    fn = sum(1 for i in ids if not predicted[i] and gold[i] == 1)
    tn = sum(1 for i in ids if not predicted[i] and gold[i] == 0)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": _rate(tp, tp + fp), "recall": _rate(tp, tp + fn)}


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1"}


def score(rater_1: dict[str, Any], rater_2: dict[str, Any], key_rows: list[dict[str, str]], kind: str) -> dict[str, Any]:
    both = [i for i in rater_1 if i in rater_2 and rater_1[i] is not None and rater_2[i] is not None]
    agree = [i for i in both if rater_1[i] == rater_2[i]]
    result: dict[str, Any] = {
        "kind": kind,
        "items": len(set(rater_1) | set(rater_2)),
        "labelled_by_both": len(both),
        "agreement": _rate(len(agree), len(both)),
        "cohen_kappa": cohen_kappa([rater_1[i] for i in both], [rater_2[i] for i in both]),
        "disagreements": [i for i in both if rater_1[i] != rater_2[i]],
        "gold": {i: rater_1[i] for i in agree},
    }
    if kind == "relevance":
        key = {row["item_id"]: row for row in key_rows}
        gold = {i: v for i, v in result["gold"].items() if i in key}
        result["rules_versions"] = sorted({key[i].get("relevance_rules") or "không rõ" for i in gold})
        result["gold_relevant"] = sum(gold.values())
        result["old_filter"] = filter_metrics(gold, {i: _bool(key[i]["old_filter_keep"]) for i in gold})
        result["new_rules"] = filter_metrics(gold, {i: _bool(key[i]["new_keep"]) for i in gold})
        wrongly_rejected = Counter(key[i]["new_reason_code"] for i in gold if gold[i] == 1 and not _bool(key[i]["new_keep"]))
        rejected_total = Counter(key[i]["new_reason_code"] for i in gold if not _bool(key[i]["new_keep"]))
        result["by_reason"] = {code: {"rejected": rejected_total[code], "of_which_people_say_relevant": wrongly_rejected[code]} for code in rejected_total}
    return result


def _fmt_rate(rate: dict[str, Any]) -> str:
    if rate["value"] is None:
        return f"không tính được (0 tin)"
    low, high = rate["wilson95"]
    return f"{rate['value']:.1%} ({rate['hit']}/{rate['total']}; Wilson 95%: {low:.1%}–{high:.1%})"


def render(result: dict[str, Any]) -> str:
    kappa = result["cohen_kappa"]
    lines = [
        f"# Kết quả gán nhãn ({result['kind']})",
        "",
        "Đây là số đo. Không có ngưỡng đạt hay không đạt; nhóm đọc số rồi quyết định.",
        "",
        f"- Số tin: {result['items']} · cả hai người cùng gán: {result['labelled_by_both']}",
        f"- Hai người đồng ý: {_fmt_rate(result['agreement'])}",
        f"- Cohen κ: {'không tính được' if kappa is None else f'{kappa:.3f}'}",
        f"- Số tin hai người khác nhau: {len(result['disagreements'])} (item_id: {', '.join(result['disagreements'][:30]) or 'không có'})",
    ]
    if result["kind"] == "relevance":
        lines += [
            "",
            f"Trên {len(result['gold'])} tin hai người cùng nhãn ({result['gold_relevant']} tin đúng doanh nghiệp):",
            "",
            "| Bộ lọc | Precision | Recall | TP | FP | FN | TN |",
            "|---|---|---|---|---|---|---|",
        ]
        versions = result.get("rules_versions") or ["không rõ"]
        if len(versions) > 1:
            lines += ["", f"Cảnh báo: phiếu gộp tin thu bằng nhiều phiên bản luật ({', '.join(versions)}). Nên chấm riêng từng phiên bản."]
        for name, key in (("Bản tái dựng (alias trong tiêu đề hoặc mô tả)", "old_filter"), (f"Luật mới ({', '.join(versions)})", "new_rules")):
            m = result[key]
            lines.append(f"| {name} | {_fmt_rate(m['precision'])} | {_fmt_rate(m['recall'])} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} |")
        lines += ["", "| Lý do loại (luật mới) | Số tin bị loại | Trong đó người gán nói là đúng doanh nghiệp |", "|---|---|---|"]
        for code, row in sorted(result["by_reason"].items()):
            lines.append(f"| {code} | {row['rejected']} | {row['of_which_people_say_relevant']} |")
    return "\n".join(lines) + "\n"


def write_sentiment_gold(result: dict[str, Any], key_rows: list[dict[str, str]], path: Path) -> int:
    key = {row["item_id"]: row for row in key_rows}
    rows = [(key[i]["title"], label) for i, label in result["gold"].items() if i in key]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["text", "label"])
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rater_1")
    parser.add_argument("rater_2")
    parser.add_argument("--key", required=True, help="File khóa đáp án do make_label_sheet tạo.")
    parser.add_argument("--kind", choices=("relevance", "sentiment"), default="relevance")
    parser.add_argument("--out", required=True, help="File báo cáo .md")
    parser.add_argument("--gold-out", help="(sentiment) File text,label cho scripts.evaluate_finbert --data-csv")
    args = parser.parse_args()
    with Path(args.key).open(encoding="utf-8", newline="") as handle:
        key_rows = list(csv.DictReader(handle))
    result = score(read_labels(args.rater_1, args.kind), read_labels(args.rater_2, args.kind), key_rows, args.kind)
    Path(args.out).write_text(render(result), encoding="utf-8")
    print(f"Đã ghi {args.out}")
    if args.kind == "sentiment" and args.gold_out:
        print(f"Đã ghi {write_sentiment_gold(result, key_rows, Path(args.gold_out))} tin vào {args.gold_out}")


if __name__ == "__main__":
    main()
