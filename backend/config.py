from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    demo_mode: str
    inference_provider: str
    local_model_revision: str
    local_inference_device: str
    hf_token: str | None
    eodhd_api_token: str | None
    eodhd_news_api_token: str | None = None
    eodhd_tin_gia_news_api_token: str | None = None
    hf_inference_url: str = ""

    @classmethod
    def from_environment(cls) -> "Settings":
        demo_mode = os.getenv("DEMO_MODE", "live").strip().lower()
        if demo_mode not in {"live", "fixture"}:
            raise ValueError("DEMO_MODE must be either 'live' or 'fixture'.")

        inference_provider = os.getenv("INFERENCE_PROVIDER", "transformers-local").strip().lower()
        if inference_provider not in {"transformers-local", "hf-inference"}:
            raise ValueError("INFERENCE_PROVIDER must be 'transformers-local' or 'hf-inference'.")

        local_inference_device = os.getenv("LOCAL_INFERENCE_DEVICE", "cpu").strip().lower()
        if local_inference_device not in {"cpu", "auto", "cuda"}:
            raise ValueError("LOCAL_INFERENCE_DEVICE must be 'cpu', 'auto', or 'cuda'.")

        return cls(
            demo_mode=demo_mode,
            inference_provider=inference_provider,
            local_model_revision=(
                os.getenv("LOCAL_MODEL_REVISION", "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031").strip()
                or "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
            ),
            local_inference_device=local_inference_device,
            hf_token=os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN"),
            eodhd_api_token=os.getenv("EODHD_API_TOKEN") or os.getenv("EODHD_TOKEN"),
            # Keep the EODHD credentials scoped: EODHD_NEWS_API_TOKEN powers the
            # article/portfolio flows; the old EODHD_API_TOKEN remains reserved
            # for the separate Tin + Giá feature's optional price/news connectors.
            eodhd_news_api_token=os.getenv("EODHD_NEWS_API_TOKEN"),
            eodhd_tin_gia_news_api_token=os.getenv("EODHD_TIN_GIA_NEWS_API_TOKEN"),
            hf_inference_url=os.getenv("HF_INFERENCE_URL", "").strip() or HF_ENDPOINT,
        )


MODEL_ID = "ProsusAI/finbert"
DEFAULT_LOCAL_MODEL_REVISION = "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
HF_PROVIDER = "hf-inference"
HF_ENDPOINT = f"https://router.huggingface.co/{HF_PROVIDER}/models/{MODEL_ID}"
EODHD_NEWS_ENDPOINT = "https://eodhd.com/api/news"
BBC_MIDDLE_EAST_RSS = "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def is_huggingface_url(url: str) -> bool:
    """True khi địa chỉ thuộc máy chủ Hugging Face (huggingface.co và tên miền con).

    [HOÀN THIỆN] HF_TOKEN chỉ được gửi tới các địa chỉ này. Máy chủ tự dựng
    (scripts/serve_hf_api.py, đặt qua HF_INFERENCE_URL) không cần và không nhận token.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "huggingface.co" or host.endswith(".huggingface.co"))
