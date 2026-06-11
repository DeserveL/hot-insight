from __future__ import annotations

from fastapi import APIRouter

from backend.app.domain.models import WEIBO_CHANNEL_ID

router = APIRouter(prefix="/api/v1")


@router.get("/channels")
def channels() -> dict:
    return {
        "items": [
            {"id": WEIBO_CHANNEL_ID, "name": "微博热搜", "enabled": True},
            {"id": "hacker_news", "name": "Hacker News", "enabled": False},
        ]
    }
