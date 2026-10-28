from fastapi import APIRouter

from src.api.application import applications, calculations, communications, customers, eligibility_tools, knowledge, reviews, sessions


router = APIRouter()
for module in (sessions, customers, knowledge, calculations, eligibility_tools, applications, reviews, communications):
    router.include_router(module.router)