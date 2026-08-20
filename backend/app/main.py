from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .logging_config import setup_logging
from .db.store import get_store
from .routes.forecast import router as forecast_router
from .routes.market_info import router as market_info_router
from .routes.mtf_rsi import router as mtf_rsi_router
from .routes.multi_year_breakout import router as multi_year_breakout_router
from .routes.news import router as news_router
from .routes.indicator_analysis import router as indicator_analysis_router
from .routes.nifty import router as nifty_router
from .routes.oi_momentum import router as oi_momentum_router
from .routes.scanner import router as scanner_router
from .routes.sector_rotation import router as sector_rotation_router
from .routes.labs_elliott_wave import router as labs_elliott_wave_router
from .routes.timeline import router as timeline_router

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Equity Scan Lab", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(forecast_router)
app.include_router(timeline_router)
app.include_router(scanner_router)
app.include_router(sector_rotation_router)
app.include_router(labs_elliott_wave_router)
app.include_router(multi_year_breakout_router)
app.include_router(market_info_router)
app.include_router(oi_momentum_router)
app.include_router(mtf_rsi_router)
app.include_router(nifty_router)
app.include_router(indicator_analysis_router)
app.include_router(news_router)


@app.on_event("startup")
async def on_startup() -> None:
    import os

    from .config import warm_instrument_keys_from_profiles
    from .services import forecast_registry

    store = get_store()
    stats = store.stats()
    warmed = warm_instrument_keys_from_profiles()
    logger.info(
        "Timeline DB ready at %s — %d/%d stocks with candle data (%d rows); "
        "warmed %d instrument keys",
        stats["db_path"],
        stats["symbols_with_data"],
        stats["profile_count"],
        stats["candle_count"],
        warmed,
    )

    model = os.getenv("FORECAST_MODEL", "timesfm-2.5")
    logger.info("Backend started — default forecast model: %s (lazy load, not preloaded)", model)
    for item in forecast_registry.list_models():
        logger.info(
            "  model %-12s available=%-5s loaded=%-5s default=%s — %s",
            item["id"],
            item["available"],
            item.get("loaded", False),
            item["default"],
            item["label"],
        )


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "equity-scan-lab", "docs": "/docs"}
