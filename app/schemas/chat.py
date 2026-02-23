from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatReference(BaseModel):
    title: str
    href: str
    description: str | None = None


class ChatAction(BaseModel):
    type: Literal["link", "command"]
    label: str
    href: str | None = None
    command: str | None = None


class ChatMessage(BaseModel):
    id: str | None = None
    role: Literal["user", "assistant", "system"]
    content: str
    actions: list[ChatAction] = Field(default_factory=list)
    references: list[ChatReference] = Field(default_factory=list)
    created_at: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ChatSession(BaseModel):
    session_id: str
    title: str | None = None
    created_at: str
    updated_at: str
    meta: dict[str, Any] = Field(default_factory=dict)


class ChatSessionCreateRequest(BaseModel):
    title: str | None = None
    meta: dict[str, Any] | None = None


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSession]


class ChatSessionDetailResponse(BaseModel):
    session: ChatSession
    messages: list[ChatMessage]


class ChatMessageCreateRequest(BaseModel):
    text: str
    context: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    session_id: str | None = None
    text: str
    context: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: ChatMessage


class ChatStreamEvent(BaseModel):
    type: Literal["token", "stage", "message", "done", "error"]
    data: dict[str, Any]

