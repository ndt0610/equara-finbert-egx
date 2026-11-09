from __future__ import annotations

import math
import asyncio
from typing import Any, Awaitable, Callable

import httpx

from backend.config import HF_ENDPOINT, HF_PROVIDER, MODEL_ID, is_huggingface_url


LABELS = ("positive", "negative", "neutral")


class InferenceProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class _BatchNotSupported(Exception):
    """HF từ chối hoặc trả sai dạng cho request nhiều tiêu đề: quay về gửi từng tiêu đề."""


class HuggingFaceFinBERT:
    """Adapter HF text-classification: gửi theo lô (bài báo mục 8), dự phòng từng tiêu đề."""

    provider_name = HF_PROVIDER

    # [HOÀN THIỆN] Bài báo (mục 8) tự nhận HF API có "latency and rate limits". Trước đây
    # chỉ 1 lần HTTP 429 (giới hạn tốc độ) hoặc 503 (model đang nạp) là cả lượt phân tích
    # 15 tiêu đề thất bại. Nay thử lại tối đa `max_retries` lần, chờ theo Retry-After /
    # estimated_time của server nếu có, nếu không thì lùi theo cấp số nhân 1s, 2s, 4s.
    RETRYABLE_STATUS = (429, 503)
    MAX_WAIT_SECONDS = 10.0

    # [HOÀN THIỆN] Bài báo mục 8: "We send up to ~15 headlines per request. The API returns
    # one result per input when top_k=3 is set." Bản gốc gửi 1 tiêu đề / request vì tài liệu HF
    # hiện ghi `inputs` là chuỗi. Nay gửi tối đa 15 tiêu đề / request như bài báo; nếu HF trả
    # 400/413/422 hoặc kết quả không đúng "mỗi đầu vào một danh sách 3 nhãn", adapter tự
    # quay về cách cũ (từng tiêu đề) và nhớ lựa chọn đó cho các lần sau.
    BATCH_SIZE = 15
    BATCH_REJECTED_STATUS = (400, 413, 422)

    # [HOÀN THIỆN] Bài báo mục 8 đặt serverless (HF lo máy chủ) cạnh self-hosted (tự chạy model).
    # Từ tháng 10/2026 tài khoản Hugging Face miễn phí không còn credit Inference Providers (HTTP 402).
    # `endpoint` cho phép cùng adapter này gọi một máy chủ tự dựng nói đúng định dạng API của HF
    # (scripts/serve_hf_api.py). HF_TOKEN chỉ được gửi tới huggingface.co, không bao giờ tới nơi khác.

    def __init__(
        self,
        client: httpx.AsyncClient,
        token: str | None,
        max_retries: int = 2,
        base_delay_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        batch_size: int = BATCH_SIZE,
        endpoint: str = HF_ENDPOINT,
    ) -> None:
        self.client = client
        self.token = token
        self.endpoint = endpoint or HF_ENDPOINT
        self.self_hosted = not is_huggingface_url(self.endpoint)
        self.max_retries = max(0, int(max_retries))
        self.base_delay_seconds = base_delay_seconds
        self._sleep = sleep
        self.batch_size = max(1, int(batch_size))
        self.batch_supported: bool | None = None  # None = chưa thử; False = HF không nhận lô
        self.retries_used = 0
        self.http_requests = 0  # số request logic đã gửi (không tính lần thử lại)

    @property
    def device_name(self) -> None:
        return None

    async def server_revision(self) -> str | None:
        """Revision mà máy chủ tự dựng (scripts/serve_hf_api.py) đang dùng, đọc từ /health của máy chủ đó.

        [NÂNG CẤP C, việc sót của vòng A] Trước đây /api/health báo `inference_revision: null` ở chế độ
        hf-inference, nên không biết web và notebook có cùng một mô hình không. Chỉ hỏi máy chủ tự dựng;
        không bao giờ gửi token; lỗi thì trả None.
        """
        if not self.self_hosted:
            return None
        cached = getattr(self, "_server_revision", None)
        if cached:
            return cached
        parts = httpx.URL(self.endpoint)
        try:
            response = await self.client.get(str(parts.copy_with(path="/health", query=None)), timeout=5.0)
            revision = response.json().get("revision") if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
        self._server_revision = str(revision) if revision else None
        return self._server_revision

    @property
    def server(self) -> str:
        return "self-hosted (HF API format)" if self.self_hosted else "huggingface.co"

    @property
    def request_mode(self) -> str:
        if self.batch_supported is False:
            mode = "one headline per HTTP request (server rejected batch input)"
        else:
            mode = f"up to {self.batch_size} headlines per HTTP request, fallback one per request"
        return f"{mode}; server: {self.server}"

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(self.MAX_WAIT_SECONDS, max(0.0, float(header)))
            except ValueError:
                pass
        try:
            estimated = float(response.json().get("estimated_time"))
            return min(self.MAX_WAIT_SECONDS, max(0.0, estimated))
        except (ValueError, TypeError, AttributeError):
            pass
        return min(self.MAX_WAIT_SECONDS, self.base_delay_seconds * (2**attempt))

    async def _post(self, inputs: str | list[str], *, batch: bool) -> Any:
        if not self.self_hosted and not self.token:
            raise InferenceProviderError(
                "Thiếu HF_TOKEN. Hãy cấu hình token Hugging Face có quyền Inference Providers.",
                status_code=424,
            )
        headers = {} if self.self_hosted else {"Authorization": f"Bearer {self.token}"}

        self.http_requests += 1
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.post(
                    self.endpoint,
                    headers=headers,
                    json={
                        "inputs": inputs,
                        "parameters": {
                            "top_k": 3,
                            "function_to_apply": "softmax",
                        },
                    },
                )
            except httpx.TimeoutException as exc:
                raise InferenceProviderError("Hugging Face Inference API timed out.", 504) from exc
            except httpx.RequestError as exc:
                raise InferenceProviderError("Không kết nối được Hugging Face Inference API.", 502) from exc
            if response.status_code in self.RETRYABLE_STATUS and attempt < self.max_retries:
                self.retries_used += 1
                await self._sleep(self._retry_delay(response, attempt))
                continue
            break

        if batch and response.status_code in self.BATCH_REJECTED_STATUS:
            raise _BatchNotSupported(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            message = {
                401: "HF_TOKEN không hợp lệ hoặc thiếu quyền Inference Providers.",
                403: "Hugging Face từ chối quyền truy cập model/provider.",
                404: "Không tìm thấy model hoặc route HF Inference API.",
                429: "Hugging Face Inference API đã giới hạn tốc độ request.",
                503: "Model/provider Hugging Face hiện chưa sẵn sàng.",
            }.get(response.status_code, f"Hugging Face Inference API trả HTTP {response.status_code}.")
            raise InferenceProviderError(message, response.status_code)

        try:
            payload: Any = response.json()
        except ValueError as exc:
            if batch:
                raise _BatchNotSupported("invalid JSON") from exc
            raise InferenceProviderError("Hugging Face trả về JSON không hợp lệ.") from exc

        if isinstance(payload, dict) and payload.get("error"):
            if batch:
                raise _BatchNotSupported("error payload")
            raise InferenceProviderError("Hugging Face Inference API báo lỗi model/provider.")
        return payload

    @staticmethod
    def _scores_from_rows(payload: Any) -> dict[str, float]:
        if not isinstance(payload, list):
            raise InferenceProviderError("Phản hồi text-classification không đúng schema mảng.")

        scores: dict[str, float] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "")).strip().lower()
            if label not in LABELS:
                continue
            try:
                score = float(row["score"])
            except (KeyError, TypeError, ValueError):
                continue
            scores[label] = score

        if set(scores) != set(LABELS):
            raise InferenceProviderError(
                "Hugging Face không trả đủ ba nhãn Positive, Negative và Neutral."
            )
        if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in scores.values()):
            raise InferenceProviderError("Điểm sentiment trả về nằm ngoài khoảng xác suất [0, 1].")
        if abs(sum(scores.values()) - 1.0) > 1e-3:
            raise InferenceProviderError("Ba xác suất softmax trả về không có tổng xấp xỉ 1.")

        return scores

    async def classify(self, text: str) -> dict[str, float]:
        return self._scores_from_rows(await self._post(text, batch=False))

    async def _classify_batch(self, texts: list[str]) -> list[dict[str, float]]:
        payload = await self._post(texts, batch=True)
        if isinstance(payload, list) and len(payload) == len(texts) and all(isinstance(row, list) for row in payload):
            return [self._scores_from_rows(row) for row in payload]
        if len(texts) == 1 and isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
            return [self._scores_from_rows(payload)]
        raise _BatchNotSupported("one result per input was not returned")

    async def classify_many(self, texts: list[str]) -> list[dict[str, float]]:
        results: list[dict[str, float]] = []
        for start in range(0, len(texts), self.batch_size):
            chunk = texts[start : start + self.batch_size]
            if self.batch_supported is not False and len(chunk) > 1:
                try:
                    results.extend(await self._classify_batch(chunk))
                    self.batch_supported = True
                    continue
                except _BatchNotSupported:
                    self.batch_supported = False
            for text in chunk:
                results.append(await self.classify(text))
        return results
