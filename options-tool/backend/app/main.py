"""FastAPI entrypoint.

Run with::

    uvicorn app.main:app --reload --port 8001

All endpoints sit under ``/api``. The root ``/`` returns the educational
disclaimer so a misconfigured deploy still makes the intent obvious.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

BANNER = "Educational tool. Not financial advice. Paper trading only in v1."

app = FastAPI(
    title="Options Analysis Tool",
    version="0.1.0",
    description=BANNER,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "options-tool", "banner": BANNER}
