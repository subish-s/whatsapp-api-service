from fastapi import APIRouter
from app.api.chats import router as chats_router
from app.api.chatting import router as chatting_router
from app.api.sessions import router as sessions_router

api_router = APIRouter()
api_router.include_router(sessions_router)
api_router.include_router(chatting_router)
api_router.include_router(chats_router)
