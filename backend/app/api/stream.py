"""SSE 实时结果推送。"""
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth import require_auth
from app.storage import ResultStore

router = APIRouter(prefix="/stream", tags=["stream"], dependencies=[Depends(require_auth)])

KEEPALIVE_INTERVAL = 15.0


@router.get("")
async def stream(request: Request) -> StreamingResponse:
    store: ResultStore = request.app.state.result_store
    queue = store.subscribe()

    async def generate():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                    yield f"event: result\ndata: {result.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            store.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
