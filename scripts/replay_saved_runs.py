"""Tính lại tab "Danh mục theo vốn" từ các phản hồi tab 1 đã lưu (không cần mạng, không cần model).

Dùng cho phép thử T3 sơ bộ: lấy đúng các tiêu đề và xác suất FinBERT mà web đã trả ở tab 1 cho từng mã
(ví dụ `docs/du_lieu_03-11/*-web.json`, lượt Windows 03/11/2026 22:29 giờ VN), rồi:
  - áp luật lọc tin riêng (RULES_VERSION) lên tin riêng của từng mã (tính tuổi tin theo giờ chạy của lượt đó),
  - áp luật tin vĩ mô (chỉ giữ tin về kinh tế hay thị trường) lên tin vĩ mô,
  - tính điểm mã, độ phủ, đóng góp từ tin đã chấm, điểm vĩ mô,
  - dựng điểm "cách bài báo" theo đúng cách chọn của tab danh mục (2 tin mới nhất mỗi mã + 4 tin vĩ mô).

Giới hạn: file tab 1 chỉ chứa các tin mà bộ lọc CŨ đã giữ từ truy vấn bậc 1, nên ở đây luật mới chỉ có thể
loại bớt; không thấy được tin bộ lọc cũ đã bỏ, cũng không có kết quả truy vấn bậc 2 hay truy vấn tin kinh tế
mà web phần C sẽ gọi thêm. Muốn có đủ ứng viên, dùng scripts/capture_candidates.py.

Chạy:
    python -m scripts.replay_saved_runs docs/du_lieu_03-11 --positions COMI:50,ETEL:30,FWRY:20 --out artifacts/replay_03-11.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.providers.news import NewsItem, company_aliases, deduplicate
from backend.schemas import normalize_symbol
from backend.services.sentiment import aggregate_probabilities
from backend.upgrades.coverage import CoverageConfig, HoldingScore, group_signal, summarize_portfolio
from backend.upgrades.relevance import RULES_VERSION, screen, screen_macro


def utf8_console() -> None:
    """Bản 3.2: trên Windows, khi đầu ra bị chuyển hướng (pipe, file, công cụ chạy lệnh), Python ghi bằng bảng mã
    cp1252 và chết ở chữ Việt đầu tiên (UnicodeEncodeError). Đổi stdout và stderr sang UTF-8 để lệnh chạy được
    nguyên văn, không cần thêm -X utf8. Chỉ đổi cách in chữ, không đổi phép kiểm hay số nào."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


FIELDS = ("title", "url", "published_at", "source", "kind", "symbol", "description")


