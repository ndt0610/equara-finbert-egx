"""Tạo phiếu gán nhãn MÙ từ một hay nhiều lượt thu tin (scripts/capture_candidates.py).

"Mù" nghĩa là phiếu không có kết quả của luật lọc, của bộ lọc cũ, hay xác suất FinBERT, và thứ tự tin
được xáo trộn. Mỗi người gán nhận một file riêng và làm độc lập. Đáp án của máy nằm ở file khóa, không
gửi cho người gán.

Hai loại phiếu:
  --kind relevance  (mặc định) Câu hỏi: "Tiêu đề này có nói về hoạt động kinh doanh hoặc tài chính của
                    đúng doanh nghiệp này không?" Gồm mọi ứng viên tin riêng, kể cả tin bị loại.
  --kind sentiment  Câu hỏi theo cách gán nhãn của Financial PhraseBank (Malo và cộng sự, 2014): "Từ góc
                    nhìn nhà đầu tư, tin này nhiều khả năng tác động tích cực, tiêu cực hay trung tính tới giá
                    cổ phiếu của công ty được nhắc tới?" Gồm các tin riêng mà luật lọc giữ, và tin vĩ mô.

Chạy:
    python -m scripts.make_label_sheet captures/<lượt 1> captures/<lượt 2> --out labels/relevance
    python -m scripts.make_label_sheet captures/<lượt 1> --kind sentiment --out labels/sentiment
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any, Iterable

QUESTIONS = {
    "relevance": (
        "Tiêu đề này có nói về hoạt động kinh doanh hoặc tài chính của đúng doanh nghiệp này không?",
        "1 = có · 0 = không · ? = không chắc (để trống cũng tính là không chắc)",
    ),
    "sentiment": (
        "Từ góc nhìn nhà đầu tư, tin này nhiều khả năng tác động tích cực, tiêu cực hay trung tính tới giá cổ phiếu "
        "của công ty được nhắc tới (với tin vĩ mô: tới thị trường chứng khoán Ai Cập)?",
        "positive · negative · neutral · ? = không chắc",
    ),
}


def _norm(title: str) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", title.casefold())).strip()


def item_id(kind: str, symbol: str, title: str) -> str:
    return hashlib.sha256(f"{kind}|{symbol}|{_norm(title)}".encode("utf-8")).hexdigest()[:10]


def load_rows(capture_dirs: Iterable[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder in capture_dirs:
        data = json.loads((Path(folder) / "capture.json").read_text(encoding="utf-8"))
        version = data.get("meta", {}).get("relevance_rules", "")
        rows.extend(dict(row, relevance_rules=version) for row in data["rows"])  # nhãn new_keep thuộc phiên bản luật lúc thu
    return rows


def select_items(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    chosen: dict[str, dict[str, Any]] = {}
    for row in rows:
        if kind == "relevance":
            if row.get("kind") != "micro":
                continue
        elif not (row.get("kind") == "macro" or row.get("new_keep") is True):
            continue
        key = item_id(kind, row.get("symbol") or "", row["title"])
        chosen.setdefault(key, dict(row, item_id=key))  # lần đầu gặp: giữ dòng của lượt thu sớm nhất
    return list(chosen.values())


def write_sheets(items: list[dict[str, Any]], out: Path, kind: str, raters: int = 2, seed: int = 20261104) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    order = list(items)
    random.Random(seed).shuffle(order)
    files: dict[str, Path] = {}
    for rater in range(1, raters + 1):
        path = out / f"nhan_nguoi_{rater}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:  # utf-8-sig để Excel đọc đúng tiếng Việt
            writer = csv.writer(handle)
            writer.writerow(["item_id", "cong_ty", "tieu_de", "link", "nhan", "ghi_chu"])
            for row in order:
                company = row.get("company") or ("Vĩ mô Ai Cập" if row.get("kind") == "macro" else "")
                writer.writerow([row["item_id"], company, row["title"], row.get("url") or "", "", ""])
        files[f"rater_{rater}"] = path
    key = out / "khoa_dap_an_KHONG_GUI_NGUOI_GAN.csv"
    with key.open("w", encoding="utf-8", newline="") as handle:
        fields = ["item_id", "kind", "symbol", "company", "title", "url", "source", "query_tier", "capture_id", "relevance_rules",
                  "new_keep", "new_reason_code", "old_filter_keep", "web_scored", "p_positive", "p_negative", "p_neutral"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in items:
            probs = row.get("probabilities") or {}
            writer.writerow({**row, "p_positive": probs.get("positive", ""), "p_negative": probs.get("negative", ""), "p_neutral": probs.get("neutral", "")})
    files["key"] = key
    question, values = QUESTIONS[kind]
    guide = out / "HUONG_DAN_GAN_NHAN.md"
    guide.write_text(
        "\n".join(
            [
                f"# Hướng dẫn gán nhãn ({kind})",
                "",
                f"Câu hỏi cho mỗi dòng: **{question}**",
                "",
                f"Điền cột `nhan`: {values}.",
                "",
                "- Mỗi người làm file của mình, không bàn với người kia cho tới khi cả hai nộp.",
                "- Chỉ đọc tiêu đề và tên công ty; có thể mở link nếu tiêu đề quá ngắn, nhưng ghi lại ở cột `ghi_chu`.",
                "- Không mở file khóa đáp án.",
                f"- Số dòng: {len(items)}.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    files["guide"] = guide
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("captures", nargs="+", help="Thư mục lượt thu (chứa capture.json).")
    parser.add_argument("--kind", choices=sorted(QUESTIONS), default="relevance")
    parser.add_argument("--raters", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261104)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    items = select_items(load_rows(args.captures), args.kind)
    files = write_sheets(items, Path(args.out), args.kind, args.raters, args.seed)
    print(f"{len(items)} dòng. " + " · ".join(f"{k}: {v}" for k, v in files.items()))


if __name__ == "__main__":
    main()
