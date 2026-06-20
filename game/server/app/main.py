"""FastAPI application entrypoint.

Run locally:
    cd game/server
    uvicorn app.main:app --reload

Then open http://localhost:8000/docs for interactive API docs.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .routers import catalog, characters, chests, players, quests, store

app = FastAPI(
    title="Mobile Game Backend",
    version=__version__,
    description=(
        "Engine-agnostic backend for the mobile third-person shooter: "
        "players, characters, progression & skill trees, inventory/loadouts, "
        "microtransaction store, world chests and quests."
    ),
)

app.include_router(players.router)
app.include_router(characters.router)
app.include_router(catalog.router)
app.include_router(store.router)
app.include_router(chests.router)
app.include_router(quests.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
