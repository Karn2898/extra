"""Compose the conversation API's domain routers."""

from fastapi import APIRouter

from agent_manager.api.routes.approvals import router as approvals_router
from agent_manager.api.routes.auth import router as auth_router
from agent_manager.api.routes.conversations import router as conversations_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(conversations_router)
router.include_router(approvals_router)
