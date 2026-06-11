from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.app.core.config import AppConfig
from backend.app.domain.models import now_iso

router = APIRouter()


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


@router.get("/health")
def health(config: Annotated[AppConfig, Depends(get_config)]) -> dict:
    return {
        "ok": True,
        "service": "hot-insight-api",
        "time": now_iso(),
        "database_path": str(config.database_path),
    }
