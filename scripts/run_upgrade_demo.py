"""Chạy THẬT 3 module nâng cấp trên FinBERT và xuất 3 biểu đồ PNG + bảng số liệu Markdown.

Cách chạy (từ thư mục gốc dự án):
    python -m scripts.run_upgrade_demo
    python -m scripts.run_upgrade_demo --model D:/models/finbert   # nếu đã có model ở thư mục local
    python -m scripts.run_upgrade_demo --from-run artifacts/upgrade --out artifacts/upgrade_v2
        # tính lại điểm, bảng, biểu đồ từ xác suất FinBERT đã lưu; không nạp model, không cần mạng

Đầu ra: artifacts/upgrade/
    chart1_softmax_time_decay.png
    chart2_portfolio_article_vs_upgrade.png
    chart3_latency_cache.png
    BANG_SO_LIEU.md          (bảng Markdown để dán thẳng vào slide)
    upgrade_results.json     (toàn bộ số liệu thô)

Model chạy bằng ĐÚNG lớp lõi `TransformersLocalFinBERT` (không viết lại phần suy luận).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.providers.hf_inference import HuggingFaceFinBERT
from backend.providers.transformers_local import TransformersLocalFinBERT
from backend.upgrades.charts import chart_latency, chart_portfolio_comparison, chart_softmax_and_decay
from backend.upgrades.portfolio_weighting import Position, article_baseline, portfolio_sentiment
from backend.upgrades.time_confidence import (
    DEFAULT_HALF_LIFE_HOURS,
    DEFAULT_NEUTRAL_BAND,
    DEFAULT_PRIOR_STRENGTH,
    aggregate_signal,
    decay_table,
    display_label,
    has_enough_evidence,
    label_with_evidence,
    sigmoid,
    softmax,
    time_decay_weight,
    weigh_headline,
)
from backend.upgrades.ttl_cache import CachedInference, TTLCache

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("positive", "negative", "neutral")
DECAY_MARKERS = (1, 6, 12, 24, 48)

# ---------------------------------------------------------------------------
# BỘ A — Kịch bản kiểm thử theo ĐÚNG cấu trúc danh mục của bài báo (mục 6):
# 4 tin macro + 2 tin mỗi mã COMI / ETEL / FWRY. Tiêu đề do nhóm soạn để kiểm thử
# (ghi rõ trên slide); điểm 3 nhãn là do FinBERT chấm THẬT khi chạy script này.
# ---------------------------------------------------------------------------
SCENARIO_HEADLINES: list[dict[str, Any]] = [
    {"title": "Commercial International Bank quarterly net profit falls 18% as loan-loss provisions surge", "kind": "micro", "symbol": "COMI.EGX", "age_hours": 2},
    {"title": "CIB named best bank in Egypt for the fifth consecutive year", "kind": "micro", "symbol": "COMI.EGX", "age_hours": 40},
    {"title": "Telecom Egypt revenue rises 35% driven by strong data growth", "kind": "micro", "symbol": "ETEL.EGX", "age_hours": 5},
    {"title": "Telecom Egypt to hold board meeting on Thursday", "kind": "micro", "symbol": "ETEL.EGX", "age_hours": 20},
    {"title": "Fawry posts record quarterly profit as digital payments surge", "kind": "micro", "symbol": "FWRY.EGX", "age_hours": 1},
    {"title": "Fawry expands merchant network to more than 400,000 outlets", "kind": "micro", "symbol": "FWRY.EGX", "age_hours": 8},
    {"title": "Egypt's central bank unexpectedly raises interest rates by 200 basis points", "kind": "macro", "symbol": None, "age_hours": 3},
    {"title": "Egypt's annual inflation accelerates to 26%, highest in five months", "kind": "macro", "symbol": None, "age_hours": 6},
    {"title": "Egypt secures $1.2 billion IMF loan disbursement after programme review", "kind": "macro", "symbol": None, "age_hours": 30},
    {"title": "Egypt's non-oil private sector PMI unchanged at 49.5 in October", "kind": "macro", "symbol": None, "age_hours": 48},
]
# Tỷ trọng vốn theo ví dụ của bạn (A 70% / B 20% / C 10%). Beta vĩ mô là GIẢ ĐỊNH ĐẦU VÀO:
# ngân hàng nhạy lãi suất/tỷ giá (1.2), viễn thông phòng thủ (0.6), ví điện tử ~ thị trường (1.0).
SCENARIO_POSITIONS = [
    Position("COMI.EGX", 0.70, 1.2),
    Position("ETEL.EGX", 0.20, 0.6),
    Position("FWRY.EGX", 0.10, 1.0),
]

# BỘ B — Tin THẬT (RSS) do máy của bạn thu thập lúc chạy kiểm chứng 01/11/2026
# (artifacts/local_inference_api_results.json, danh mục 5 mã). Tỷ trọng là giả định minh họa.
REAL_POSITIONS = [
    Position("COMI.EGX", 0.40, 1.2),
    Position("ETEL.EGX", 0.20, 0.6),
    Position("FWRY.EGX", 0.15, 1.0),
    Position("ADIB.EGX", 0.15, 1.2),
    Position("EFIH.EGX", 0.10, 1.0),
]

# Tiêu đề "hai chiều" để kiểm tra lỗi "91% Bull / 91% Bear" khi KHÔNG dùng softmax.
MIXED_HEADLINES = [
    "Bank profit jumps 40% but bad loans double",
    "Revenue beats expectations while margins collapse",
    "Egyptian pound plunges as IMF approves bailout",
    "Shares rally despite record quarterly loss",
    "Fawry revenue climbs even as net profit falls",
    "CIB profit rises but provisions surge",
]


def short(symbol: str | None) -> str:
    return (symbol or "").removesuffix(".EGX") or "Vĩ mô"


def logits_for(provider: TransformersLocalFinBERT, texts: list[str]) -> list[dict[str, float]]:
    torch = provider.torch
    encoded = provider.tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
    encoded = {k: v.to(provider.device) for k, v in encoded.items()}
    with torch.inference_mode():
        logits = provider.model(**encoded).logits.cpu().tolist()
    return [{provider.id2label[i]: float(row[i]) for i in range(len(row))} for row in logits]


def build_items(rows: list[dict[str, Any]], probs: list[dict[str, float]], now: datetime) -> list[dict[str, Any]]:
    items = []
    for row, p in zip(rows, probs, strict=True):
        item = {k: v for k, v in row.items() if k != "age_hours"}
        item["published_at"] = (now - timedelta(hours=row["age_hours"])).isoformat()
        item["source"] = "Kịch bản kiểm thử"
        item["probabilities"] = p
        items.append(item)
    return items


def compare_methods(items: list[dict[str, Any]], positions: list[Position], now: datetime) -> dict[str, Any]:
    baseline = article_baseline(items)
    weighted = [weigh_headline(item, now) for item in items]
    module1_only = aggregate_signal(weighted, DEFAULT_PRIOR_STRENGTH)
    full = portfolio_sentiment(items, positions, now).to_dict()
    for row, c in zip(full["headlines"], baseline["headline_contributions"], strict=True):
        row["article_contribution"] = c
    module1_label = label_with_evidence(module1_only.score, module1_only.evidence, DEFAULT_PRIOR_STRENGTH)
    return {"article": baseline, "module1_only": module1_only.to_dict() | {"sentiment": module1_label}, "full": full}


def attribution_groups(result: dict[str, Any], positions: list[Position]) -> list[dict[str, Any]]:
    groups = []
    for p in positions:
        rows = [h for h in result["full"]["headlines"] if h["kind"] != "macro" and h["symbol"] == p.symbol]
        groups.append(
            {
                "name": f"{short(p.symbol)} ({p.capital_weight:.0%} vốn, β={p.macro_beta:g})",
                "article": sum(h["article_contribution"] for h in rows),
                "upgraded": sum(h["contribution"] for h in rows),
            }
        )
    macro_rows = [h for h in result["full"]["headlines"] if h["kind"] == "macro"]
    groups.append(
        {
            "name": f"Tin vĩ mô (β danh mục={result['full']['portfolio_beta']:.2f})",
            "article": sum(h["article_contribution"] for h in macro_rows),
            "upgraded": sum(h["contribution"] for h in macro_rows),
        }
    )
    return groups


async def latency_benchmark(provider: TransformersLocalFinBERT, items: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    """Chuỗi 12 request trong cùng một cửa sổ TTL: 3 người dùng mở mã lẻ và danh mục, rồi có 1 tin mới."""
    micro = {s: [i["title"] for i in items if i.get("symbol") == s] for s in ("COMI.EGX", "ETEL.EGX", "FWRY.EGX")}
    macro = [i["title"] for i in items if i["kind"] == "macro"]
    portfolio = [t for s in micro for t in micro[s]] + macro
    breaking = "Commercial International Bank shares drop 6% after central bank rate hike"
    trace = [
        ("Người A: mở COMI", micro["COMI.EGX"] + macro),
        ("Người A: mở ETEL", micro["ETEL.EGX"] + macro),
        ("Người A: danh mục", portfolio),
        ("Người B: mở COMI", micro["COMI.EGX"] + macro),
        ("Người B: mở FWRY", micro["FWRY.EGX"] + macro),
        ("Người B: danh mục", portfolio),
        ("Người C: mở ETEL", micro["ETEL.EGX"] + macro),
        ("Người C: danh mục", portfolio),
        ("Người A: làm mới COMI", micro["COMI.EGX"] + macro),
        ("Người A: làm mới danh mục", portfolio),
        ("Tin mới về COMI: mở COMI", [breaking] + micro["COMI.EGX"] + macro),
        ("Tin mới: danh mục", [breaking] + portfolio),
    ]
    # Làm nóng model (lần đầu PyTorch cấp phát bộ nhớ) để không tính oan cho luồng nào.
    await provider.classify_many(portfolio)

    direct_runs: list[list[float]] = []
    cached_runs: list[list[float]] = []
    per_request_calls: list[dict[str, int]] = []
    for rep in range(repeats):
        direct_ms = []
        for _, texts in trace:
            t0 = time.perf_counter()
            scores = await provider.classify_many(texts)  # luồng gốc: chấm lại toàn bộ
            article_baseline([{"probabilities": s} for s in scores])
            direct_ms.append((time.perf_counter() - t0) * 1000)
        direct_runs.append(direct_ms)

        cache = TTLCache(ttl_seconds=24 * 3600)
        cached = CachedInference(provider, cache, MODEL_ID, provider.revision)
        cached_ms = []
        calls = []
        for _, texts in trace:
            t0 = time.perf_counter()
            scores = await cached.classify_many(texts)
            article_baseline([{"probabilities": s} for s in scores])
            cached_ms.append((time.perf_counter() - t0) * 1000)
            calls.append(dict(cached.last_call))
        cached_runs.append(cached_ms)
        per_request_calls = calls
        cache_stats = cache.stats()

    rows = []
    for idx, (label, texts) in enumerate(trace):
        rows.append(
            {
                "request": idx + 1,
                "label": label,
                "headlines": len(texts),
                "direct_ms": statistics.median(run[idx] for run in direct_runs),
                "cached_ms": statistics.median(run[idx] for run in cached_runs),
                "cache_hits": per_request_calls[idx]["cache_hits"],
                "model_calls": per_request_calls[idx]["model_calls"],
            }
        )

    def p95(values: list[float]) -> float:
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]

    direct_vals = [r["direct_ms"] for r in rows]
    cached_vals = [r["cached_ms"] for r in rows]
    direct_calls = sum(r["headlines"] for r in rows)
    cached_calls = sum(r["model_calls"] for r in rows)
    return {
        "repeats": repeats,
        "trace": rows,
        "summary": {
            "Gọi trực tiếp\n(bài báo)": {"mean_ms": statistics.mean(direct_vals), "p95_ms": p95(direct_vals), "total_ms": sum(direct_vals), "model_calls": direct_calls},
            "Có TTL cache\n(code mới)": {"mean_ms": statistics.mean(cached_vals), "p95_ms": p95(cached_vals), "total_ms": sum(cached_vals), "model_calls": cached_calls},
        },
        "hf_api_requests_if_hf_provider": {"direct": direct_calls, "cached": cached_calls},
        "hf_http_requests": hf_http_requests(rows),
        "cache_stats_last_repeat": cache_stats,
    }


def hf_http_requests(trace: list[dict[str, Any]], batch_size: int = HuggingFaceFinBERT.BATCH_SIZE) -> dict[str, int]:
    """Số request HTTP tới HF Inference API suy ra từ chuỗi request (không gọi HF thật).

    Code gốc gửi 1 tiêu đề mỗi request; code mới gửi tối đa batch_size tiêu đề mỗi request.
    Với cache, chỉ các tiêu đề chưa có trong cache (model_calls) mới phải gửi đi.
    """

    def batches(n: int) -> int:
        return -(-n // batch_size) if n > 0 else 0

    return {
        "batch_size": batch_size,
        "one_per_headline_direct": sum(t["headlines"] for t in trace),
        "one_per_headline_cached": sum(t["model_calls"] for t in trace),
        "batched_direct": sum(batches(t["headlines"]) for t in trace),
        "batched_cached": sum(batches(t["model_calls"]) for t in trace),
    }


def fmt(v: float | None, d: int = 3, sign: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"


def md_headline_table(result: dict[str, Any], show_source: bool = False) -> str:
    head = "| # | Tiêu đề tin | Loại | Mã | Số giờ đã đăng | Tỷ trọng vốn | β vĩ mô | P(Positive) | P(Negative) | P(Neutral) | Điểm tin s = P+ − P− | w_time | w_conf | w = w_time × w_conf | Đóng góp — Bài báo gốc | Đóng góp — Code mới |"
    if show_source:
        head = head.replace("| Loại |", "| Nguồn | Loại |")
    sep = "|" + "---|" * (head.count("|") - 1)
    lines = [head, sep]
    holdings = {h["symbol"]: h for h in result["full"]["holdings"]}
    for i, h in enumerate(result["full"]["headlines"], 1):
        p = h["probabilities"]
        if h["kind"] == "macro":
            cap, beta = "toàn danh mục", f"{result['full']['portfolio_beta']:.2f} (β danh mục)"
        else:
            hold = holdings.get(h["symbol"])
            cap = f"{hold['capital_weight']:.0%}" if hold else "0%"
            beta = f"{hold['macro_beta']:g}" if hold else "—"
        age = f"{h['age_hours']:.0f}" + (" (giả định)" if h["age_is_assumed"] else "")
        cells = [
            str(i),
            h["title"].replace("|", "/"),
            *([h.get("source") or ""] if show_source else []),
            "Vĩ mô" if h["kind"] == "macro" else "Riêng mã",
            short(h["symbol"]),
            age,
            cap,
            beta,
            fmt(p["positive"]),
            fmt(p["negative"]),
            fmt(p["neutral"]),
            fmt(h["score"], sign=True),
            fmt(h["time_weight"]),
            fmt(h["confidence_weight"]),
            fmt(h["weight"]),
            fmt(h["article_contribution"], 4, True),
            fmt(h["contribution"], 4, True),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    total_article = sum(h["article_contribution"] for h in result["full"]["headlines"])
    total_new = sum(h["contribution"] for h in result["full"]["headlines"])
    blanks = ["", "**TỔNG = điểm danh mục**"] + [""] * (len(lines[0].split("|")) - 5)
    blanks[-2] = f"**{total_article:+.4f}** ({display_label(result['article']['sentiment'])})"
    blanks[-1] = f"**{total_new:+.4f}** ({display_label(result['full']['sentiment'])})"
    lines.append("| " + " | ".join(blanks) + " |")
    return "\n".join(lines)


def md_holding_table(result: dict[str, Any]) -> str:
    lines = [
        "| Mã | Tỷ trọng vốn | β vĩ mô | Số tin riêng | Điểm tin riêng micro_k | β × M (M = điểm vĩ mô) | Điểm mã S_k | Đóng góp = vốn × S_k | Bài báo: tổng đóng góp tin riêng của mã |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for h in result["full"]["holdings"]:
        art = sum(x["article_contribution"] for x in result["full"]["headlines"] if x["kind"] != "macro" and x["symbol"] == h["symbol"])
        clip = " (đã chặn ±1)" if h["clip_factor"] < 1 else ""
        lines.append(
            f"| {short(h['symbol'])} | {h['capital_weight']:.0%} | {h['macro_beta']:g} | {h['micro']['count']} | {h['micro']['score']:+.3f} | "
            f"{h['macro_component']:+.3f} | {h['stock_score']:+.3f}{clip} | {h['contribution']:+.4f} | {art:+.4f} |"
        )
    m = result["full"]["macro"]
    lines.append(
        f"| **Vĩ mô** | — | β danh mục = {result['full']['portfolio_beta']:.2f} | {m['count']} | M = {m['score']:+.3f} | — | — | "
        f"(đã nằm trong cột β × M) | {sum(x['article_contribution'] for x in result['full']['headlines'] if x['kind'] == 'macro'):+.4f} |"
    )
    lines.append(
        f"| **Danh mục** | 100% | | | | | | **{result['full']['score']:+.4f} ({display_label(result['full']['sentiment'])})** | **{result['article']['score']:+.4f} ({result['article']['sentiment']})** |"
    )
    return "\n".join(lines)


def md_evidence_table(result: dict[str, Any]) -> str:
    """Σw của từng nhóm tin so với ngưỡng κ: căn cứ của trạng thái "Không đủ tin"."""
    full = result["full"]
    groups = full.get("evidence_by_group")
    if not groups:
        return ""
    threshold = full["evidence_threshold"]
    lines = [
        f"Trạng thái bằng chứng (một nhóm tin \"đủ tin\" khi tổng trọng số Σw ≥ κ = {threshold:g}, tức bằng chứng nặng hơn độ hoài nghi ban đầu):",
        "",
        "| Nhóm tin | Số tin | Σw | Đủ tin? |",
        "|---|---|---|---|",
    ]
    counts = {h["symbol"]: h["micro"]["count"] for h in full["holdings"]}
    counts["macro"] = full["macro"]["count"]
    for name, value in groups.items():
        label = "Tin vĩ mô" if name == "macro" else f"Tin riêng {short(name)}"
        lines.append(f"| {label} | {counts.get(name, 0)} | {value:.3f} | {'Có' if has_enough_evidence(value, threshold) else 'Không'} |")
    verdict = (
        f"Kết luận: có nhóm đủ tin, nhãn danh mục là **{display_label(full['sentiment'])}**."
        if full["evidence_status"] == "enough"
        else f"Kết luận: không nhóm nào đủ tin, nhãn danh mục là **Không đủ tin** (riêng điểm số {full['score']:+.3f} sẽ cho {full['score_label']})."
    )
    return "\n".join(lines + ["", verdict])


def md_summary_table(result: dict[str, Any]) -> str:
    a, m1, f = result["article"], result["module1_only"], result["full"]
    return "\n".join(
        [
            "| Cách tính | Điểm danh mục | Nhãn | P(Pos) TB | P(Neg) TB | P(Neu) TB |",
            "|---|---|---|---|---|---|",
            f"| Bài báo gốc: trung bình phẳng 10 tin | {a['score']:+.3f} | {a['sentiment']} | {a['probabilities']['positive']:.3f} | {a['probabilities']['negative']:.3f} | {a['probabilities']['neutral']:.3f} |",
            f"| + Module 1 (thời gian × độ rõ), vẫn gộp phẳng | {m1['score']:+.3f} | {display_label(m1['sentiment'])} | {m1['weighted_probabilities']['positive']:.3f} | {m1['weighted_probabilities']['negative']:.3f} | {m1['weighted_probabilities']['neutral']:.3f} |",
            f"| + Module 1 + Module 2 (vốn 70/20/10, β vĩ mô) | {f['score']:+.3f} | {display_label(f['sentiment'])} | — | — | — |",
        ]
    )


def write_outputs(results: dict[str, Any], out: Path) -> None:
    """Vẽ 3 biểu đồ, ghi upgrade_results.json và BANG_SO_LIEU.md từ một dict kết quả."""
    scenario, latency = results["scenario"], results["latency"]
    hours = [h / 4 for h in range(0, 48 * 4 + 1)]
    decay_rows = {
        f"Tin riêng mã (H = {DEFAULT_HALF_LIFE_HOURS['micro']:g}h)": decay_table(hours, DEFAULT_HALF_LIFE_HOURS["micro"]),
        f"Tin vĩ mô (H = {DEFAULT_HALF_LIFE_HOURS['macro']:g}h)": decay_table(hours, DEFAULT_HALF_LIFE_HOURS["macro"]),
    }
    c1 = chart_softmax_and_decay(results["softmax_demo"]["chosen"], decay_rows, DECAY_MARKERS, out / "chart1_softmax_time_decay.png")
    steps = [
        {"name": "Bài báo gốc\n(trung bình phẳng)", "score": scenario["article"]["score"], "sentiment": scenario["article"]["sentiment"]},
        {"name": "+ Module 1\n(thời gian × độ rõ)", "score": scenario["module1_only"]["score"], "sentiment": scenario["module1_only"]["sentiment"]},
        {"name": "+ Module 1 + 2\n(vốn 70/20/10 & β)", "score": scenario["full"]["score"], "sentiment": scenario["full"]["sentiment"]},
    ]
    positions = [Position(**p) for p in scenario["positions"]]
    c2 = chart_portfolio_comparison(
        steps,
        attribution_groups(scenario, positions),
        out / "chart2_portfolio_article_vs_upgrade.png",
        "Danh mục COMI 70% · ETEL 20% · FWRY 10%; 4 tin vĩ mô + 2 tin/mã như bài báo. Điểm 3 nhãn do FinBERT chấm thật trong lần chạy này.",
    )
    c3 = chart_latency(
        latency["trace"],
        latency["summary"],
        out / "chart3_latency_cache.png",
        f"12 request liên tiếp (3 người dùng, 1 tin mới ở cuối) · FinBERT local CPU, {results['runtime']['threads']} luồng · trung vị của {latency['repeats']} lần chạy.",
    )
    results["charts"] = [c1.name, c2.name, c3.name]
    (out / "upgrade_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "BANG_SO_LIEU.md").write_text(render_markdown(results), encoding="utf-8")


def items_from_saved(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Dựng lại danh sách tin (kèm xác suất FinBERT đã chấm) từ một khối kết quả đã lưu."""
    keys = ("title", "kind", "symbol", "source", "published_at", "probabilities")
    return [{k: h.get(k) for k in keys} for h in block["full"]["headlines"]]


