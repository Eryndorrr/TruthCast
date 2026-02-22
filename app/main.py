from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.env_loader import load_project_env

load_project_env()

from app.api.routes_detect import router as detect_router
from app.api.routes_health import router as health_router
from app.api.routes_history import router as history_router
from app.api.routes_simulate import router as simulate_router
from app.core.concurrency import init_semaphore
from app.services.history_store import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    init_db()
    init_semaphore()
    yield
    # 关闭时清理（预留）


app = FastAPI(title="TruthCast MVP", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(detect_router)
app.include_router(simulate_router)
app.include_router(history_router)
