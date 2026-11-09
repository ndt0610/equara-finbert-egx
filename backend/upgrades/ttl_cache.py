"""Module 3a — Bộ nhớ đệm TTL (Time-To-Live) cho kết quả FinBERT và tin tức.

Bài báo gốc (mục 8) tự thừa nhận: dùng Hugging Face Inference API thì phải chịu "latency and
rate limits". Trong code hiện tại, adapter HF gửi 1 HTTP request cho MỖI tiêu đề, và mỗi lần
người dùng mở một mã/danh mục, toàn bộ tiêu đề (kể cả 4 tin vĩ mô dùng chung cho mọi mã) lại
bị chấm điểm lại từ đầu.

Ý tưởng: cache đúng thứ BẤT BIẾN, tính lại thứ BIẾN ĐỔI.
  - Bất biến: cùng model + cùng revision + cùng tiêu đề  →  cùng 3 xác suất softmax.
    → cache xác suất theo tiêu đề, TTL dài (mặc định 24 giờ).
  - Biến đổi: danh sách tin mới (đổi theo phút), tuổi tin (đổi theo giờ).
    → cache danh sách tin TTL ngắn (mặc định 10 phút); trọng số thời gian luôn tính lại theo
      giờ hiện tại, nên cache KHÔNG làm sai Time-Decay.
"""

from __future__ import annotations

import copy
import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable


class TTLCache:
    """Cache khóa → giá trị, mỗi mục hết hạn sau `ttl_seconds`; quá `max_items` thì bỏ mục cũ nhất (LRU)."""

    def __init__(
        self,
        ttl_seconds: float,
        max_items: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds phải > 0.")
        if max_items <= 0:
            raise ValueError("max_items phải > 0.")
        self.ttl_seconds = float(ttl_seconds)
        self.max_items = int(max_items)
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.expired = 0
        self.evictions = 0

    def get(self, key: Hashable) -> tuple[bool, Any]:
        now = self._clock()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return False, None
            expires_at, value = entry
            if now >= expires_at:
                del self._data[key]
                self.expired += 1
                self.misses += 1
                return False, None
            self._data.move_to_end(key)
            self.hits += 1
            return True, copy.deepcopy(value)

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = (self._clock() + self.ttl_seconds, copy.deepcopy(value))
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)
                self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict[str, Any]:
        lookups = self.hits + self.misses
        return {
            "ttl_seconds": self.ttl_seconds,
            "max_items": self.max_items,
            "size": len(self._data),
            "hits": self.hits,
            "misses": self.misses,
            "expired": self.expired,
            "evictions": self.evictions,
            "hit_rate": (self.hits / lookups) if lookups else 0.0,
        }


_WS = re.compile(r"\s+")


def headline_cache_key(model_id: str, revision: str | None, text: str) -> str:
    """Khóa = model + revision + tiêu đề đã chuẩn hóa khoảng trắng.

    Có revision trong khóa: khi đổi phiên bản model, cache cũ tự động không còn khớp.
    """
    normalized = _WS.sub(" ", str(text)).strip()
    raw = f"{model_id}@{revision or 'unpinned'}|{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CachedInference:
    """Bọc BẤT KỲ provider nào của phần lõi (local Transformers hoặc HF API) — không sửa provider.

    - Provider có `classify_many` (local): chỉ đưa các tiêu đề chưa có trong cache vào 1 batch.
    - Provider chỉ có `classify` (HF API, 1 request/tiêu đề): chỉ gửi request cho tiêu đề cache-miss
      → số HTTP request tới HF giảm đúng bằng số cache-hit (giảm rủi ro HTTP 429 rate limit).
    """

    def __init__(self, provider: Any, cache: TTLCache, model_id: str, revision: str | None = None) -> None:
        self.provider = provider
        self.cache = cache
        self.model_id = model_id
        self.revision = revision if revision is not None else getattr(provider, "revision", None)
        self.model_calls = 0  # tổng số tiêu đề thực sự đưa vào model / HF API
        self.last_call: dict[str, int] = {}

    @property
    def request_mode(self) -> str:
        return f"{getattr(self.provider, 'request_mode', 'inference')} + TTL cache theo tiêu đề"

    @property
    def device_name(self) -> Any:
        return getattr(self.provider, "device_name", None)

    async def classify(self, text: str) -> dict[str, float]:
        return (await self.classify_many([text]))[0]

    async def classify_many(self, texts: list[str]) -> list[dict[str, float]]:
        keys = [headline_cache_key(self.model_id, self.revision, text) for text in texts]
        results: dict[str, dict[str, float]] = {}
        pending: dict[str, str] = {}
        hits = 0
        for key, text in zip(keys, texts):
            if key in results or key in pending:
                hits += 1  # trùng trong cùng request: không chấm lại
                continue
            found, value = self.cache.get(key)
            if found:
                results[key] = value
                hits += 1
            else:
                pending[key] = text

        if pending:
            miss_keys = list(pending)
            miss_texts = [pending[key] for key in miss_keys]
            if hasattr(self.provider, "classify_many"):
                scored = await self.provider.classify_many(miss_texts)
            else:
                scored = [await self.provider.classify(text) for text in miss_texts]
            for key, scores in zip(miss_keys, scored, strict=True):
                self.cache.set(key, scores)
                results[key] = scores
            self.model_calls += len(miss_texts)

        self.last_call = {"requested": len(texts), "cache_hits": hits, "model_calls": len(pending)}
        return [dict(results[key]) for key in keys]
