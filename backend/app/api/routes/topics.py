from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.app.core.config import AppConfig
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import WEIBO_CHANNEL_ID

router = APIRouter(prefix="/api/v1")


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_repository(config: Annotated[AppConfig, Depends(get_config)]):
    repository = AppRepository(config.database_path)
    try:
        yield repository
    finally:
        repository.close()


@router.get("/topics")
def topics(
    repository: Annotated[AppRepository, Depends(get_repository)],
    channel: str = Query(WEIBO_CHANNEL_ID, min_length=1),
    tag: str = "",
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
) -> dict:
    return repository.list_topics(channel_id=channel, tag=tag, limit=limit, cursor=cursor)


@router.get("/topics/{topic_id}")
def topic_detail(topic_id: str, repository: Annotated[AppRepository, Depends(get_repository)]) -> dict:
    topic = repository.get_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.get("/trends/summary")
def trends_summary(repository: Annotated[AppRepository, Depends(get_repository)]) -> dict:
    return repository.get_trends_summary()
