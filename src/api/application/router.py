from fastapi import APIRouter

from src.api.application import applications, calculations, communications, customers, knowledge, reviews, sessions


router = APIRouter()
for module in (sessions, customers, knowledge, calculations, applications, reviews, communications):
    router.include_router(module.router)