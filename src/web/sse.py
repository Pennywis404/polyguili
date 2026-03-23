"""
Server-Sent Events endpoint pour les mises a jour temps reel.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

sse_router = APIRouter()


@sse_router.get("/api/stream")
async def event_stream(request: Request):
    event_bus = request.app.state.event_bus

    async def generate():
        queue = await event_bus.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {
                        "event": event.type,
                        "data": json.dumps(event.data, default=str),
                    }
                except asyncio.TimeoutError:
                    # Keepalive
                    yield {
                        "event": "keepalive",
                        "data": json.dumps({"time": datetime.now(timezone.utc).isoformat()}),
                    }
        finally:
            await event_bus.unsubscribe(queue)

    return EventSourceResponse(generate())
