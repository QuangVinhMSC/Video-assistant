from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from routers.video import router as video_router
from routers.qa import router as qa_router

app = FastAPI(title="Video Assistant")
app.include_router(video_router)
app.include_router(qa_router)
