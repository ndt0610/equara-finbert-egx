"""Kiểm tra đường gọi Hugging Face Inference API: cách gọi model đúng như bài báo (mục 5 và 8).

Script gửi 7 tiêu đề tham chiếu qua đúng adapter của backend
(`HuggingFaceFinBERT`: top_k=3, softmax, gửi theo lô tối đa 15 tiêu đề, thử lại khi 429/503).
Sau đó so 3 xác suất trả về với kết quả FinBERT chạy local (revision 0bc2ac10)
đã lưu trong `artifacts/local_inference_api_results.json`, rồi gửi lại 7 tiêu đề từng cái một
để đo gửi theo lô tiết kiệm bao nhiêu request và thời gian.

Kết quả trả lời 4 câu:
  1. Đường gọi API có chạy thật qua HTTP không (HTTP 200)?
  2. Gửi theo lô có được máy chủ chấp nhận không (bao nhiêu request HTTP cho 7 tiêu đề)?
  3. Máy chủ có trả cùng xác suất với FinBERT local không (cùng model, cùng phiên bản)?
  4. Gửi theo lô so với gửi từng tiêu đề: bao nhiêu request, bao nhiêu giây?

Hai nơi gọi được (chọn bằng --endpoint hoặc biến HF_INFERENCE_URL):
  - Mặc định: máy chủ Hugging Face thật. Cần HF_TOKEN có quyền "Make calls to Inference Providers"
    và còn credit (từ tháng 10/2026 tài khoản miễn phí không còn credit, sẽ nhận HTTP 402).
  - Máy chủ tự dựng `python -m scripts.serve_hf_api` (miễn phí, cùng định dạng API, không cần token):
        --endpoint http://127.0.0.1:8001/models/ProsusAI/finbert
Token chỉ được gửi tới huggingface.co, không bao giờ được in ra hay ghi vào file kết quả.

    python -m scripts.check_hf_api [--endpoint URL]
    # kết quả: artifacts/hf_api_check/hf_api_check.json (Hugging Face thật)
    #          artifacts/hf_api_check/self_hosted_api_check.json (máy chủ tự dựng)
    # file được ghi cả khi thất bại, kèm mã lỗi
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.config import HF_ENDPOINT, MODEL_ID
from backend.providers.hf_inference import LABELS, HuggingFaceFinBERT, InferenceProviderError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "fixtures" / "local_inference_api_results.json"
DEFAULT_OUT = ROOT / "artifacts" / "hf_api_check"

HINTS = {
    401: "Token sai, hoặc chưa tick quyền \"Make calls to Inference Providers\". Tạo lại token tại huggingface.co/settings/tokens.",
    402: "Tài khoản Hugging Face đã hết credit Inference Providers. Chờ credit tháng mới, dùng tài khoản khác, hoặc nạp thêm.",
    403: "Token không được phép gọi model hoặc provider này.",
    404: "Không tìm thấy route: provider hf-inference có thể không còn phục vụ ProsusAI/finbert.",
    424: "Chưa có HF_TOKEN. Trên Colab: Secrets, thêm khóa HF_TOKEN và bật Notebook access.",
    429: "Bị giới hạn tốc độ dù đã thử lại. Chờ vài phút rồi chạy lại.",
    502: "Không kết nối được Hugging Face. Kiểm tra mạng rồi chạy lại.",
    503: "Model đang nạp hoặc provider đang bận dù đã thử lại. Chờ 1 đến 2 phút rồi chạy lại.",
    504: "Hugging Face trả lời quá lâu. Chạy lại sau.",
}


def load_reference(path: Path) -> dict[str, Any]:
    """Lấy các tiêu đề (không trùng) và xác suất FinBERT local từ file tham chiếu."""
    ref = json.loads(path.read_text(encoding="utf-8"))
    seen: dict[str, dict[str, float]] = {}
    for section in ("single_stock", "five_symbol_portfolio"):
        for headline in ref.get(section, {}).get("headlines", []):
            seen.setdefault(headline["title"], headline["probabilities"])
    return {
        "file": path.name,
        "revision": ref["health"]["inference_revision"],
        "titles": list(seen),
        "probabilities": [seen[title] for title in seen],
    }


def top_label(probabilities: dict[str, float]) -> str:
    return max(LABELS, key=lambda label: probabilities[label])


def _clone(adapter: HuggingFaceFinBERT, batch_size: int) -> HuggingFaceFinBERT:
    return HuggingFaceFinBERT(
        adapter.client,
        adapter.token,
        max_retries=adapter.max_retries,
        sleep=adapter._sleep,
        batch_size=batch_size,
        endpoint=adapter.endpoint,
    )


async def _timed(adapter: HuggingFaceFinBERT, titles: list[str]) -> tuple[list[dict[str, float]], float]:
    started = time.perf_counter()
    rows = await adapter.classify_many(titles)
    return rows, time.perf_counter() - started


async def run_check(
    reference: dict[str, Any],
    client: httpx.AsyncClient,
    token: str | None,
    tolerance: float = 1e-3,
    adapter: HuggingFaceFinBERT | None = None,
    endpoint: str = HF_ENDPOINT,
    compare_one_by_one: bool = True,
    rounds: int = 3,
) -> dict[str, Any]:
    adapter = adapter or HuggingFaceFinBERT(client, token, endpoint=endpoint)
    titles: list[str] = reference["titles"]
    rounds = max(1, int(rounds))
    result: dict[str, Any] = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": adapter.endpoint,
        "server": adapter.server,
        "self_hosted": adapter.self_hosted,
        "model": MODEL_ID,
        "parameters": {"top_k": 3, "function_to_apply": "softmax", "batch_size": adapter.batch_size},
        "reference_file": reference["file"],
        "reference_revision": reference["revision"],
        "headlines": len(titles),
        "tolerance": tolerance,
        "timing": {
            "warmup_http_requests": 1,
            "rounds": rounds,
            "rule": "1 request khởi động (không tính giờ, tránh lần chạy model đầu tiên bị chậm), "
            "sau đó mỗi vòng đo lô rồi đo từng tiêu đề; báo trung vị.",
        },
    }
    warm = _clone(adapter, 1)
    batch_times: list[float] = []
    try:
        await warm.classify(titles[0])
        api, elapsed = await _timed(adapter, titles)
        batch_times.append(elapsed)
    except InferenceProviderError as exc:
        result.update(
            ok=False,
            status_code=exc.status_code,
            error=str(exc),
            hint=HINTS.get(exc.status_code, "Xem thông báo lỗi ở trên."),
            http_requests=warm.http_requests + adapter.http_requests,
            retries_used=warm.retries_used + adapter.retries_used,
        )
        return result

    rows = []
    for title, local, remote in zip(titles, reference["probabilities"], api):
        rows.append(
            {
                "title": title,
                "local": {label: local[label] for label in LABELS},
                "hf_api": {label: remote[label] for label in LABELS},
                "max_abs_diff": max(abs(local[label] - remote[label]) for label in LABELS),
                "same_label": top_label(local) == top_label(remote),
            }
        )
    max_diff = max(row["max_abs_diff"] for row in rows)
    result.update(
        ok=True,
        status_code=200,
        http_requests=adapter.http_requests,
        retries_used=adapter.retries_used,
        batch_supported=adapter.batch_supported,
        request_mode=adapter.request_mode,
        max_abs_diff=max_diff,
        labels_agree=sum(row["same_label"] for row in rows),
        same_model_version=max_diff <= tolerance,
        rows=rows,
    )

    single_times: list[float] = []
    single_requests = 0
    try:
        for round_index in range(rounds):
            if round_index > 0:
                batch_times.append((await _timed(_clone(adapter, adapter.batch_size), titles))[1])
            if compare_one_by_one:
                # Cùng 7 tiêu đề, gửi từng cái một (cách của code gốc) để đo lô tiết kiệm được bao nhiêu.
                single = _clone(adapter, 1)
                single_times.append((await _timed(single, titles))[1])
                single_requests = single.http_requests
    except InferenceProviderError as exc:
        result["one_by_one"] = {"ok": False, "status_code": exc.status_code}
    else:
        if compare_one_by_one:
            result["one_by_one"] = {
                "ok": True,
                "http_requests": single_requests,
                "elapsed_seconds": statistics.median(single_times),
                "elapsed_seconds_each_round": single_times,
            }
    result["elapsed_seconds"] = statistics.median(batch_times)
    result["elapsed_seconds_each_round"] = batch_times
    return result


def summary_lines(result: dict[str, Any]) -> list[str]:
    self_hosted = result.get("self_hosted", False)
    where = f"máy chủ tự dựng theo định dạng Hugging Face ({result['endpoint']})" if self_hosted else "Hugging Face API"
    if not result["ok"]:
        return [
            f"CHƯA GỌI ĐƯỢC {where}: HTTP {result['status_code']}.",
            f"Lỗi: {result['error']}",
            f"Cách xử lý: {result['hint']}",
            f"Số request HTTP đã gửi: {result['http_requests']} (thử lại {result['retries_used']} lần).",
        ]
    batch = "có" if result["batch_supported"] else "không, đã tự quay về gửi từng tiêu đề"
    server = "Máy chủ" if self_hosted else "Hugging Face"
    version = (
        f"khớp: {server} đang phục vụ đúng model và phiên bản đã dùng cho mọi biểu đồ"
        if result["same_model_version"]
        else f"lệch: {server} đang phục vụ phiên bản khác với bản ghim 0bc2ac10, số trên slide vẫn lấy từ bản local"
    )
    head = (
        f"Đường gọi API của bài báo CHẠY THẬT qua HTTP tới {where}"
        if self_hosted
        else "Hugging Face API CHẠY THẬT"
    )
    lines = [
        f"{head}: HTTP 200, {result['headlines']} tiêu đề trong {result['elapsed_seconds']:.2f} giây.",
        f"Gửi theo lô được chấp nhận: {batch}. Số request HTTP: {result['http_requests']} (thử lại {result['retries_used']} lần).",
        f"Sai khác lớn nhất so với FinBERT local: {result['max_abs_diff']:.2e} (ngưỡng {result['tolerance']:g}), {version}.",
        f"Nhãn cao nhất trùng nhau: {result['labels_agree']}/{result['headlines']} tiêu đề.",
    ]
    single = result.get("one_by_one")
    if single and single.get("ok"):
        lines.append(
            f"Gửi từng tiêu đề (code gốc): {single['http_requests']} request, {single['elapsed_seconds']:.2f} giây; "
            f"gửi theo lô: {result['http_requests']} request, {result['elapsed_seconds']:.2f} giây "
            f"(trung vị {result['timing']['rounds']} vòng, sau 1 request khởi động)."
        )
    if self_hosted:
        lines.append("Lưu ý: đây là máy chủ tự dựng (self-hosted, bài báo mục 8), không phải máy chủ của Hugging Face.")
    return lines


def write_result(result: dict[str, Any], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / ("self_hosted_api_check.json" if result.get("self_hosted") else "hf_api_check.json")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--tolerance", type=float, default=1e-3)
    parser.add_argument(
        "--endpoint",
        default=os.getenv("HF_INFERENCE_URL", "").strip() or HF_ENDPOINT,
        help="Mặc định là máy chủ Hugging Face thật; máy chủ tự dựng: http://127.0.0.1:8001/models/ProsusAI/finbert",
    )
    parser.add_argument("--no-one-by-one", action="store_true", help="Bỏ phần đo gửi từng tiêu đề.")
    parser.add_argument("--rounds", type=int, default=3, help="Số vòng đo thời gian (báo trung vị).")
    args = parser.parse_args()

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    reference = load_reference(Path(args.reference))

    async def _run() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            return await run_check(
                reference, client, token, args.tolerance, endpoint=args.endpoint,
                compare_one_by_one=not args.no_one_by_one, rounds=args.rounds,
            )

    result = asyncio.run(_run())
    path = write_result(result, Path(args.out))
    print("\n".join(summary_lines(result)))
    print(f"Đã ghi {path}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
