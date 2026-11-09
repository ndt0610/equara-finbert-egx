"""Đo độ chính xác của FinBERT trên tin tài chính có nhãn, so với một model sentiment "thông thường".

Vì sao có script này (đối chiếu yêu cầu):
- Bài báo mục 1 khẳng định: model sentiment thông thường (học từ review phim) đọc sai tin tài chính,
  FinBERT thì đúng hơn. Bài báo không đưa con số nào. Script này đo con số đó.
- README repo ProsusAI/finBERT có phần Datasets (dữ liệu có nhãn) và `predict.py` (xuất file gồm câu,
  3 xác suất softmax, nhãn dự đoán và điểm = P(positive) − P(negative)). File `predictions.csv` ở đây
  có đúng các cột đó, cộng nhãn đúng và dự đoán của model so sánh.

Dữ liệu mặc định: tập validation của `zeroshot/twitter-financial-news-sentiment` (tin tài chính tiếng Anh,
nhãn Bearish / Bullish / Neutral). Không chấm trên Financial PhraseBank như README vì FinBERT đã được huấn
luyện trên chính bộ đó: chấm lại sẽ cho điểm cao giả. Có thể đưa CSV khác vào bằng `--data-csv`.

Model so sánh mặc định: `distilbert/distilbert-base-uncased-finetuned-sst-2-english`, học từ SST-2
(câu review phim), đúng ví dụ "trained on movie reviews" của bài báo. Model này chỉ có 2 nhãn nên phép so
sánh công bằng là trên các tin có chiều rõ (Bullish / Bearish); FinBERT được đánh giá thêm trên đủ 3 nhãn.

Chạy (cần mạng tới Hugging Face, ví dụ trên Colab):
    python -m scripts.evaluate_finbert
Kết quả: artifacts/evaluation/{chart4_finbert_vs_general.png, chart5_confidence_check.png, BANG_DANH_GIA.md, evaluation_results.json, predictions.csv}
Tính lại từ một lần chạy trước (không cần model): python -m scripts.evaluate_finbert --from-run <thư mục kết quả>
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID

ROOT = Path(__file__).resolve().parents[1]
TWITTER_REPO = "zeroshot/twitter-financial-news-sentiment"
TWITTER_NUMERIC_LABELS = {0: "negative", 1: "positive", 2: "neutral"}  # 0 Bearish, 1 Bullish, 2 Neutral
GENERAL_MODEL = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
LABELS = ("positive", "negative", "neutral")
MARKET_NAME = {"positive": "Bullish", "negative": "Bearish", "neutral": "Neutral"}
LABEL_ALIASES = {
    "positive": "positive",
    "pos": "positive",
    "bullish": "positive",
    "negative": "negative",
    "neg": "negative",
    "bearish": "negative",
    "neutral": "neutral",
    "neu": "neutral",
}
# Từ mà bài báo mục 1 nêu là "có nghĩa riêng trong tài chính", cộng vài từ cùng loại; dùng để chọn ví dụ.
FINANCE_WORDS = ("loss", "crash", "rally", "cut", "beat", "miss", "plunge", "surge", "short", "bear", "bull", "debt", "default", "downgrade", "upgrade")


# ---------------------------------------------------------------------------
# Đọc dữ liệu
# ---------------------------------------------------------------------------
def normalize_label(value: Any, numeric_map: dict[int, str] = TWITTER_NUMERIC_LABELS) -> str | None:
    text = str(value).strip().lower()
    if re.fullmatch(r"-?\d+(\.0+)?", text):
        return numeric_map.get(int(float(text)))
    return LABEL_ALIASES.get(text)


def read_labeled_csv(path: str | Path, numeric_map: dict[int, str] = TWITTER_NUMERIC_LABELS) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = {name.lower().strip(): name for name in reader.fieldnames or []}
        text_col = next((columns[c] for c in ("text", "sentence", "headline", "title") if c in columns), None)
        label_col = next((columns[c] for c in ("label", "sentiment", "gold") if c in columns), None)
        if text_col is None or label_col is None:
            raise SystemExit(f"CSV cần cột text và label; đang có: {reader.fieldnames}")
        rows = []
        for raw in reader:
            text = (raw.get(text_col) or "").strip()
            gold = normalize_label(raw.get(label_col), numeric_map)
            if text and gold:
                rows.append({"text": text, "gold": gold})
    if not rows:
        raise SystemExit(f"Không đọc được dòng nào có nhãn hợp lệ trong {path}")
    return rows


def download_twitter_split(split_hint: str = "valid") -> tuple[Path, str | None, str]:
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    sha = None
    try:
        sha = api.dataset_info(TWITTER_REPO).sha
    except Exception:  # thông tin phiên bản chỉ để ghi lại, không bắt buộc
        pass
    files = api.list_repo_files(TWITTER_REPO, repo_type="dataset", revision=sha)
    candidates = [f for f in files if f.lower().endswith(".csv") and split_hint in f.lower()]
    if not candidates:
        raise SystemExit(f"Không thấy file CSV '{split_hint}' trong {TWITTER_REPO}; các file: {files}")
    filename = sorted(candidates)[0]
    path = hf_hub_download(TWITTER_REPO, filename, repo_type="dataset", revision=sha)
    return Path(path), sha, filename


# ---------------------------------------------------------------------------
# Model so sánh (2 nhãn)
# ---------------------------------------------------------------------------
class GeneralSentimentModel:
    """Model sentiment 2 nhãn (POSITIVE/NEGATIVE), trả P(positive) cho từng câu."""

    def __init__(self, model_id: str = GENERAL_MODEL, revision: str | None = None, device_preference: str = "auto") -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.model_id = model_id
        self.device = torch.device("cuda" if device_preference == "auto" and torch.cuda.is_available() else "cpu")
        # Resolve once before loading so both files and the reported SHA refer to the same snapshot.
        if not Path(model_id).exists():
            from huggingface_hub import hf_hub_download
            config_path = Path(hf_hub_download(model_id, "config.json", revision=revision))
            self.revision = config_path.parent.name
        else:
            self.revision = None
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, revision=self.revision)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_id, revision=self.revision).to(self.device).eval()
        id2label = {int(k): str(v).lower() for k, v in self.model.config.id2label.items()}
        pos = [i for i, name in id2label.items() if name.startswith("pos")]
        neg = [i for i, name in id2label.items() if name.startswith("neg")]
        if len(pos) != 1 or len(neg) != 1 or len(id2label) != 2:
            raise SystemExit(f"{model_id} phải là model 2 nhãn POSITIVE/NEGATIVE; đang có {id2label}")
        self.pos_index = pos[0]

    def positive_probability(self, texts: Sequence[str], batch_size: int = 32) -> list[float]:
        out: list[float] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            encoded = self.tokenizer(batch, padding=True, truncation=True, max_length=128, return_tensors="pt")
            encoded = {k: v.to(self.device) for k, v in encoded.items()}
            with self.torch.inference_mode():
                probs = self.torch.softmax(self.model(**encoded).logits, dim=-1)[:, self.pos_index]
            out.extend(float(p) for p in probs.cpu().tolist())
        return out


# ---------------------------------------------------------------------------
# Chỉ số
# ---------------------------------------------------------------------------
def finbert_label(probabilities: dict[str, float]) -> str:
    return max(LABELS, key=lambda label: probabilities[label])


def finbert_direction(probabilities: dict[str, float]) -> str:
    """Khi buộc chọn chiều (như model 2 nhãn): Bull nếu P(positive) ≥ P(negative)."""
    return "positive" if probabilities["positive"] >= probabilities["negative"] else "negative"


def confusion(gold: Sequence[str], pred: Sequence[str], labels: Sequence[str]) -> dict[str, dict[str, int]]:
    table = {g: {p: 0 for p in labels} for g in labels}
    for g, p in zip(gold, pred, strict=True):
        table[g][p] += 1
    return table


def wilson_interval(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = correct / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def classification_metrics(gold: Sequence[str], pred: Sequence[str], labels: Sequence[str]) -> dict[str, Any]:
    total = len(gold)
    correct = sum(g == p for g, p in zip(gold, pred, strict=True))
    per_class = {}
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, pred))
        support = sum(g == label for g in gold)
        predicted = sum(p == label for p in pred)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
    majority = max(labels, key=lambda label: per_class[label]["support"])
    return {
        "n": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "accuracy_ci95": wilson_interval(correct, total),
        "macro_f1": sum(c["f1"] for c in per_class.values()) / len(labels),
        "per_class": per_class,
        "confusion": confusion(gold, pred, labels),
        "majority_label": majority,
        "majority_baseline_accuracy": per_class[majority]["support"] / total if total else 0.0,
    }


def mcnemar(a_correct: Sequence[bool], b_correct: Sequence[bool]) -> dict[str, Any]:
    """Kiểm định McNemar (có hiệu chỉnh liên tục) cho 2 model chấm cùng một bộ câu."""
    only_a = sum(a and not b for a, b in zip(a_correct, b_correct, strict=True))
    only_b = sum(b and not a for a, b in zip(a_correct, b_correct, strict=True))
    discordant = only_a + only_b
    if discordant == 0:
        return {"only_first_correct": 0, "only_second_correct": 0, "chi2": 0.0, "p_value": 1.0}
    chi2 = (abs(only_a - only_b) - 1) ** 2 / discordant
    return {"only_first_correct": only_a, "only_second_correct": only_b, "chi2": chi2, "p_value": math.erfc(math.sqrt(chi2 / 2))}


def pick_examples(rows: list[dict[str, Any]], want: Callable[[dict[str, Any]], bool], limit: int) -> list[dict[str, Any]]:
    chosen = [r for r in rows if want(r)]
    has_word = [r for r in chosen if any(re.search(rf"\b{w}", r["text"].lower()) for w in FINANCE_WORDS)]
    picked = {id(r) for r in has_word}
    rest = [r for r in chosen if id(r) not in picked]
    return (has_word + rest)[:limit]


CONFIDENCE_BUCKETS = ((0.0, 0.2), (0.2, 0.5), (0.5, 0.8), (0.8, 1.0))


def confidence_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Kiểm chứng Module 1 bằng dữ liệu: độ rõ |P+ − P−| có báo trước FinBERT đúng hay sai không?

    - Theo từng khoảng độ rõ: tỷ lệ đoán đúng chiều trên tin có chiều rõ, và tỷ lệ tin thực chất trung tính.
    - "Phần phiếu": cách bài báo chia trung bình cho N (mỗi tin 1 phiếu); Module 1 chia cho Σ|P+ − P−|.
      Tính xem bao nhiêu phần phiếu rơi vào tin đúng chiều, tin sai chiều, và tin thực chất trung tính.
    """
    buckets = []
    for index, (low, high) in enumerate(CONFIDENCE_BUCKETS):
        last = index == len(CONFIDENCE_BUCKETS) - 1
        inside = [r for r in rows if low <= abs(r["finbert_score"]) < high or (last and abs(r["finbert_score"]) >= high)]
        directional = [r for r in inside if r["gold"] != "neutral"]
        right = sum(r["finbert_direction"] == r["gold"] for r in directional)
        buckets.append({
            "low": low,
            "high": high,
            "n": len(inside),
            "directional_n": len(directional),
            "direction_accuracy": right / len(directional) if directional else None,
            "neutral_share": (len(inside) - len(directional)) / len(inside) if inside else None,
        })

    def vote_shares(weight: Callable[[dict[str, Any]], float]) -> dict[str, float]:
        total = sum(weight(r) for r in rows) or 1.0
        right = sum(weight(r) for r in rows if r["gold"] != "neutral" and r["finbert_direction"] == r["gold"])
        wrong = sum(weight(r) for r in rows if r["gold"] != "neutral" and r["finbert_direction"] != r["gold"])
        neutral = sum(weight(r) for r in rows if r["gold"] == "neutral")
        return {"right_direction": right / total, "wrong_direction": wrong / total, "neutral_news": neutral / total}

    return {
        "buckets": buckets,
        "vote_share_equal": vote_shares(lambda r: 1.0),
        "vote_share_confidence": vote_shares(lambda r: abs(r["finbert_score"])),
    }


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: [{text, gold, finbert{positive,negative,neutral}, general_positive}]"""
    for r in rows:
        r["finbert_label"] = finbert_label(r["finbert"])
        r["finbert_direction"] = finbert_direction(r["finbert"])
        r["general_label"] = "positive" if r["general_positive"] >= 0.5 else "negative"
        r["finbert_score"] = r["finbert"]["positive"] - r["finbert"]["negative"]

    three = classification_metrics([r["gold"] for r in rows], [r["finbert_label"] for r in rows], LABELS)
    directional = [r for r in rows if r["gold"] != "neutral"]
    two = ("positive", "negative")
    finbert_binary = classification_metrics([r["gold"] for r in directional], [r["finbert_direction"] for r in directional], two)
    general_binary = classification_metrics([r["gold"] for r in directional], [r["general_label"] for r in directional], two)
    test = mcnemar(
        [r["finbert_direction"] == r["gold"] for r in directional],
        [r["general_label"] == r["gold"] for r in directional],
    )
    neutral_rows = [r for r in rows if r["gold"] == "neutral"]
    finbert_wins = pick_examples(directional, lambda r: r["finbert_direction"] == r["gold"] != r["general_label"], 6)
    general_wins = pick_examples(directional, lambda r: r["general_label"] == r["gold"] != r["finbert_direction"], 3)
    return {
        "finbert_three_class": three,
        "directional_subset": {
            "n": len(directional),
            "finbert": finbert_binary,
            "general": general_binary,
            "mcnemar": test,
        },
        "neutral_subset": {
            "n": len(neutral_rows),
            "finbert_says_neutral": sum(r["finbert_label"] == "neutral" for r in neutral_rows),
            "general_forced_to_bull_or_bear": len(neutral_rows),
        },
        "confidence": confidence_analysis(rows),
        "examples": {
            "finbert_right_general_wrong": [_example(r) for r in finbert_wins],
            "general_right_finbert_wrong": [_example(r) for r in general_wins],
        },
    }


def _example(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": r["text"],
        "gold": MARKET_NAME[r["gold"]],
        "finbert": {k: round(v, 4) for k, v in r["finbert"].items()},
        "finbert_direction": MARKET_NAME[r["finbert_direction"]],
        "general_positive": round(r["general_positive"], 4),
        "general_label": MARKET_NAME[r["general_label"]],
    }


# ---------------------------------------------------------------------------
# Xuất kết quả
# ---------------------------------------------------------------------------
def read_predictions_csv(path: str | Path) -> list[dict[str, Any]]:
    """Đọc lại predictions.csv của một lần chạy để tính lại chỉ số/biểu đồ mà không cần chạy model."""
    names = {v: k for k, v in MARKET_NAME.items()}
    rows = []
    with open(path, encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            rows.append({
                "text": raw["sentence"],
                "gold": names[raw["gold"]],
                "finbert": {label: float(raw[f"finbert_{label}"]) for label in LABELS},
                "general_positive": float(raw["general_p_positive"]),
            })
    return rows


def write_predictions_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sentence", "gold", "finbert_positive", "finbert_negative", "finbert_neutral", "finbert_prediction", "sentiment_score", "general_p_positive", "general_prediction"])
        for r in rows:
            p = r["finbert"]
            writer.writerow([
                r["text"], MARKET_NAME[r["gold"]], f"{p['positive']:.6f}", f"{p['negative']:.6f}", f"{p['neutral']:.6f}",
                r["finbert_label"], f"{r['finbert_score']:.6f}", f"{r['general_positive']:.6f}", r["general_label"],
            ])


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_markdown(result: dict[str, Any]) -> str:
    d = result["evaluation"]["directional_subset"]
    f, g, t = d["finbert"], d["general"], d["mcnemar"]
    three = result["evaluation"]["finbert_three_class"]
    neu = result["evaluation"]["neutral_subset"]
    meta = result["meta"]
    lines = [
        "# Bảng đánh giá: FinBERT so với model review phim trên tin tài chính có nhãn",
        "",
        f"- Dữ liệu: `{meta['dataset']}` file `{meta['dataset_file']}` (phiên bản `{meta['dataset_revision']}`), {three['n']} tin.",
        f"- FinBERT: `{meta['finbert_model']}` revision `{meta['finbert_revision']}`. Model so sánh: `{meta['general_model']}` revision `{meta['general_revision']}`.",
        f"- Chạy lúc {meta['run_at_utc']} · Python {meta['python']} · {meta['seconds']:.0f} giây.",
        "",
        f"## 1. Tin có chiều rõ (Bullish / Bearish): {d['n']} tin",
        "",
        "| Chỉ số | FinBERT | Model review phim (SST-2) |",
        "|---|---|---|",
        f"| Độ chính xác | **{_pct(f['accuracy'])}** (95%: {_pct(f['accuracy_ci95'][0])}–{_pct(f['accuracy_ci95'][1])}) | {_pct(g['accuracy'])} (95%: {_pct(g['accuracy_ci95'][0])}–{_pct(g['accuracy_ci95'][1])}) |",
        f"| Bắt đúng tin Bullish (recall) | {_pct(f['per_class']['positive']['recall'])} | {_pct(g['per_class']['positive']['recall'])} |",
        f"| Bắt đúng tin Bearish (recall) | {_pct(f['per_class']['negative']['recall'])} | {_pct(g['per_class']['negative']['recall'])} |",
        f"| Đoán bừa theo nhãn phổ biến nhất ({MARKET_NAME[f['majority_label']]}) | {_pct(f['majority_baseline_accuracy'])} | {_pct(g['majority_baseline_accuracy'])} |",
        "",
        f"Kiểm định McNemar trên cùng {d['n']} tin: {t['only_first_correct']} tin chỉ FinBERT đúng, {t['only_second_correct']} tin chỉ model review phim đúng; χ² = {t['chi2']:.1f}, p = {t['p_value']:.2g}.",
        "",
        f"## 2. FinBERT trên đủ 3 nhãn: {three['n']} tin",
        "",
        f"Độ chính xác {_pct(three['accuracy'])} (95%: {_pct(three['accuracy_ci95'][0])}–{_pct(three['accuracy_ci95'][1])}), macro-F1 {three['macro_f1']:.3f}; đoán bừa theo nhãn phổ biến nhất ({MARKET_NAME[three['majority_label']]}) được {_pct(three['majority_baseline_accuracy'])}.",
        "",
        "| Nhãn đúng \\ FinBERT đoán | Bullish | Bearish | Neutral | Recall |",
        "|---|---|---|---|---|",
    ]
    for label in LABELS:
        row = three["confusion"][label]
        lines.append(f"| {MARKET_NAME[label]} | {row['positive']} | {row['negative']} | {row['neutral']} | {_pct(three['per_class'][label]['recall'])} |")
    lines += [
        "",
        f"Tin trung tính: {neu['n']} tin. FinBERT nhận ra {neu['finbert_says_neutral']} tin là Neutral; model review phim không có nhãn Neutral nên cả {neu['general_forced_to_bull_or_bear']} tin bị ép thành Bullish hoặc Bearish.",
        "",
        "## 3. Ví dụ FinBERT đúng, model review phim sai",
        "",
        "| Tiêu đề | Nhãn đúng | FinBERT (P+ / P−) | Model review phim (P+) |",
        "|---|---|---|---|",
    ]
    for e in result["evaluation"]["examples"]["finbert_right_general_wrong"]:
        lines.append(f"| {e['text'].replace('|', '/')} | {e['gold']} | {e['finbert_direction']} ({e['finbert']['positive']:.2f} / {e['finbert']['negative']:.2f}) | {e['general_label']} ({e['general_positive']:.2f}) |")
    lines += ["", "## 4. Ví dụ ngược lại: model review phim đúng, FinBERT sai (để không chọn lọc một chiều)", "", "| Tiêu đề | Nhãn đúng | FinBERT (P+ / P−) | Model review phim (P+) |", "|---|---|---|---|"]
    for e in result["evaluation"]["examples"]["general_right_finbert_wrong"]:
        lines.append(f"| {e['text'].replace('|', '/')} | {e['gold']} | {e['finbert_direction']} ({e['finbert']['positive']:.2f} / {e['finbert']['negative']:.2f}) | {e['general_label']} ({e['general_positive']:.2f}) |")
    c = result["evaluation"].get("confidence")
    if c:
        lines += [
            "",
            "## 5. Kiểm chứng Module 1: độ rõ |P+ − P−| có báo trước FinBERT đúng hay sai?",
            "",
            "| Độ rõ \\|P+ − P−\\| | Số tin | Tin thực chất trung tính | Đoán đúng chiều (trên tin có chiều rõ) |",
            "|---|---|---|---|",
        ]
        for b in c["buckets"]:
            acc = _pct(b["direction_accuracy"]) + f" ({b['directional_n']} tin)" if b["direction_accuracy"] is not None else "—"
            neu_share = _pct(b["neutral_share"]) if b["neutral_share"] is not None else "—"
            lines.append(f"| {b['low']:.1f} – {b['high']:.1f} | {b['n']} | {neu_share} | {acc} |")
        e, w = c["vote_share_equal"], c["vote_share_confidence"]
        lines += [
            "",
            "| Phần \"phiếu\" (mẫu số khi lấy trung bình) rơi vào | Bài báo: mỗi tin 1 phiếu | Module 1: phiếu = độ rõ |",
            "|---|---|---|",
            f"| Tin đúng chiều | {_pct(e['right_direction'])} | {_pct(w['right_direction'])} |",
            f"| Tin sai chiều | {_pct(e['wrong_direction'])} | {_pct(w['wrong_direction'])} |",
            f"| Tin thực chất trung tính (làm loãng điểm) | {_pct(e['neutral_news'])} | {_pct(w['neutral_news'])} |",
            "",
            "Đọc: tin FinBERT chấm càng rõ thì càng hay đúng chiều, nên cho tin rõ nhiều phiếu hơn là có cơ sở. Phần phiếu sai chiều gần như không giảm: những lần FinBERT sai mà rất chắc chắn vẫn lọt qua.",
        ]
    lines += [
        "",
        "## Giới hạn",
        "",
        "- Tin của bộ dữ liệu là tin tài chính tiếng Anh nói chung (chủ yếu thị trường Mỹ), không phải tin EGX.",
        "- Model review phim chỉ có 2 nhãn, nên so sánh công bằng chỉ làm trên tin có chiều rõ.",
        "- Không dùng Financial PhraseBank (bộ dữ liệu trong README) vì FinBERT đã học trên bộ đó.",
        "",
    ]
    return "\n".join(lines)


async def _finbert_probs(provider: Any, texts: list[str]) -> list[dict[str, float]]:
    return await provider.classify_many(texts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-csv", help="CSV có cột text và label; bỏ trống để tải tập validation Twitter Financial News.")
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--revision", default=DEFAULT_LOCAL_MODEL_REVISION)
    parser.add_argument("--general-model", default=GENERAL_MODEL)
    parser.add_argument("--general-revision", default=None)
    parser.add_argument("--limit", type=int, default=0, help="Chỉ lấy N dòng đầu (0 = tất cả), để chạy thử nhanh.")
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "evaluation"))
    parser.add_argument("--from-run", help="Thư mục kết quả của một lần chạy trước (predictions.csv + evaluation_results.json): tính lại chỉ số, bảng, biểu đồ mà không chạy model.")
    args = parser.parse_args()

    from backend.upgrades.charts import chart_accuracy_comparison, chart_confidence_check

    started = time.perf_counter()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.from_run:
        run_dir = Path(args.from_run)
        rows = read_predictions_csv(run_dir / "predictions.csv")
        meta = json.loads((run_dir / "evaluation_results.json").read_text(encoding="utf-8"))["meta"]
        meta["recomputed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        evaluation = evaluate(rows)
        result = {"meta": meta, "evaluation": evaluation}
        note = " · FinBERT chưa từng học bộ này." if meta["dataset"] == TWITTER_REPO else "."
        chart_accuracy_comparison(evaluation, out / "chart4_finbert_vs_general.png", f"Dữ liệu: {meta['dataset']} ({meta['dataset_file']}), {len(rows)} tin tài chính tiếng Anh có nhãn sẵn{note}")
        chart_confidence_check(evaluation["confidence"], out / "chart5_confidence_check.png", f"Cùng {len(rows)} tin có nhãn của biểu đồ 4 ({meta['dataset']}); độ rõ là của FinBERT revision {str(meta['finbert_revision'])[:8]}.")
        write_predictions_csv(rows, out / "predictions.csv")
        (out / "evaluation_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "BANG_DANH_GIA.md").write_text(render_markdown(result), encoding="utf-8")
        print(f"Đã tính lại từ {run_dir} → {out}")
        return

    from backend.providers.transformers_local import TransformersLocalFinBERT

    print("[1/5] Nạp dữ liệu có nhãn")
    if args.data_csv:
        data_path, data_sha, data_file, dataset = Path(args.data_csv), None, Path(args.data_csv).name, "local CSV"
    else:
        data_path, data_sha, data_file = download_twitter_split("valid")
        dataset = TWITTER_REPO
    rows = read_labeled_csv(data_path)
    if args.limit:
        rows = rows[: args.limit]
    counts = {MARKET_NAME[label]: sum(r["gold"] == label for r in rows) for label in LABELS}
    print(f"      {len(rows)} tin · {counts}")

    print(f"[2/5] FinBERT {args.model} @ {args.revision}")
    finbert = TransformersLocalFinBERT(model_id=args.model, revision=args.revision, device_preference="auto")
    texts = [r["text"] for r in rows]
    for r, probs in zip(rows, asyncio.run(_finbert_probs(finbert, texts)), strict=True):
        r["finbert"] = probs

    print(f"[3/5] Model so sánh {args.general_model}")
    general = GeneralSentimentModel(args.general_model, args.general_revision)
    for r, p in zip(rows, general.positive_probability(texts), strict=True):
        r["general_positive"] = p

    print("[4/5] Tính chỉ số")
    evaluation = evaluate(rows)
    d = evaluation["directional_subset"]
    print(f"      Tin có chiều rõ ({d['n']}): FinBERT {d['finbert']['accuracy']:.1%} vs model review phim {d['general']['accuracy']:.1%} · McNemar p = {d['mcnemar']['p_value']:.2g}")
    print(f"      FinBERT 3 nhãn: {evaluation['finbert_three_class']['accuracy']:.1%}, macro-F1 {evaluation['finbert_three_class']['macro_f1']:.3f}")

    result = {
        "meta": {
            "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "python": platform.python_version(),
            "dataset": dataset,
            "dataset_file": data_file,
            "dataset_revision": data_sha,
            "finbert_model": args.model,
            "finbert_revision": args.revision,
            "finbert_device": finbert.device_name,
            "general_model": args.general_model,
            "general_revision": general.revision,
            "seconds": time.perf_counter() - started,
        },
        "evaluation": evaluation,
    }

    print("[5/5] Xuất biểu đồ, bảng, CSV")
    note = " · FinBERT chưa từng học bộ này." if dataset == TWITTER_REPO else "."
    chart_accuracy_comparison(evaluation, out / "chart4_finbert_vs_general.png", f"Dữ liệu: {dataset} ({data_file}), {len(rows)} tin tài chính tiếng Anh có nhãn sẵn{note}")
    chart_confidence_check(evaluation["confidence"], out / "chart5_confidence_check.png", f"Cùng {len(rows)} tin có nhãn của biểu đồ 4 ({dataset}); độ rõ là của FinBERT revision {str(args.revision)[:8]}.")
    write_predictions_csv(rows, out / "predictions.csv")
    (out / "evaluation_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "BANG_DANH_GIA.md").write_text(render_markdown(result), encoding="utf-8")
    print(f"Xong → {out}")


if __name__ == "__main__":
    main()
