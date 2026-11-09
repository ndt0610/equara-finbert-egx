from __future__ import annotations

import asyncio
import threading

from backend.config import DEFAULT_LOCAL_MODEL_REVISION, MODEL_ID
from backend.providers.hf_inference import InferenceProviderError, LABELS


class TransformersLocalFinBERT:
    """Run the pinned ProsusAI/finbert weights in this backend process."""

    provider_name = "transformers-local"
    request_mode = "local Transformers batch inference; no inference HTTP requests"

    def __init__(
        self,
        model_id: str = MODEL_ID,
        revision: str = DEFAULT_LOCAL_MODEL_REVISION,
        device_preference: str = "cpu",
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise InferenceProviderError(
                "Thiếu PyTorch hoặc Transformers. Cài dependencies từ requirements.lock.txt.",
                status_code=503,
            ) from exc

        self.torch = torch
        self.model_id = model_id
        self.revision = revision
        self._lock = threading.Lock()

        if device_preference == "cuda":
            if not torch.cuda.is_available():
                raise InferenceProviderError(
                    "LOCAL_INFERENCE_DEVICE=cuda nhưng runtime không có CUDA; chọn cpu hoặc auto.",
                    status_code=503,
                )
            self.device = torch.device("cuda")
        elif device_preference == "auto" and torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")

        if self.device.type == "cpu":
            torch.set_num_threads(min(4, torch.get_num_threads()))

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision, token=False)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                model_id,
                revision=revision,
                token=False,
            )
            self.model.to(self.device)
            self.model.eval()
        except Exception as exc:
            raise InferenceProviderError(
                f"Không tải được {model_id} revision {revision} từ cache hoặc Hugging Face Hub ({type(exc).__name__}).",
                status_code=503,
            ) from exc

        raw_id2label = self.model.config.id2label
        self.id2label = {
            index: str(raw_id2label.get(index, raw_id2label.get(str(index), f"LABEL_{index}")))
            .strip()
            .lower()
            for index in range(self.model.config.num_labels)
        }
        if set(self.id2label.values()) != set(LABELS):
            raise InferenceProviderError(
                f"Model {model_id} không có đủ ba nhãn Positive, Negative và Neutral.",
                status_code=503,
            )

    @property
    def device_name(self) -> str:
        return str(self.device)

    async def classify(self, text: str) -> dict[str, float]:
        rows = await self.classify_many([text])
        return rows[0]

    async def classify_many(self, texts: list[str]) -> list[dict[str, float]]:
        return await asyncio.to_thread(self._classify_many, texts)

    def _classify_many(self, texts: list[str]) -> list[dict[str, float]]:
        if not texts:
            return []

        results: list[dict[str, float]] = []
        with self._lock:
            for start in range(0, len(texts), 16):
                batch = [str(text).strip() for text in texts[start : start + 16]]
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=256,
                    return_tensors="pt",
                )
                encoded = {name: tensor.to(self.device) for name, tensor in encoded.items()}
                try:
                    with self.torch.inference_mode():
                        probabilities = self.torch.softmax(self.model(**encoded).logits, dim=-1)
                    rows = probabilities.cpu().tolist()
                except Exception as exc:
                    raise InferenceProviderError(
                        f"FinBERT local inference thất bại ({type(exc).__name__}).",
                        status_code=500,
                    ) from exc

                for values in rows:
                    scores: dict[str, float] = {
                        self.id2label[index]: float(values[index])
                        for index in range(len(self.id2label))
                    }
                    self._validate_scores(scores)
                    results.append(scores)
        return results

    @staticmethod
    def _validate_scores(scores: dict[str, float]) -> None:
        if set(scores) != set(LABELS):
            raise InferenceProviderError(
                "FinBERT local không trả đủ ba nhãn Positive, Negative và Neutral.",
                status_code=500,
            )
        if any(value < 0.0 or value > 1.0 for value in scores.values()):
            raise InferenceProviderError(
                "Softmax local tạo xác suất ngoài khoảng [0, 1].",
                status_code=500,
            )
        if abs(sum(scores.values()) - 1.0) > 1e-5:
            raise InferenceProviderError(
                "Tổng xác suất softmax local khác 1.",
                status_code=500,
            )
