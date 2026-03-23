import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class EventBus:
    """Bus d'evenements pub/sub async avec support multi-subscribers."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    async def publish(self, event: Event) -> None:
        async with self._lock:
            dead_queues = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("Event queue full, dropping event %s", event.type)
                    # Drain oldest event and retry
                    try:
                        queue.get_nowait()
                        queue.put_nowait(event)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        dead_queues.append(queue)
            for q in dead_queues:
                self._subscribers.remove(q)
