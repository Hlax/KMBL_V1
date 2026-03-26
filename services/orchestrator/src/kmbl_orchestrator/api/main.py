"""FastAPI entrypoint — health + internal orchestrator routes (docs/12 §5)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.errors import RoleInvocationFailed
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.factory import get_repository
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

app = FastAPI(title="KMBL Orchestrator", version="0.1.0")


def get_repo(settings: Settings = Depends(get_settings)) -> Repository:
    return get_repository(settings)


def get_invoker(settings: Settings = Depends(get_settings)) -> DefaultRoleInvoker:
    return DefaultRoleInvoker(settings=settings)


class StartRunBody(BaseModel):
    """Request body for starting a graph run. Omit identity_id / thread_id for a fresh run."""

    model_config = ConfigDict(
        json_schema_extra={
            # Empty object = safest default in Swagger (do not send the literal "string" for UUIDs).
            "example": {}
        }
    )

    identity_id: UUID | None = Field(
        default=None,
        description=(
            "Optional identity UUID. OpenAPI shows type 'string' because UUIDs are serialized "
            "as strings — use a real UUID, null, or omit this field. Never send the word 'string'."
        ),
    )
    thread_id: UUID | None = Field(
        default=None,
        description=(
            "Optional existing thread UUID. Same as identity_id: real UUID, null, or omit. "
            "Never send the placeholder 'string'."
        ),
    )
    trigger_type: Literal["prompt", "resume", "schedule", "system"] = "prompt"
    event_input: dict[str, Any] = Field(default_factory=dict)


class StartRunResponse(BaseModel):
    graph_run_id: str
    thread_id: str
    status: Literal["completed", "failed"]


class RunStatusResponse(BaseModel):
    graph_run_id: str
    thread_id: str
    status: str
    iteration_index: int | None = None
    decision: str | None = None
    snapshot: dict[str, Any] | None = None


class InvokeRoleBody(BaseModel):
    """Internal shape from docs/12 §6 — thin passthrough for future wiring."""

    role_type: Literal["planner", "generator", "evaluator"]
    payload: dict[str, Any]


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "status": "ok",
        "kiloclaw_base_url": settings.kiloclaw_base_url,
    }


@app.post(
    "/orchestrator/runs/start",
    response_model=StartRunResponse,
    summary="Start a graph run",
    description=(
        "Use an **empty JSON object `{}`** for a normal fresh run. "
        "Swagger may list UUID fields as type `string` in the schema; that is normal. "
        "Do not paste placeholder values like `\"string\"` for UUID fields — that causes 422 or runtime errors."
    ),
)
def start_run(
    body: Annotated[
        StartRunBody,
        Body(
            openapi_examples={
                "fresh_run": {
                    "summary": "Fresh run (recommended)",
                    "description": "Empty body. New thread_id and graph_run_id are created.",
                    "value": {},
                },
                "explicit_defaults": {
                    "summary": "Explicit trigger only",
                    "value": {"trigger_type": "prompt", "event_input": {}},
                },
                "with_uuids": {
                    "summary": "Resume / tie to identity (real UUIDs only)",
                    "description": "Replace with real UUIDs from your database — not the word 'string'.",
                    "value": {
                        "identity_id": "00000000-0000-0000-0000-000000000001",
                        "thread_id": "00000000-0000-0000-0000-000000000002",
                        "trigger_type": "prompt",
                        "event_input": {},
                    },
                },
            },
        ),
    ],
    repo: Repository = Depends(get_repo),
    invoker: DefaultRoleInvoker = Depends(get_invoker),
    settings: Settings = Depends(get_settings),
) -> StartRunResponse:
    """Create thread + graph_run rows, then run the LangGraph (persist before graph)."""
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=str(body.thread_id) if body.thread_id is not None else None,
        graph_run_id=None,
        identity_id=str(body.identity_id) if body.identity_id is not None else None,
        trigger_type=body.trigger_type,
        event_input=body.event_input,
    )
    try:
        run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={
                "thread_id": tid,
                "graph_run_id": gid,
                "identity_id": str(body.identity_id) if body.identity_id is not None else None,
                "trigger_type": body.trigger_type,
                "event_input": body.event_input,
            },
        )
    except RoleInvocationFailed:
        return StartRunResponse(graph_run_id=gid, thread_id=tid, status="failed")
    return StartRunResponse(graph_run_id=gid, thread_id=tid, status="completed")


@app.get("/orchestrator/runs/{graph_run_id}", response_model=RunStatusResponse)
def run_status(
    graph_run_id: str,
    repo: Repository = Depends(get_repo),
) -> RunStatusResponse:
    gr = repo.get_graph_run(UUID(graph_run_id))
    if gr is None:
        raise HTTPException(status_code=404, detail="graph_run not found")
    snap = repo.get_run_snapshot(UUID(graph_run_id))
    iteration = None
    decision = None
    if snap:
        iteration = snap.get("iteration_index")
        decision = snap.get("decision")
    return RunStatusResponse(
        graph_run_id=str(gr.graph_run_id),
        thread_id=str(gr.thread_id),
        status=gr.status,
        iteration_index=iteration,
        decision=decision,
        snapshot=snap,
    )


@app.post("/orchestrator/invoke-role")
def invoke_role(
    body: InvokeRoleBody,
    invoker: DefaultRoleInvoker = Depends(get_invoker),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Internal dev hook — production path is the LangGraph nodes.

    TODO: Remove or protect when KiloClaw is only reachable from orchestrator graph.
    """
    # Minimal synthetic IDs for standalone calls
    gid = UUID(int=0)
    tid = UUID(int=1)
    key = {
        "planner": settings.kiloclaw_planner_config_key,
        "generator": settings.kiloclaw_generator_config_key,
        "evaluator": settings.kiloclaw_evaluator_config_key,
    }[body.role_type]
    _inv, raw = invoker.invoke(
        graph_run_id=gid,
        thread_id=tid,
        role_type=body.role_type,
        provider_config_key=key,
        input_payload=body.payload,
        iteration_index=0,
    )
    return {"output": raw}


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "kmbl_orchestrator.api.main:app",
        host=s.orchestrator_host,
        port=s.orchestrator_port,
        reload=s.orchestrator_reload,
    )


if __name__ == "__main__":
    run()