def load_runs(folder: str | Path) -> dict[str, dict[str, Any]]:
    runs = {}
    for path in sorted(Path(folder).glob("*-web.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        runs[data["symbols"][0]] = data
    return runs


def replay(runs: dict[str, dict[str, Any]], positions: list[tuple[str, float]], config: CoverageConfig | None = None) -> dict[str, Any]:
    config = config or CoverageConfig()
    holdings, details, article_micro, macro_rows = [], [], [], {}
    for symbol, weight in positions:
        run = runs.get(symbol)
        rows = [] if run is None else run["headlines"]
        now = datetime.fromisoformat(run["data_freshness"]["requested_at_utc"]) if run else None
        micro = [r for r in rows if r.get("kind") == "micro"]
        for r in rows:
            if r.get("kind") == "macro":
                macro_rows.setdefault(r["title"], r)
        kept, rejected = [], []
        verdicts = screen([NewsItem(**{k: r.get(k) for k in FIELDS}) for r in micro], company_aliases(symbol), now=now, lookback_days=config.lookback_days)
        for r, verdict in zip(micro, verdicts, strict=True):
            (kept if verdict.keep else rejected).append((r, verdict))
        kept_rows = [r for r, _ in kept][: config.max_headlines_per_holding]
        signal = group_signal(kept_rows, kind="micro", config=config, now=now) if now else None
        holdings.append(HoldingScore(symbol, weight, signal))
        details.append({
            "symbol": symbol, "found": run is not None, "old_kept": len(micro), "kept": kept_rows,
            "rejected": [(r["title"], v.reason) for r, v in rejected],
            "tab1": None if run is None else {"score": run["score"], "sentiment": run["sentiment"], "n": run["news_count"]},
            "run_at": now,
        })
        article_micro.extend(micro[:2])  # tab 1 đã sắp mới nhất trước; [:2] = collect_stock(limit=2) trên cùng tập
    portfolio = summarize_portfolio(holdings, config)
    macro = sorted(macro_rows.values(), key=lambda r: r.get("published_at") or "", reverse=True)
    times = [d["run_at"] for d in details if d["run_at"]]
    macro_kept, macro_rejected = [], []
    macro_verdicts = screen_macro([NewsItem(**{k: r.get(k) for k in FIELDS}) for r in macro], now=max(times), lookback_days=config.lookback_days)
    for r, verdict in zip(macro, macro_verdicts, strict=True):
        (macro_kept.append(r) if verdict.keep else macro_rejected.append((r["title"], verdict.reason)))
    macro_signal = group_signal(macro_kept[: config.macro_limit], kind="macro", config=config, now=max(times)) if macro_kept else None
    items = [NewsItem(**{k: r.get(k) for k in FIELDS}) for r in article_micro + macro[:4]]
    by_title = {r["title"]: r for r in article_micro + macro[:4]}
    merged = sorted(deduplicate(items), key=lambda i: (1 if i.published_at else 0, i.published_at or ""), reverse=True)[:14]
    probs, sentiment, score = aggregate_probabilities([by_title[i.title]["probabilities"] for i in merged]) if merged else (None, None, None)
    return {
        "rules": RULES_VERSION,
        "holdings": holdings,
        "details": details,
        "portfolio": portfolio,
        "macro": macro_signal,
        "macro_rejected": macro_rejected,
        "article": {"score": score, "sentiment": sentiment, "n": len(merged)},
    }


def render(result: dict[str, Any], source: str) -> str:
    p = result["portfolio"]
    num = lambda x: "—" if x is None else f"{x:+.3f}"
    lines = [
        f"# Tính lại tab nâng cấp từ lượt đã lưu ({source})",
        "",
        f"Luật lọc {result['rules']}. Chỉ là số đo trên một lượt; không có ngưỡng đạt hay không đạt.",
        "",
        "| Mã | Vốn | Tab 1 (cách bài báo, một mã) | Tin bộ lọc cũ giữ | Tin luật mới giữ | Điểm tin riêng | Nhãn tin riêng | Tiêu đề theo nhãn (tích cực · trung tính · tiêu cực) | Đóng góp |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for h, d in zip(result["holdings"], result["details"], strict=True):
        tab1 = d["tab1"]
        tab1_cell = "—" if not tab1 else "{} {} ({} tin)".format(tab1["sentiment"], num(tab1["score"]), tab1["n"])
        label_cell = h.label if h.has_news else "không tìm thấy tin riêng"
        own_score = num(h.signal["score"] if h.signal else None)
        counts = h.signal["label_counts"] if h.signal else None
        counts_cell = "—" if not counts else f"{counts['Bullish']} · {counts['Neutral']} · {counts['Bearish']}"
        lines.append(
            f"| {h.symbol.removesuffix('.EGX')} | {h.w:.0%} | {tab1_cell} | {d['old_kept']} | {len(d['kept'])} | {own_score} | "
            f"{label_cell} | {counts_cell} | {num(h.contribution)} |"
        )
    differ = sum(1 for h, d in zip(result["holdings"], result["details"]) if d["tab1"] and d["tab1"]["sentiment"] != (h.label if h.has_news else None))
    lines += [
        "",
        f"- Số mã có nhãn tab 1 khác nhãn tin riêng (tính cả mã không tìm thấy tin riêng): {differ}/{sum(1 for d in result['details'] if d['tab1'])}",
        f"- Độ phủ tin: {p['coverage']:.0%} vốn",
        f"- Điểm tin doanh nghiệp S (trên phần vốn có tin): {num(p['score'])}",
        "- Chỉ tổng hợp trên tin đã chấm; không suy diễn điểm cho mã chưa có dữ liệu.",
        f"- {p['direction_text']}",
        f"- Vốn theo nhãn tin riêng: " + ", ".join(f"{k} {v:.0%}" for k, v in p["capital_by_label"].items()),
        *([f"- {p['capital_by_label_note']}"] if p.get("capital_by_label_note") else []),
        f"- Điểm vĩ mô M (chỉ tin kinh tế hay thị trường, không cộng vào S): {num(result['macro']['score'] if result['macro'] else None)} ({result['macro']['n'] if result['macro'] else 0} tin; {len(result['macro_rejected'])} tin vĩ mô bị loại)",
        f"- Cách bài báo (gộp chung, {result['article']['n']} tiêu đề): {num(result['article']['score'])} {result['article']['sentiment'] or ''}",
        "",
        "Tin bị luật mới loại:",
        "",
    ]
    for d in result["details"]:
        for title, reason in d["rejected"]:
            lines.append(f"- {d['symbol'].removesuffix('.EGX')}: {title} → {reason}")
    for title, reason in result["macro_rejected"]:
        lines.append(f"- Vĩ mô: {title} → {reason}")
    if not any(d["rejected"] for d in result["details"]) and not result["macro_rejected"]:
        lines.append("- không có")
    return "\n".join(lines) + "\n"


def main() -> None:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder")
    parser.add_argument("--positions", default="COMI:20,ETEL:20,FWRY:20,ADIB:20,EFIH:20")
    parser.add_argument("--out")
    args = parser.parse_args()
    positions = []
    for part in args.positions.split(","):
        symbol, _, weight = part.partition(":")
        positions.append((normalize_symbol(symbol), float(weight)))
    text = render(replay(load_runs(args.folder), positions), args.folder)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
