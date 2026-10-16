from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.web.routes import router

app = FastAPI(title="Кабінет — AI Daily Planner")

app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(router)


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
