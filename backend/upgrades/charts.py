"""Module 3b — Tự động vẽ và lưu 3 biểu đồ PNG từ dữ liệu chạy thật.

Biểu đồ 1: Có softmax vs không softmax (lỗi kiểu "91% Bull / 91% Bear") + đường Time-Decay.
Biểu đồ 2: Điểm danh mục — phương pháp gốc của bài báo vs code cải tiến (cùng tập tin).
Biểu đồ 3: Độ trễ (ms) — luồng gọi trực tiếp vs luồng có TTL cache.
Biểu đồ 4: Độ chính xác — FinBERT vs model review phim trên tin tài chính có nhãn (scripts/evaluate_finbert.py).

Chỉ dùng matplotlib (backend "Agg" — chạy được trên server/Colab không có màn hình).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from backend.upgrades.time_confidence import display_label  # noqa: E402

# Bảng màu đã kiểm định (dataviz reference palette): xanh = cải tiến/đúng, cam = gốc/sai.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
VIOLET = "#6250d6"
GRAY = "#898781"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
BEAR = "#e34948"


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "axes.edgecolor": AXIS,
            "axes.linewidth": 0.8,
            "axes.labelcolor": INK_2,
            "axes.titlesize": 12.5,
            "axes.titleweight": "bold",
            "axes.titlecolor": INK,
            "axes.titlelocation": "left",
            "axes.titlepad": 12,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "grid.linestyle": "-",
            "axes.axisbelow": True,
            "legend.frameon": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _pct(value: float, _pos: Any = None) -> str:
    return f"{value * 100:.0f}%"


# ---------------------------------------------------------------------------
# Biểu đồ 1
# ---------------------------------------------------------------------------
def chart_softmax_and_decay(
    softmax_cases: Sequence[Mapping[str, Any]],
    decay_rows: Mapping[str, Sequence[Mapping[str, float]]],
    marker_hours: Sequence[float],
    path: str | Path,
) -> Path:
    """softmax_cases: [{title, logits{pos,neg,neu}, sigmoid{...}, softmax{...}}] (tối đa 2)
    decay_rows: {"micro (H=12h)": [{age_hours, time_weight}...], "macro (H=24h)": [...]}
    """
    _style()
    cases = list(softmax_cases)[:2]
    fig = plt.figure(figsize=(15, 7.2))
    grid = fig.add_gridspec(len(cases), 2, width_ratios=[1.15, 1], hspace=0.95, wspace=0.16)

    labels = ["positive", "negative", "neutral"]
    shown = ["Positive\n(Bull)", "Negative\n(Bear)", "Neutral"]
    handles: list[Any] = []
    for row, case in enumerate(cases):
        ax = fig.add_subplot(grid[row, 0])
        x = range(len(labels))
        width = 0.36
        no_soft = [case["sigmoid"][k] for k in labels]
        soft = [case["softmax"][k] for k in labels]
        bars_a = ax.bar([i - width / 2 - 0.01 for i in x], no_soft, width, color=ORANGE, label="Không softmax (sigmoid từng nhãn)")
        bars_b = ax.bar([i + width / 2 + 0.01 for i in x], soft, width, color=BLUE, label="Có softmax (cách của FinBERT)")
        for bars in (bars_a, bars_b):
            for bar in bars:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.025, f"{bar.get_height() * 100:.0f}%", ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_xticks(list(x), shown)
        ax.set_ylim(0, 1.18)
        ax.yaxis.set_major_formatter(FuncFormatter(_pct))
        ax.grid(axis="x", visible=False)
        title = case["title"] if len(case["title"]) <= 70 else case["title"][:67] + "…"
        source = f"  ({case['source']})" if case.get("source") else ""
        ax.set_title(
            f"“{title}”{source}\nCộng 3 nhãn: không softmax = {sum(no_soft) * 100:.0f}%   ·   có softmax = {sum(soft) * 100:.0f}%",
            fontsize=10,
            fontweight="normal",
            color=INK,
            linespacing=1.5,
        )
        if row == 0:
            handles = [bars_a, bars_b]

    ax = fig.add_subplot(grid[:, 1])
    colors = [BLUE, VIOLET]
    for (name, rows), color in zip(decay_rows.items(), colors):
        xs = [r["age_hours"] for r in rows]
        ys = [r["time_weight"] for r in rows]
        ax.plot(xs, ys, color=color, linewidth=2, label=name)
        marks = [r for r in rows if r["age_hours"] in set(marker_hours)]
        ax.scatter([r["age_hours"] for r in marks], [r["time_weight"] for r in marks], s=46, color=color, edgecolor=SURFACE, linewidth=2, zorder=3)
        # Đường lồi đi xuống: phía trên-phải và dưới-trái của mỗi điểm luôn trống.
        upper = color == VIOLET
        for r in marks:
            ax.annotate(
                f"{r['time_weight']:.2f}",
                (r["age_hours"], r["time_weight"]),
                textcoords="offset points",
                xytext=(5, 5) if upper else (-6, -4),
                ha="left" if upper else "right",
                va="bottom" if upper else "top",
                fontsize=9,
                color=INK,
            )
    ax.set_xticks(list(marker_hours))
    ax.set_xlabel("Số giờ kể từ lúc tin được đăng")
    ax.set_ylabel("Trọng số thời gian w_time")
    ax.set_ylim(0, 1.08)
    ax.set_xlim(-3, max(marker_hours) + 3)
    ax.legend(loc="upper right", fontsize=9.5)
    ax.set_title("B. Time-Decay: tin càng cũ, phiếu bầu càng nhẹ\nw = 0.5^(giờ / H)", linespacing=1.5)

    fig.text(0.012, 0.985, "Biểu đồ 1 — A. Softmax giữ tổng xác suất = 100%  ·  B. Đường suy giảm theo thời gian", fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.012, 0.945, "A: logits thật của FinBERT chấm trong lần chạy này, nguồn tiêu đề ghi trong ngoặc. B: công thức Module 1 tại 1h, 6h, 12h, 24h, 48h.", fontsize=10, color=INK_2, va="top")
    fig.legend(handles, [h.get_label() for h in handles], loc="upper left", bbox_to_anchor=(0.045, 0.915), ncol=2, fontsize=9.5)
    fig.subplots_adjust(left=0.05, right=0.985, top=0.76, bottom=0.09)
    path = Path(path)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Biểu đồ 2
# ---------------------------------------------------------------------------
def chart_portfolio_comparison(
    steps: Sequence[Mapping[str, Any]],
    attribution: Sequence[Mapping[str, Any]],
    path: str | Path,
    subtitle: str,
) -> Path:
    """steps: [{name, score, sentiment}] — gốc → +Module 1 → +Module 1+2.
    attribution: [{name, article, upgraded}] — đóng góp vào điểm danh mục theo nhóm (mã / vĩ mô).
    """
    _style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.8), gridspec_kw={"width_ratios": [1, 1.2], "wspace": 0.5})

    names = [s["name"] for s in steps]
    scores = [s["score"] for s in steps]
    colors = [ORANGE] + [BLUE] * (len(steps) - 1)
    bars = ax1.bar(names, scores, width=0.5, color=colors)
    ax1.axhline(0, color=AXIS, linewidth=1)
    lim = max(0.6, max(abs(v) for v in scores) + 0.2)
    ax1.set_ylim(-lim, lim)
    for bar, step in zip(bars, steps):
        value = bar.get_height()
        offset = 0.03 if value >= 0 else -0.03
        ax1.text(bar.get_x() + bar.get_width() / 2, value + offset, f"{value:+.3f}\n{display_label(step['sentiment'])}", ha="center", va="bottom" if value >= 0 else "top", fontsize=10, color=INK, fontweight="bold")
    ax1.axhspan(-0.15, 0.15, color=GRID, alpha=0.5, zorder=0)
    ax1.set_xlabel("Dải xám = vùng Neutral (−0.15 đến +0.15)", fontsize=9.5)
    ax1.set_ylabel("Điểm sentiment danh mục  (−1 = rất xấu, +1 = rất tốt)")
    ax1.grid(axis="x", visible=False)
    ax1.set_title("A. Cùng 10 tiêu đề, 3 cách tính")

    groups = [a["name"] for a in attribution]
    y = list(range(len(groups)))
    h = 0.36
    ax2.barh([i - h / 2 - 0.01 for i in y], [a["article"] for a in attribution], h, color=ORANGE, label="Bài báo gốc (trung bình phẳng)")
    ax2.barh([i + h / 2 + 0.01 for i in y], [a["upgraded"] for a in attribution], h, color=BLUE, label="Code cải tiến (vốn × β × thời gian × độ rõ)")
    for i, a in enumerate(attribution):
        for value, dy in ((a["article"], -h / 2 - 0.01), (a["upgraded"], h / 2 + 0.01)):
            ax2.text(value + (0.006 if value >= 0 else -0.006), i + dy, f"{value:+.3f}", va="center", ha="left" if value >= 0 else "right", fontsize=9, color=INK)
    ax2.axvline(0, color=AXIS, linewidth=1)
    ax2.set_yticks(y, groups)
    ax2.invert_yaxis()
    span = max(abs(v) for a in attribution for v in (a["article"], a["upgraded"])) + 0.12
    ax2.set_xlim(-span, span)
    ax2.set_xlabel("Đóng góp vào điểm danh mục (cộng dọc = điểm ở hình A)")
    ax2.grid(axis="y", visible=False)
    ax2.set_title("B. Điểm danh mục đến từ đâu?")

    fig.text(0.012, 0.985, "Biểu đồ 2 — Portfolio Sentiment: phương pháp của bài báo vs code cải tiến", fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.012, 0.94, subtitle, fontsize=10, color=INK_2, va="top")
    fig.legend(*ax2.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(0.045, 0.905), ncol=2, fontsize=9.5)
    fig.subplots_adjust(left=0.06, right=0.985, top=0.79, bottom=0.12)
    path = Path(path)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Biểu đồ 3
# ---------------------------------------------------------------------------
def chart_latency(
    trace: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Mapping[str, float]],
    path: str | Path,
    subtitle: str,
) -> Path:
    """trace: [{request, label, direct_ms, cached_ms, cache_hits, model_calls}]
    summary: {"Gọi trực tiếp (bài báo)": {mean_ms, p95_ms, model_calls}, "Có TTL cache (mới)": {...}}
    """
    _style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7.4), gridspec_kw={"width_ratios": [1.6, 1], "wspace": 0.22})

    xs = [t["request"] for t in trace]
    ax1.plot(xs, [t["direct_ms"] for t in trace], color=ORANGE, linewidth=2, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="Gọi trực tiếp như bài báo (chấm lại mọi tiêu đề)")
    ax1.plot(xs, [t["cached_ms"] for t in trace], color=BLUE, linewidth=2, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="Có TTL cache (chỉ chấm tiêu đề mới)")
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:g} ms"))
    ax1.set_xticks(xs, [t["label"] for t in trace], rotation=45, ha="right", fontsize=8.5)
    ax1.set_ylabel("Thời gian phản hồi mỗi request (ms, thang log)")
    ax1.set_title("A. Độ trễ từng request trong cùng một chuỗi truy cập")
    cached = [t["cached_ms"] for t in trace]
    for i, t in enumerate(trace):
        if t["model_calls"] <= 0:
            continue
        left = cached[i - 1] if i > 0 else 0.0
        right = cached[i + 1] if i + 1 < len(trace) else 0.0
        # Đỉnh nhọn (hai bên thấp hơn): ghi nhãn sang phải, nơi đường đang rơi xuống; còn lại ghi bên dưới.
        peak = i > 0 and t["cached_ms"] > left and t["cached_ms"] > right
        ax1.annotate(
            f"{t['model_calls']} tin mới",
            (t["request"], t["cached_ms"]),
            textcoords="offset points",
            xytext=(8, 0) if peak else (0, -16),
            ha="left" if peak else "center",
            va="center" if peak else "baseline",
            fontsize=8.5,
            color=INK_2,
        )

    names = list(summary)
    means = [summary[n]["mean_ms"] for n in names]
    bars = ax2.bar(names, means, width=0.45, color=[ORANGE, BLUE])
    for bar, name in zip(bars, names):
        s = summary[name]
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(means) * 0.03,
            f"TB {s['mean_ms']:.1f} ms\np95 {s['p95_ms']:.1f} ms\n{int(s['model_calls'])} lượt chấm model",
            ha="center",
            va="bottom",
            fontsize=9.5,
            color=INK,
        )
    ax2.set_ylim(0, max(means) * 1.4)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:g} ms"))
    ax2.set_ylabel("Thời gian trung bình mỗi request (ms)")
    ax2.grid(axis="x", visible=False)
    ax2.set_title("B. Trung bình cả chuỗi")

    fig.text(0.012, 0.985, "Biểu đồ 3 — Latency: luồng gọi trực tiếp vs luồng có TTL cache", fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.012, 0.945, subtitle, fontsize=10, color=INK_2, va="top")
    fig.legend(*ax1.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(0.06, 0.915), ncol=2, fontsize=9.5)
    fig.subplots_adjust(left=0.07, right=0.985, top=0.8, bottom=0.22)
    path = Path(path)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Biểu đồ 4
# ---------------------------------------------------------------------------
def chart_accuracy_comparison(evaluation: Mapping[str, Any], path: str | Path, subtitle: str) -> Path:
    """evaluation: kết quả của scripts.evaluate_finbert.evaluate()."""
    _style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.8), gridspec_kw={"width_ratios": [1.25, 1], "wspace": 0.3})

    d = evaluation["directional_subset"]
    f, g = d["finbert"], d["general"]
    groups = ["Độ chính xác\nchung", "Bắt đúng\ntin Bullish", "Bắt đúng\ntin Bearish"]
    fin_vals = [f["accuracy"], f["per_class"]["positive"]["recall"], f["per_class"]["negative"]["recall"]]
    gen_vals = [g["accuracy"], g["per_class"]["positive"]["recall"], g["per_class"]["negative"]["recall"]]
    x = list(range(len(groups)))
    width = 0.36
    bars_f = ax1.bar([i - width / 2 - 0.01 for i in x], fin_vals, width, color=BLUE, label="FinBERT (học từ tin tài chính)")
    bars_g = ax1.bar([i + width / 2 + 0.01 for i in x], gen_vals, width, color=ORANGE, label="Model review phim SST-2 (model thông thường)")
    for bars in (bars_f, bars_g):
        for bar in bars:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.015, f"{bar.get_height() * 100:.1f}%", ha="center", va="bottom", fontsize=9.5, color=INK)
    baseline = f["majority_baseline_accuracy"]
    base_line = ax1.axhline(baseline, xmax=0.36, color=GRAY, linewidth=1.4, linestyle=(0, (4, 3)), label=f"Đoán bừa theo nhãn phổ biến nhất ({baseline * 100:.1f}%)")
    ax1.set_xticks(x, groups)
    ax1.set_ylim(0, 1.12)
    ax1.yaxis.set_major_formatter(FuncFormatter(_pct))
    ax1.grid(axis="x", visible=False)
    t = d["mcnemar"]
    p_text = "p < 0.001" if t["p_value"] < 0.001 else f"p = {t['p_value']:.3f}"
    ax1.set_title(f"A. {d['n']} tin có chiều rõ (Bullish / Bearish)\nMcNemar: {t['only_first_correct']} tin chỉ FinBERT đúng, {t['only_second_correct']} tin chỉ model review phim đúng, {p_text}", linespacing=1.5)

    three = evaluation["finbert_three_class"]
    labels = ["positive", "negative", "neutral"]
    names = ["Bullish", "Bearish", "Neutral"]
    matrix = [[three["confusion"][gold][pred] for pred in labels] for gold in labels]
    shares = [[value / max(1, sum(row)) for value in row] for row in matrix]
    ax2.imshow(shares, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            dark = shares[i][j] > 0.55
            ax2.text(j, i, f"{value}\n{shares[i][j] * 100:.0f}%", ha="center", va="center", fontsize=10, color=SURFACE if dark else INK)
    ax2.set_xticks(range(3), names)
    ax2.set_yticks(range(3), names)
    neu = evaluation["neutral_subset"]
    ax2.set_xlabel(f"FinBERT đoán\n(model review phim không có nhãn Neutral: cả {neu['n']} tin trung tính bị ép thành Bull/Bear)", fontsize=9.5)
    ax2.set_ylabel("Nhãn đúng")
    ax2.grid(False)
    for spine in ax2.spines.values():
        spine.set_visible(False)
    ax2.set_title(f"B. FinBERT trên đủ 3 nhãn (có Neutral)\nđúng {three['accuracy'] * 100:.1f}% của {three['n']} tin; ô = số tin và % theo hàng", linespacing=1.5)

    fig.text(0.012, 0.985, "Biểu đồ 4 — Vì sao phải dùng FinBERT: đọc tin tài chính đúng hơn model sentiment thông thường", fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.012, 0.94, subtitle, fontsize=10, color=INK_2, va="top")
    handles = [bars_f, bars_g, base_line]
    fig.legend(handles, [h.get_label() for h in handles], loc="upper left", bbox_to_anchor=(0.045, 0.905), ncol=3, fontsize=9.5)
    fig.subplots_adjust(left=0.05, right=0.985, top=0.74, bottom=0.13)
    path = Path(path)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Biểu đồ 5 — kiểm chứng trọng số độ rõ của Module 1 bằng tin có nhãn
# ---------------------------------------------------------------------------
def chart_confidence_check(confidence: Mapping[str, Any], path: str | Path, subtitle: str) -> Path:
    """confidence: evaluation["confidence"] của scripts.evaluate_finbert."""
    _style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.8), gridspec_kw={"width_ratios": [1.3, 1], "wspace": 0.28})

    buckets = list(confidence["buckets"])
    names = [f"{b['low']:.1f}–{b['high']:.1f}\n({b['n']} tin)" for b in buckets]
    acc = [b["direction_accuracy"] or 0.0 for b in buckets]
    neutral = [b["neutral_share"] or 0.0 for b in buckets]
    x = list(range(len(buckets)))
    width = 0.36
    neutral_gray = "#b4b2a9"
    bars_a = ax1.bar([i - width / 2 - 0.01 for i in x], acc, width, color=BLUE, label="Tỉ lệ đoán đúng chiều (tính trên tin có chiều rõ)")
    bars_n = ax1.bar([i + width / 2 + 0.01 for i in x], neutral, width, color=neutral_gray, label="Tỉ lệ tin thực chất trung tính")
    for bars in (bars_a, bars_n):
        for bar in bars:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.015, f"{bar.get_height() * 100:.0f}%", ha="center", va="bottom", fontsize=9.5, color=INK)
    ax1.set_xticks(x, names)
    ax1.set_xlabel("Độ rõ của FinBERT |P(Positive) − P(Negative)| = trọng số w_conf của Module 1")
    ax1.set_ylim(0, 1.08)
    ax1.yaxis.set_major_formatter(FuncFormatter(_pct))
    ax1.grid(axis="x", visible=False)
    ax1.set_title("A. Tin FinBERT chấm càng rõ thì càng hay đúng chiều,\nvà càng ít khả năng là tin trung tính", linespacing=1.5, pad=30)
    ax1.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, fontsize=9.5, frameon=False, borderaxespad=0.3)

    schemes = [("Bài báo\n(mỗi tin 1 phiếu)", confidence["vote_share_equal"]), ("Module 1\n(phiếu = độ rõ)", confidence["vote_share_confidence"])]
    parts = [("right_direction", "Tin đúng chiều", BLUE), ("wrong_direction", "Tin sai chiều", ORANGE), ("neutral_news", "Tin trung tính", neutral_gray)]
    for i, (_label, shares) in enumerate(schemes):
        bottom = 0.0
        for key, label, color in parts:
            value = shares[key]
            ax2.bar(i, value, 0.5, bottom=bottom, color=color, edgecolor=SURFACE, linewidth=2, label=label if i == 0 else None)
            if value >= 0.04:
                ax2.text(i, bottom + value / 2, f"{value * 100:.1f}%", ha="center", va="center", fontsize=10, color=SURFACE if color in (BLUE, ORANGE) else INK)
            bottom += value
    ax2.set_xticks(range(len(schemes)), [s[0] for s in schemes])
    ax2.set_ylim(0, 1.0)
    ax2.yaxis.set_major_formatter(FuncFormatter(_pct))
    ax2.grid(axis="x", visible=False)
    ax2.set_title("B. Khi lấy trung bình, phần \"phiếu\" rơi vào loại tin nào?\n(mỗi cột cộng lại 100%)", linespacing=1.5, pad=30)
    ax2.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=3, fontsize=9.5, frameon=False, borderaxespad=0.3)

    fig.text(0.012, 0.985, "Biểu đồ 5 — Kiểm chứng Module 1: cho tin rõ nhiều phiếu hơn có cơ sở từ dữ liệu", fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.012, 0.94, subtitle, fontsize=10, color=INK_2, va="top")
    fig.subplots_adjust(left=0.05, right=0.985, top=0.74, bottom=0.14)
    path = Path(path)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path
