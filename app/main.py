from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.env_loader import load_project_env

load_project_env()

from app.api.routes_content import router as content_router
from app.api.routes_chat import router as chat_router
from app.api.routes_detect import router as detect_router
from app.api.routes_export import router as export_router
from app.api.routes_health import router as health_router
from app.api.routes_history import router as history_router
from app.api.routes_simulate import router as simulate_router
from app.api.routes_pipeline_state import router as pipeline_router
from app.core.concurrency import init_semaphore
from app.services.history_store import init_db
from app.services.chat_store import init_db as init_chat_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    init_db()
    init_chat_db()
    init_semaphore()
    yield
    # 关闭时清理（预留）


app = FastAPI(title="TruthCast MVP", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 局域网/内网部署：允许所有来源
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(detect_router)
app.include_router(chat_router)
app.include_router(simulate_router)
app.include_router(pipeline_router)
app.include_router(history_router)
app.include_router(content_router)
app.include_router(export_router)
