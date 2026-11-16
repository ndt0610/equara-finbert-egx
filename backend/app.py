from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

from backend.config import MODEL_ID, Settings
from backend.schemas import PortfolioAnalysisRequest, StockAnalysisRequest
from backend.services.sentiment import AnalysisError, SentimentService
from backend.upgrades.portfolio_weighting import Position
from backend.upgrades.coverage import CoverageConfig
from backend.upgrades.coverage_service import CoverageService
from backend.upgrades.schemas import CoverageRequest, WeightedPortfolioRequest, parse_positions_query
from backend.upgrades.service import UpgradedPortfolioService
from backend.upgrades.tin_gia.context_service import TinGiaContextService
from backend.contracts.pit_models import USPortfolioRequest
from backend.services.portfolio_exposure import analyze_us_portfolio
from backend.universe.catalog import load_universe
from backend.storage.pit_ledger import PitLedger
from backend.services.pit_decision_snapshot import build_snapshot
from backend.services.us_audit_summary import audit_summary
from backend.services.us_capture import capture_sec, capture_alpaca_news, capture_alpaca_prices, default_cutoff
from backend.providers.us_market.sec_edgar_adapter import ProviderUnconfigured
from backend.providers.us_market.us_price_adapter import AlpacaPriceAccessError
from backend.providers.hf_inference import InferenceProviderError
import json


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("equara")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = RotatingFileHandler(
        ARTIFACTS_DIR / "backend.log",
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

settings = Settings.from_environment()


@asynccontextmanager
async def lifespan(application: FastAPI):
    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        application.state.service = SentimentService(client, settings)
        # [NÂNG CẤP] Lớp bổ sung bọc quanh service lõi; không thay đổi các endpoint cũ.
        application.state.upgraded = UpgradedPortfolioService(application.state.service)
        # [NÂNG CẤP C] Độ phủ tin và đóng góp theo vốn; dùng chung bộ nhớ đệm và model với lớp nâng cấp.
        application.state.coverage = CoverageService(application.state.upgraded, CoverageConfig.from_environment())
        # [TIN + GIÁ V1] Luồng phân tích riêng cho một mã đang nắm; không lấy tỷ trọng C3 để phát nhãn.
        application.state.tin_gia = TinGiaContextService(application.state.service, settings)
        logger.info(
            "application started mode=%s inference_provider=%s model_revision=%s device=%s hf_token_configured=%s eodhd_news_token_configured=%s",
            settings.demo_mode,
            settings.inference_provider,
            application.state.service.inference_metadata().get("revision"),
            application.state.service.inference_metadata().get("device"),
            bool(settings.hf_token),
            bool(settings.eodhd_news_api_token),
        )
        yield
    logger.info("application stopped")


app = FastAPI(
    title="Equara AI article reconstruction",
    version="0.2.0",
    description="EGX sentiment demo based on the supplied architecture article; not the original Equara AI app.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.exception_handler(AnalysisError)
async def analysis_error_handler(_: Request, exc: AnalysisError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "context": exc.context}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # [HOÀN THIỆN] exc.errors() có thể chứa object ValueError (từ validator mã EGX / mã trùng),
    # không serialize được sang JSON → trước đây server trả HTTP 500. jsonable_encoder chuyển
    # chúng thành chuỗi; thông báo tiếng Việt của validator được đưa lên trường "message".
    details = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    message = "Dữ liệu request không hợp lệ."
    for error in details:
        if error.get("type") == "value_error":
            message = str(error.get("msg", message)).removeprefix("Value error, ")
            break
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": message, "details": details}},
    )


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    inference = request.app.state.service.inference_metadata()
    revision = inference["revision"]
    provider = request.app.state.service.inference
    if revision is None and hasattr(provider, "server_revision"):
        revision = await provider.server_revision()  # máy chủ tự dựng báo revision của nó
    return {
        "status": "ok",
        "app_version": "0.2.0",
        "data_mode": settings.demo_mode,
        "model": MODEL_ID,
        "inference_provider": inference["provider"],
        "inference_revision": revision,
        "inference_device": inference["device"],
        "hf_token_configured": bool(settings.hf_token),
        "eodhd_token_configured": bool(settings.eodhd_news_api_token),
        "eodhd_news_token_configured": bool(settings.eodhd_news_api_token),
        "eodhd_price_token_configured": bool(settings.eodhd_api_token),
        "inference_request_mode": inference["request_mode"],
    }


@app.get("/api/stocks")
async def stocks() -> dict[str, Any]:
    return {
        "market": "EGX",
        "items": [
            {"symbol": "COMI", "eodhd_symbol": "COMI.EGX", "name": "Commercial International Bank (CIB)", "article_example": True},
            {"symbol": "ETEL", "eodhd_symbol": "ETEL.EGX", "name": "Telecom Egypt", "article_example": True},
            {"symbol": "FWRY", "eodhd_symbol": "FWRY.EGX", "name": "Fawry", "article_example": True},
        ],
        "note": "Ba mã ví dụ trong bài báo; API cũng nhận mã EGX khác theo định dạng mã.EGX.",
    }


@app.get("/api/v3/us/universe")
async def us_universe() -> dict[str, Any]:
    return load_universe()


@app.get("/api/v3/us/fixture")
async def us_portfolio_fixture() -> dict[str, Any]:
    return json.loads((ROOT_DIR / "fixtures" / "us_portfolio_phase1.json").read_text(encoding="utf-8"))


@app.post("/api/v3/us/portfolio/exposure")
async def us_portfolio_exposure(payload: USPortfolioRequest) -> dict[str, Any]:
    try:
        return analyze_us_portfolio(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class UsCaptureRequest(BaseModel):
    source: Literal["sec", "alpaca_news", "alpaca_prices"]
    tickers: list[str] = Field(default_factory=list, max_length=50)
    end_ts_utc: str | None = None


class UsSnapshotRequest(BaseModel):
    holdings: list[dict] = Field(min_length=1, max_length=20)
    cash_usd: float = Field(default=0, ge=0)
    decision_ts_utc: str | None = None
    strict_pit_mode: bool = True
    window_days: int = Field(default=7, ge=1, le=90)
    relevance_filter: Literal["none", "exclude_noise"] = "exclude_noise"
    scenario_returns: dict[str, float] = Field(default_factory=dict)


@app.post("/api/v3/us/capture")
async def us_capture(payload: UsCaptureRequest) -> dict[str, Any]:
    tickers = payload.tickers or [x["ticker"] for x in load_universe()["items"]]
    if len(tickers) != len(set(tickers)) or any(x not in {r["ticker"] for r in load_universe()["items"]} for x in tickers):
        raise HTTPException(status_code=422, detail="INVALID_TICKERS")
    ledger = PitLedger()
    try:
        if payload.source == "sec":
            return await capture_sec(ledger, tickers)
        if payload.source == "alpaca_news":
            return await capture_alpaca_news(ledger, tickers)
        end_ts = None
        if payload.end_ts_utc:
            from datetime import datetime
            end_ts = datetime.fromisoformat(payload.end_ts_utc)
        return await capture_alpaca_prices(ledger, tickers, end_ts_utc=end_ts)
    except ProviderUnconfigured as exc:
        raise HTTPException(status_code=503, detail=f"PROVIDER_UNCONFIGURED: {exc}") from exc
    except InferenceProviderError as exc:
        raise HTTPException(status_code=503, detail=f"FINBERT_UNAVAILABLE: {exc}") from exc
    except AlpacaPriceAccessError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"PROVIDER_UNAVAILABLE: {type(exc).__name__}") from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        ledger.close()


@app.post("/api/v3/us/snapshot")
async def us_snapshot(payload: UsSnapshotRequest) -> dict[str, Any]:
    ledger = PitLedger()
    try:
        return build_snapshot(ledger, payload.decision_ts_utc or default_cutoff(), payload.holdings,
                              payload.cash_usd, payload.strict_pit_mode, payload.window_days,
                              payload.relevance_filter, payload.scenario_returns)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        ledger.close()


@app.get('/api/v3/us/audit-summary')
async def us_audit_summary() -> dict[str, Any]:
    ledger = PitLedger()
    try:
        return audit_summary(ledger, ARTIFACTS_DIR)
    finally:
        ledger.close()


@app.post("/api/sentiment/stock")
async def analyze_stock(payload: StockAnalysisRequest, request: Request) -> dict[str, Any]:
    logger.info("request received scope=stock symbol=%s mode=%s", payload.symbol, settings.demo_mode)
    service: SentimentService = request.app.state.service
    return await service.analyze_stock(payload.symbol)


@app.post("/api/sentiment/portfolio")
async def analyze_portfolio(payload: PortfolioAnalysisRequest, request: Request) -> dict[str, Any]:
    logger.info("request received scope=portfolio symbols=%s mode=%s", ",".join(payload.symbols), settings.demo_mode)
    service: SentimentService = request.app.state.service
    return await service.analyze_portfolio(payload.symbols)


# [HOÀN THIỆN] Sơ đồ mục 2–3 của bài báo: app di động gọi `GET sentiment` và nhận JSON.
# Hai route GET dưới đây dùng đúng schema kiểm tra và đúng service của 2 route POST ở trên,
# nên cùng đầu vào cho cùng JSON. Ví dụ:
#   GET /api/sentiment/stock?symbol=COMI
#   GET /api/sentiment/portfolio?symbols=COMI,ETEL,FWRY
def _validate_query(model: type[BaseModel], data: dict[str, Any]) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        # Đưa về cùng định dạng lỗi 422 tiếng Việt như route POST.
        raise RequestValidationError(
            [{**error, "loc": ("query", *error.get("loc", ()))} for error in exc.errors()]
        ) from exc


@app.get("/api/sentiment/stock")
async def analyze_stock_get(request: Request, symbol: str = Query(..., description="Mã EGX, ví dụ COMI")) -> dict[str, Any]:
    payload = _validate_query(StockAnalysisRequest, {"symbol": symbol})
    return await analyze_stock(payload, request)


@app.get("/api/v1/tin-gia/stock")
async def analyze_tin_gia_stock(
    request: Request,
    symbol: str = Query(..., description="Mã EGX, ví dụ COMI"),
) -> dict[str, Any]:
    payload = _validate_query(StockAnalysisRequest, {"symbol": symbol})
    logger.info("request received scope=tin_gia symbol=%s mode=%s", payload.symbol, settings.demo_mode)
    return await request.app.state.tin_gia.analyze(payload.symbol)


@app.get("/api/sentiment/portfolio")
async def analyze_portfolio_get(
    request: Request,
    symbols: str = Query(..., description="1–5 mã EGX, cách nhau bằng dấu phẩy, ví dụ COMI,ETEL,FWRY"),
) -> dict[str, Any]:
    parts = [part.strip() for part in symbols.split(",") if part.strip()]
    payload = _validate_query(PortfolioAnalysisRequest, {"symbols": parts})
    return await analyze_portfolio(payload, request)



# ---------------------------------------------------------------------------
# [NÂNG CẤP] Endpoint bổ sung — Module 1 (Time-Decay + Confidence),
# Module 2 (tỷ trọng vốn + macro beta), Module 3 (TTL cache).
# Trả về song song điểm theo bài báo gốc và điểm theo code cải tiến trên cùng tập tin.
# ---------------------------------------------------------------------------
@app.post("/api/v2/sentiment/portfolio/weighted")
async def analyze_weighted_portfolio(payload: WeightedPortfolioRequest, request: Request) -> dict[str, Any]:
    logger.info(
        "request received scope=weighted_portfolio positions=%s mode=%s",
        ",".join(f"{p.symbol}:{p.weight}:{p.macro_beta}" for p in payload.positions),
        settings.demo_mode,
    )
    upgraded: UpgradedPortfolioService = request.app.state.upgraded
    return await upgraded.analyze_weighted_portfolio(
        [Position(p.symbol, p.weight, p.macro_beta) for p in payload.positions],
        half_life_hours={"micro": payload.half_life_micro_hours, "macro": payload.half_life_macro_hours},
        prior_strength=payload.prior_strength,
        neutral_band=payload.neutral_band,
    )


# ---------------------------------------------------------------------------
# [NÂNG CẤP C] Tab "Danh mục theo vốn": điểm tin đã chấm theo vốn, đóng góp từng mã, phạm vi dữ liệu,
# vĩ mô tách riêng, và điểm cách bài báo trên cùng lượt lấy tin. GET và POST cho cùng JSON.
#   POST /api/v2/sentiment/portfolio/coverage  {"positions": [{"symbol": "COMI", "weight": 50}, ...]}
#   GET  /api/v2/sentiment/portfolio/coverage?positions=COMI:50,ETEL:30,FWRY:20
# ---------------------------------------------------------------------------
@app.post("/api/v2/sentiment/portfolio/coverage")
async def analyze_coverage_portfolio(payload: CoverageRequest, request: Request) -> dict[str, Any]:
    logger.info(
        "request received scope=coverage_portfolio positions=%s mode=%s",
        ",".join(f"{p.symbol}:{p.weight}" for p in payload.positions),
        settings.demo_mode,
    )
    coverage: CoverageService = request.app.state.coverage
    return await coverage.analyze([(p.symbol, p.weight) for p in payload.positions])


@app.get("/api/v2/sentiment/portfolio/coverage")
async def analyze_coverage_portfolio_get(
    request: Request,
    positions: str = Query(..., description="1–5 cặp MÃ:VỐN, cách nhau bằng dấu phẩy, ví dụ COMI:50,ETEL:30,FWRY:20"),
) -> dict[str, Any]:
    payload = _validate_query(CoverageRequest, {"positions": parse_positions_query(positions)})
    return await analyze_coverage_portfolio(payload, request)


@app.get("/api/v2/coverage/config")
async def coverage_config(request: Request) -> dict[str, Any]:
    return request.app.state.coverage.config.to_dict()


@app.get("/api/v2/cache/stats")
async def cache_stats(request: Request) -> dict[str, Any]:
    return request.app.state.upgraded.cache_stats()
