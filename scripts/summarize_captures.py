"""Tóm tắt nhiều lượt thu tin (scripts/capture_candidates.py): số tin và độ phủ theo ngày. Chỉ báo số đo.

Cho mỗi lượt và mỗi mã: số ứng viên, số tin bộ lọc cũ giữ, số tin luật mới giữ, số tin web sẽ chấm (n_i).
Nếu cho `--positions`, tính thêm độ phủ C của danh mục đó ở từng lượt (C = tổng phần vốn của các mã có n_i ≥ 1),
Phạm vi vốn được thống kê để mô tả dữ liệu đã thu, không suy diễn tin chưa có.

Chạy:
    python -m scripts.summarize_captures captures/* --positions COMI:50,ETEL:30,FWRY:20 --out captures/TOM_TAT.md
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from backend.schemas import normalize_symbol


def _true(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def summarize(capture_dirs: list[str | Path], positions: dict[str, float] | None = None) -> dict[str, Any]:
    captures = []
    for folder in sorted(capture_dirs, key=str):
        path = Path(folder) / "capture.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        per_symbol: dict[str, dict[str, int]] = {}
        for symbol in data["meta"]["symbols"]:
            rows = [r for r in data["rows"] if r.get("kind") == "micro" and r.get("symbol") == symbol]
            per_symbol[symbol] = {
                "candidates": len(rows),
                "old_filter_keep": sum(_true(r.get("old_filter_keep")) for r in rows),
                "new_keep": sum(_true(r.get("new_keep")) for r in rows),
                "web_scored": sum(_true(r.get("web_scored")) for r in rows),
            }
        coverage = None
        if positions:
            total = sum(positions.values())
            coverage = sum(w for s, w in positions.items() if per_symbol.get(s, {}).get("web_scored", 0) >= 1) / total
        captures.append({"capture_id": data["meta"]["capture_id"], "runtime": data["meta"].get("runtime"), "per_symbol": per_symbol, "coverage": coverage})

    symbols = sorted({s for c in captures for s in c["per_symbol"]})
    overall: dict[str, Any] = {}
    for symbol in symbols:
        counts = [c["per_symbol"][symbol]["web_scored"] for c in captures if symbol in c["per_symbol"]]
        overall[symbol] = {
            "captures": len(counts),
            "captures_with_zero": sum(1 for n in counts if n == 0),
            "min": min(counts),
            "median": statistics.median(counts),
            "max": max(counts),
        }
    result: dict[str, Any] = {"captures": captures, "per_symbol": overall}
    if positions:
        values = [c["coverage"] for c in captures if c["coverage"] is not None]
        result["coverage"] = {
            "positions": positions,
            "min": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None,
            "captures_above_half": sum(1 for v in values if v > 0.5),
            "captures": len(values),
        }
    return result


def render(result: dict[str, Any]) -> str:
    lines = ["# Tóm tắt các lượt thu tin", "", "Số đo, không có ngưỡng đạt hay không đạt.", ""]
    lines += ["## Mỗi lượt", "", "| Lượt | Máy | Mã | Ứng viên | Bộ lọc cũ giữ | Luật mới giữ | Web chấm (n) |", "|---|---|---|---|---|---|---|"]
    for c in result["captures"]:
        for symbol, row in c["per_symbol"].items():
            lines.append(f"| {c['capture_id']} | {c['runtime']} | {symbol} | {row['candidates']} | {row['old_filter_keep']} | {row['new_keep']} | {row['web_scored']} |")
    lines += ["", "## Mỗi mã qua các lượt", "", "| Mã | Số lượt | Lượt có n = 0 | n nhỏ nhất | trung vị | lớn nhất |", "|---|---|---|---|---|---|"]
    for symbol, row in result["per_symbol"].items():
        lines.append(f"| {symbol} | {row['captures']} | {row['captures_with_zero']} | {row['min']} | {row['median']} | {row['max']} |")
    if "coverage" in result:
        cov = result["coverage"]
        weights = ", ".join(f"{s.removesuffix('.EGX')} {w:g}" for s, w in cov["positions"].items())
        lines += ["", f"## Độ phủ của danh mục {weights}", ""]
        if cov["captures"]:
            lines += [
                f"- Độ phủ nhỏ nhất {cov['min']:.0%}, trung vị {cov['median']:.0%}, lớn nhất {cov['max']:.0%} trên {cov['captures']} lượt.",
            ]
        lines += ["", "| Lượt | Độ phủ |", "|---|---|"] + [f"| {c['capture_id']} | {c['coverage']:.0%} |" for c in result["captures"] if c["coverage"] is not None]
    return "\n".join(lines) + "\n"


def parse_positions(value: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in value.split(","):
        if part.strip():
            symbol, _, weight = part.partition(":")
            out[normalize_symbol(symbol)] = float(weight)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("captures", nargs="+")
    parser.add_argument("--positions", help="Ví dụ COMI:50,ETEL:30,FWRY:20")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = summarize(args.captures, parse_positions(args.positions) if args.positions else None)
    Path(args.out).write_text(render(result), encoding="utf-8")
    print(f"Đã ghi {args.out}")


if __name__ == "__main__":
    main()
