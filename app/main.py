from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .codex_client import AppServerError
from .collector import Monitor
from .config import refresh_interval
from .database import initialize

STATIC = Path(__file__).parent / "static"
monitor = Monitor(Path("/app/data"), refresh_interval())


class NewAccount(BaseModel):
    name: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    await monitor.start()
    yield
    await monitor.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def require_account(account_id: str):
    if account_id not in monitor.clients:
        raise HTTPException(404, "Unknown account")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard():
    return monitor.dashboard()


@app.post("/api/accounts", status_code=201)
async def add_account(payload: NewAccount):
    name = payload.name.strip()
    if not name or len(name) > 80:
        raise HTTPException(400, "Name must be 1–80 characters")
    return await monitor.add_account(name)


@app.delete("/api/accounts/{account_id}")
async def remove_account(account_id: str):
    if not await monitor.remove_account(account_id):
        raise HTTPException(404, "Unknown account")
    return {"removed": True}


@app.post("/api/accounts/{account_id}/login")
async def login(account_id: str):
    require_account(account_id)
    try:
        return await monitor.clients[account_id].begin_device_login()
    except (AppServerError, OSError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/accounts/{account_id}/sync")
async def sync(account_id: str):
    require_account(account_id)
    await monitor.sync(account_id)
    return monitor.dashboard()
