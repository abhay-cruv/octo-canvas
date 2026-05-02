"""Dev-only event injection — slice 5a.

Mounted only when `settings.allow_internal_endpoints` is true. Lets a
developer (or pytest) drive the WS without a real agent yet.
"""

from beanie import PydanticObjectId
from db.models import Task, User
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from shared_models.wire_protocol import DebugEvent

from ..middleware.auth import require_user
from ..services.event_store import append_event

router = APIRouter()


class InjectEventBody(BaseModel):
    message: str


class CreateTaskResponse(BaseModel):
    id: str


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(user: User = Depends(require_user)) -> CreateTaskResponse:
    """Insert a placeholder `Task` owned by the caller. Slice 6 replaces this
    with a real `POST /api/tasks` that takes a prompt + repo_id."""
    task = Task(user_id=user.id)  # type: ignore[arg-type]
    await task.insert()
    assert task.id is not None
    return CreateTaskResponse(id=str(task.id))


@router.post("/tasks/{task_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def inject_event(
    task_id: str,
    body: InjectEventBody,
    request: Request,
    user: User = Depends(require_user),
) -> dict[str, int | str]:
    """Append a `DebugEvent` to the task's event log + publish to Redis. Seq
    is allocated by `append_event`; the request body is just `message`."""

    try:
        oid = PydanticObjectId(task_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task_not_found") from exc

    task = await Task.get(oid)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task_not_found")
    if task.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    redis_handle = getattr(request.app.state, "redis_handle", None)
    event = await append_event(
        oid,
        DebugEvent(seq=0, message=body.message),
        redis=redis_handle,
    )
    return {"task_id": str(oid), "seq": event.seq}
