"""V5-4 AI 教练独立聊天 API：POST 发消息 / GET 历史 / DELETE 清空。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.db import get_session
from app.services import coach_chat as svc

router = APIRouter(
    prefix="/api/coach/chat",
    tags=["coach-chat"],
    dependencies=[Depends(require_auth)],
)


class ChatMessageRequest(BaseModel):
    content: str
    client_request_id: str = Field(min_length=1, max_length=64)


def _serialize_message(msg) -> dict:
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "model": msg.model,
        "prompt_tokens": msg.prompt_tokens,
        "completion_tokens": msg.completion_tokens,
        "cost_estimate": msg.cost_estimate,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.post("")
def post_message(
    payload: ChatMessageRequest,
    session: Session = Depends(get_session),
) -> dict:
    """发送独立聊天消息：落用户消息 → 调 LLM → 落 assistant 回复。"""
    try:
        user_msg, assistant_msg = svc.post_message(
            session, payload.content, payload.client_request_id
        )
    except svc.ChatMessageLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "user_message": _serialize_message(user_msg),
        "assistant_message": _serialize_message(assistant_msg),
    }


@router.get("")
def list_messages(session: Session = Depends(get_session)) -> dict:
    """独立聊天历史（按时间正序）；不返回 client_request_id。"""
    messages = svc.list_messages(session)
    return {"messages": [_serialize_message(m) for m in messages]}


@router.delete("")
def clear_messages(session: Session = Depends(get_session)) -> dict:
    """hard delete 清空全部独立聊天消息。"""
    deleted = svc.clear_messages(session)
    return {"ok": True, "deleted": deleted}
