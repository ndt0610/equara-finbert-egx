from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from backend.config import MODEL_ID, Settings
from backend.schemas import PortfolioAnalysisRequest, StockAnalysisRequest
from backend.services.sentiment import AnalysisError, SentimentService
from backend.upgrades.portfolio_weighting import Position
from backend.upgrades.coverage import CoverageConfig
from backend.upgrades.coverage_service import CoverageService
from backend.upgrades.schemas import CoverageRequest, WeightedPortfolioRequest, parse_positions_query
from backend.upgrades.service import UpgradedPortfolioService
from backend.upgrades.tin_gia.context_service import TinGiaContextService


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