def rebuild_from_run(run_dir: Path, out: Path) -> dict[str, Any]:
    """Tính lại 3 cách tính điểm, bảng và biểu đồ từ upgrade_results.json của một lần chạy trước.

    Không nạp model: dùng đúng xác suất FinBERT đã lưu, nên số liệu vẫn là của model trong lần chạy đó
    (phần kiểm chứng phiên bản model, softmax và latency được giữ nguyên như lần chạy gốc).
    """
    saved = json.loads((Path(run_dir) / "upgrade_results.json").read_text(encoding="utf-8"))
    results = dict(saved)
    results["recomputed_at_utc"] = datetime.now(timezone.utc).isoformat()
    for key in ("scenario", "real_rss"):
        block = saved.get(key)
        if not block:
            continue
        now = datetime.fromisoformat(block["now_utc"])
        positions = [Position(**p) for p in block["positions"]]
        results[key] = {"now_utc": block["now_utc"], "positions": block["positions"], **compare_methods(items_from_saved(block), positions, now)}
    results["latency"] = dict(saved["latency"])
    results["latency"]["hf_http_requests"] = hf_http_requests(results["latency"]["trace"])
    out.mkdir(parents=True, exist_ok=True)
    write_outputs(results, out)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=MODEL_ID, help="Model id trên Hugging Face hoặc đường dẫn thư mục model local.")
    parser.add_argument("--revision", default=DEFAULT_LOCAL_MODEL_REVISION)
    parser.add_argument("--reference", default=str(ROOT / "artifacts" / "local_inference_api_results.json"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "upgrade"))
    parser.add_argument("--repeats", type=int, default=5, help="Số lần lặp benchmark latency (lấy trung vị).")
    parser.add_argument("--tolerance", type=float, default=1e-3, help="Sai khác tối đa cho phép so với kết quả tham chiếu.")
    parser.add_argument("--allow-model-mismatch", action="store_true", help="Vẫn chạy tiếp khi model lệch kết quả tham chiếu.")
    parser.add_argument("--from-run", help="Thư mục có upgrade_results.json của lần chạy trước: tính lại điểm, bảng, biểu đồ mà không nạp model.")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.from_run:
        rebuild_from_run(Path(args.from_run), out)
        print(f"Đã tính lại từ {args.from_run} → {out}")
        return
    print(f"[1/6] Nạp FinBERT: {args.model}")
    t0 = time.perf_counter()
    provider = TransformersLocalFinBERT(model_id=args.model, revision=args.revision, device_preference="cpu")
    load_s = time.perf_counter() - t0
    print(f"      xong sau {load_s:.1f}s, device={provider.device_name}, nhãn={provider.id2label}")

    results: dict[str, Any] = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "revision_arg": args.revision,
        "runtime": {"python": platform.python_version(), "machine": platform.machine(), "torch": provider.torch.__version__, "device": provider.device_name, "threads": provider.torch.get_num_threads()},
        "model_load_seconds": load_s,
    }

    # --- Kiểm chứng: model trong lần chạy này cho ra đúng số như máy của bạn đã chạy ---
    ref_path = Path(args.reference)
    real_items: list[dict[str, Any]] = []
    real_now = None
    if ref_path.exists():
        print("[2/6] Đối chiếu với kết quả FinBERT thật trên máy bạn")
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        real_now = datetime.fromisoformat(ref["checked_at_utc"].replace("Z", "+00:00")[:26] + "+00:00")
        seen: dict[str, dict[str, Any]] = {}
        for section in ("single_stock", "five_symbol_portfolio"):
            for h in ref.get(section, {}).get("headlines", []):
                seen.setdefault(h["title"], h)
        titles = list(seen)
        mine = asyncio.run(provider.classify_many(titles))
        diffs = [max(abs(m[k] - seen[t]["probabilities"][k]) for k in LABELS) for t, m in zip(titles, mine)]
        results["validation"] = {
            "reference_file": ref_path.name,
            "reference_revision": ref["health"]["inference_revision"],
            "headlines": len(titles),
            "max_abs_diff": max(diffs),
            "rows": [{"title": t, "reference": seen[t]["probabilities"], "this_run": m, "max_abs_diff": d} for t, m, d in zip(titles, mine, diffs)],
        }
        print(f"      {len(titles)} tiêu đề, sai khác lớn nhất = {max(diffs):.2e}")
        if max(diffs) > args.tolerance and not args.allow_model_mismatch:
            raise SystemExit(
                f"DỪNG: model lần này lệch {max(diffs):.3f} so với kết quả tham chiếu (ngưỡng {args.tolerance}). "
                "Có thể sai phiên bản model; số liệu sẽ không khớp slide. Kiểm tra --model/--revision, "
                "hoặc thêm --allow-model-mismatch nếu cố ý chạy bản khác."
            )
        port = ref["five_symbol_portfolio"]["headlines"]
        port_probs = asyncio.run(provider.classify_many([h["title"] for h in port]))
        for h, p in zip(port, port_probs):
            item = {k: h[k] for k in ("title", "kind", "symbol", "published_at", "source")}
            item["probabilities"] = p
            real_items.append(item)

    # --- Bộ A: kịch bản ---
    print("[3/6] Chấm FinBERT bộ kịch bản + so sánh 3 cách tính")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    scen_probs = asyncio.run(provider.classify_many([r["title"] for r in SCENARIO_HEADLINES]))
    scen_items = build_items(SCENARIO_HEADLINES, scen_probs, now)
    scenario = compare_methods(scen_items, SCENARIO_POSITIONS, now)
    results["scenario"] = {"now_utc": now.isoformat(), "positions": [p.__dict__ for p in SCENARIO_POSITIONS], **scenario}
    print(f"      Bài báo: {scenario['article']['score']:+.3f} {scenario['article']['sentiment']} | Code mới: {scenario['full']['score']:+.3f} {scenario['full']['sentiment']}")

    real = None
    if real_items:
        real = compare_methods(real_items, REAL_POSITIONS, real_now)
        results["real_rss"] = {"now_utc": real_now.isoformat(), "positions": [p.__dict__ for p in REAL_POSITIONS], **real}
        print(f"      Tin thật — Bài báo: {real['article']['score']:+.3f} {real['article']['sentiment']} | Code mới: {real['full']['score']:+.3f} {real['full']['sentiment']}")

    # --- Softmax vs không softmax ---
    print("[4/6] Lấy logits thật để so sánh có/không softmax")
    sources = (
        [(t, "câu thử hai chiều, tự soạn") for t in MIXED_HEADLINES]
        + [(r["title"], "tiêu đề kịch bản theo bài báo") for r in SCENARIO_HEADLINES]
        + [(i["title"], "tin RSS thật") for i in real_items]
    )
    pool = [t for t, _ in sources]
    logit_rows = logits_for(provider, pool)
    cases = []
    for (title, source), lg in zip(sources, logit_rows):
        values = [lg[k] for k in LABELS]
        sg = dict(zip(LABELS, sigmoid(values)))
        sm = dict(zip(LABELS, softmax(values)))
        cases.append({"title": title, "source": source, "logits": lg, "sigmoid": sg, "softmax": sm, "sigmoid_sum": sum(sg.values()), "bull_bear_min": min(sg["positive"], sg["negative"])})
    both_way = max(cases, key=lambda c: c["bull_bear_min"])
    one_way = max((c for c in cases if c is not both_way), key=lambda c: c["sigmoid_sum"])
    results["softmax_demo"] = {"chosen": [both_way, one_way], "all_cases": cases}
    print(f"      Ca hai chiều: “{both_way['title']}” sigmoid Pos={both_way['sigmoid']['positive']:.0%} Neg={both_way['sigmoid']['negative']:.0%}")

    # --- Latency ---
    print(f"[5/6] Đo latency (lặp {args.repeats} lần, lấy trung vị)")
    latency = asyncio.run(latency_benchmark(provider, scen_items, args.repeats))
    results["latency"] = latency
    s = latency["summary"]
    for name, v in s.items():
        print(f"      {name.replace(chr(10), ' ')}: TB {v['mean_ms']:.2f} ms, p95 {v['p95_ms']:.2f} ms, model calls {v['model_calls']}")

    print("[6/6] Vẽ biểu đồ + bảng")
    write_outputs(results, out)
    print(f"Xong → {out}")


