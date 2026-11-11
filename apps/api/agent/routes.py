"""Chat routes. A conversation is private to the user who started it."""

import os
from contextlib import contextmanager
from typing import Annotated

import psycopg
from fastapi import APIRouter, Path, Request
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from pydantic import BaseModel, StringConstraints

from apps.api import actions
from apps.api.agent import graph, tools
from apps.api.agent.providers import provider_from_environment
from apps.api.auth import Viewer
from apps.api.db import Db

router = APIRouter(tags=["chat"])

ConversationId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class MessageIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Claim(BaseModel):
    text: str
    evidence: list[str]


class Answer(BaseModel):
    summary: str
    observations: list[Claim]
    hypotheses: list[Claim]
    data_notes: list[str]
    evidence: dict[str, dict]
    tool_calls: list[dict]
    dropped_claims: list[dict]
    proposals: list[actions.Proposal]  # actions drafted for the user to approve, edit or reject


@contextmanager
def agent_runtime():
    """The compiled graph with its checkpointer, and the model provider. Lives as long as the API."""
    # The checkpointer creates unqualified tables and an index CONCURRENTLY, so it gets its own
    # autocommit connection whose search path puts its tables in the agent schema.
    # shortcut: one connection shared by all requests behind the checkpointer's lock; give it a
    # connection pool when many conversations run at once.
    with psycopg.connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-c search_path=agent",
    ) as conn:
        conn.execute("create schema if not exists agent")
        conn.execute("select pg_advisory_lock(727275)")  # one process runs its setup at a time
        try:
            saver = PostgresSaver(conn)
            saver.setup()
        finally:
            conn.execute("select pg_advisory_unlock(727275)")
        yield {
            "graph": graph.build(saver),
            "provider": provider_from_environment([tools.schema(name) for name in tools.TOOLS]),
        }


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: ConversationId, message: MessageIn, request: Request, db: Db, user: Viewer
) -> Answer:
    runtime = request.app.state.agent
    thread = graph.thread_id(user, conversation_id)
    answer = graph.ask(runtime["graph"], db, runtime["provider"], thread, message.message)
    return answer | {"proposals": actions.save(db, user, conversation_id, answer.pop("drafts"))}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: ConversationId, request: Request, user: Viewer) -> list[dict]:
    """The earlier questions and answer summaries in this conversation; empty when there are none."""
    saved = request.app.state.agent["graph"].get_state(
        {"configurable": {"thread_id": graph.thread_id(user, conversation_id)}}
    )
    return saved.values.get("history", [])
