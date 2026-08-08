from fastapi import APIRouter

from app.api import auth, checks, meta, results, settings, stats, stream, targets

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(meta.router)
api_router.include_router(targets.router)
api_router.include_router(results.router)
api_router.include_router(checks.router)
api_router.include_router(stats.router)
api_router.include_router(stream.router)
api_router.include_router(settings.router)