def render_markdown(r: dict[str, Any]) -> str:
    sc = r["scenario"]
    lines = [
        "# Bảng số liệu đầu ra — chạy thật",
        "",
        f"- Thời điểm chạy: {r['run_at_utc']} · Model: `{r['model']}` · Torch {r['runtime']['torch']} · {r['runtime']['device']} · {r['runtime']['threads']} luồng CPU",
        f"- Tham số Module 1: chu kỳ bán rã tin riêng mã H = {DEFAULT_HALF_LIFE_HOURS['micro']:g}h, tin vĩ mô H = {DEFAULT_HALF_LIFE_HOURS['macro']:g}h; độ hoài nghi κ = {DEFAULT_PRIOR_STRENGTH}; vùng Neutral ±{DEFAULT_NEUTRAL_BAND}.",
        "- Công thức gốc (bài báo/lõi): điểm = trung bình(P+) − trung bình(P−); đóng góp mỗi tin = s/N.",
        "- Công thức mới: S_danh mục = Σ vốn_k × clip(micro_k + β_k × M, −1, 1); micro_k và M = Σ w·s / (Σ w + κ), w = 0.5^(giờ/H) × |P+ − P−|.",
        "",
    ]
    if "validation" in r:
        v = r["validation"]
        lines += [
            "## 0. Kiểm chứng model: lần chạy này cho ra đúng số như máy của bạn",
            "",
            f"Đối chiếu {v['headlines']} tiêu đề RSS thật trong `{v['reference_file']}` (revision `{v['reference_revision'][:10]}…` trên máy bạn). Sai khác tuyệt đối lớn nhất: **{v['max_abs_diff']:.2e}**.",
            "",
            "| Tiêu đề (RSS thật) | P+ máy bạn | P+ lần này | P− máy bạn | P− lần này | P0 máy bạn | P0 lần này |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in v["rows"]:
            a, b = row["reference"], row["this_run"]
            lines.append(f"| {row['title'][:80].replace('|', '/')} | {a['positive']:.4f} | {b['positive']:.4f} | {a['negative']:.4f} | {b['negative']:.4f} | {a['neutral']:.4f} | {b['neutral']:.4f} |")
        lines.append("")

    lines += [
        "## 1. Bảng chính (Bộ A — kịch bản theo đúng cấu trúc danh mục của bài báo)",
        "",
        "Danh mục: COMI 70% vốn (β 1.2) · ETEL 20% (β 0.6) · FWRY 10% (β 1.0). 4 tin vĩ mô + 2 tin mỗi mã như hình *Portfolio Sentiment Data Flow* của bài báo.",
        "Tiêu đề do nhóm soạn để kiểm thử; **3 xác suất là FinBERT chấm thật**. Cộng dọc hai cột đóng góp = điểm danh mục của từng phương pháp.",
        "",
        md_headline_table(sc),
        "",
        "## 2. Điểm theo từng mã (Bộ A)",
        "",
        md_holding_table(sc),
        "",
        md_evidence_table(sc),
        "",
        "## 3. Tóm tắt: gỡ từng lớp (Bộ A)",
        "",
        md_summary_table(sc),
        "",
    ]
    if "real_rss" in r:
        rr = r["real_rss"]
        lines += [
            "## 4. Kiểm tra trên tin THẬT (Bộ B — RSS máy bạn thu thập, danh mục 5 mã)",
            "",
            f"Tuổi tin tính đến lúc máy bạn chạy ({rr['now_utc']}). Tỷ trọng vốn: COMI 40% · ETEL 20% · FWRY 15% · ADIB 15% · EFIH 10% (giả định minh họa). ETEL và FWRY không có tin riêng, nên điểm của chúng chỉ đến từ β × vĩ mô.",
            "",
            md_headline_table(rr, show_source=True),
            "",
            md_holding_table(rr),
            "",
            md_evidence_table(rr),
            "",
        ]
        if rr["full"]["warnings"]:
            lines += ["Cảnh báo do code tự sinh:", ""] + [f"- {w}" for w in rr["full"]["warnings"]] + [""]

    lines += [
        "## 5. Có softmax vs không softmax (logits thật của FinBERT)",
        "",
        "| Tiêu đề | Logit Pos | Logit Neg | Logit Neu | Sigmoid Pos | Sigmoid Neg | Sigmoid Neu | Tổng sigmoid | Softmax Pos | Softmax Neg | Softmax Neu | Tổng softmax |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in r["softmax_demo"]["chosen"]:
        lg, sg, sm = c["logits"], c["sigmoid"], c["softmax"]
        lines.append(
            f"| {c['title'][:80]} | {lg['positive']:+.2f} | {lg['negative']:+.2f} | {lg['neutral']:+.2f} | {sg['positive']:.1%} | {sg['negative']:.1%} | {sg['neutral']:.1%} | **{sum(sg.values()):.1%}** | {sm['positive']:.1%} | {sm['negative']:.1%} | {sm['neutral']:.1%} | **{sum(sm.values()):.1%}** |"
        )
    lines += [
        "",
        "## 6. Trọng số thời gian tại các mốc",
        "",
        "| Số giờ đã đăng | 1h | 6h | 12h | 24h | 48h |",
        "|---|---|---|---|---|---|",
    ]
    for kind, label in (("micro", "Tin riêng mã"), ("macro", "Tin vĩ mô")):
        h = DEFAULT_HALF_LIFE_HOURS[kind]
        lines.append(f"| {label} (H = {h:g}h) | " + " | ".join(f"{time_decay_weight(x, h):.3f}" for x in DECAY_MARKERS) + " |")
    lines.append("| Bài báo gốc (không suy giảm) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |")

    lat = r["latency"]
    lines += [
        "",
        f"## 7. Latency: gọi trực tiếp vs TTL cache (trung vị {lat['repeats']} lần chạy)",
        "",
        "| # | Request | Số tiêu đề | Gọi trực tiếp (ms) | Có cache (ms) | Tiêu đề lấy từ cache | Tiêu đề phải chấm model |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in lat["trace"]:
        lines.append(f"| {t['request']} | {t['label']} | {t['headlines']} | {t['direct_ms']:.2f} | {t['cached_ms']:.3f} | {t['cache_hits']} | {t['model_calls']} |")
    names = list(lat["summary"])
    d, c = lat["summary"][names[0]], lat["summary"][names[1]]
    hf = hf_http_requests(lat["trace"])
    lines += [
        "",
        "| Chỉ số | Gọi trực tiếp (bài báo) | Có TTL cache (code mới) | Chênh lệch |",
        "|---|---|---|---|",
        f"| Latency trung bình / request | {d['mean_ms']:.2f} ms | {c['mean_ms']:.2f} ms | nhanh hơn {d['mean_ms'] / c['mean_ms']:.1f} lần |",
        f"| Latency p95 | {d['p95_ms']:.2f} ms | {c['p95_ms']:.2f} ms | |",
        f"| Tổng thời gian 12 request | {d['total_ms']:.1f} ms | {c['total_ms']:.1f} ms | |",
        f"| Số lượt tiêu đề đưa vào model | {d['model_calls']} | {c['model_calls']} | giảm {1 - c['model_calls'] / d['model_calls']:.0%} |",
        f"| Request HTTP tới HF API, gửi 1 tiêu đề/request (code gốc) | {hf['one_per_headline_direct']} | {hf['one_per_headline_cached']} | giảm {1 - hf['one_per_headline_cached'] / hf['one_per_headline_direct']:.0%} |",
        f"| Request HTTP tới HF API, gửi theo lô ≤{hf['batch_size']} tiêu đề (code mới) | {hf['batched_direct']} | {hf['batched_cached']} | giảm {1 - hf['batched_cached'] / hf['batched_direct']:.0%} |",
        "",
        f"Code gốc so với code mới đầy đủ (gửi theo lô + cache): {hf['one_per_headline_direct']} → {hf['batched_cached']} request HTTP, giảm {1 - hf['batched_cached'] / hf['one_per_headline_direct']:.0%}.",
        "",
        "Ghi chú: latency đo trên FinBERT local CPU (provider mặc định của code). Lần chạy này không gọi Hugging Face Inference API nên không đo độ trễ mạng; hai dòng request HTTP được đếm từ chuỗi 12 request ở trên theo cách code gửi đi. "
        "Cách gửi theo lô đã được kiểm bằng test giả lập HF (16 tiêu đề → 2 request). Nếu HF từ chối lô, code tự quay về 1 tiêu đề/request và con số sẽ như dòng \"code gốc\".",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
