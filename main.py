from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from db import init_db
from limiter import limiter
from routers.video import router as video_router
from routers.qa import router as qa_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Video Assistant", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin, "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "X-OpenAI-Key", "Content-Type"],
)

app.include_router(video_router)
app.include_router(qa_router)
