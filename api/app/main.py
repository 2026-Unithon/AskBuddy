"""공용 — 라우터 등록만 한다. 비즈니스 로직을 여기에 쓰지 않는다.

셋 다 손대는 유일한 파일이라 충돌이 제일 잦다.
라우터 세 줄이 이미 등록돼 있으므로, 각자 자기 폴더의 router.py 만 채우면 된다.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.config import get_settings
from app.deps import close_pool, init_pool
from app.ingest.router import router as ingest_router
from app.preflight import router as preflight_router
from app.reg.router import router as reg_router

settings = get_settings()

# uvicorn 기본 설정은 app.* 로거를 흘려보내지 않는다.
# 가이드 8장 "LLM 호출마다 소요 시간·토큰 로깅" 이 화면에 보이려면 이게 필요하다
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("app").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="AskBuddy", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(preflight_router)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(reg_router, prefix="/reg", tags=["reg"])
app.include_router(ingest_router, prefix="/ingest", tags=["ingest"])


@app.get("/health")
def health():
    return {"ok": True, "env": settings.env}
