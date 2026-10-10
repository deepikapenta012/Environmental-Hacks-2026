from fastapi import APIRouter
from .auth import router as auth_router
from .claims import router as claims_router
from .admin import router as admin_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(claims_router)
api_router.include_router(admin_router)
