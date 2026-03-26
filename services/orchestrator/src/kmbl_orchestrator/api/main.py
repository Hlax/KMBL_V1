"""FastAPI entrypoint — health + internal orchestrator routes (docs/12 §5)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

app = FastAPI(title="KMBL Orchestrator", version="0.1.0")

# Process-local placeholder store — TODO: inject Supabase-backed repository.
_REPO = InMemoryRepository()


def get_repo() -> InMemoryRepository:
    return _REPO


def get_invoker(settings: Settings = Depends(get_settings)) -> DefaultRoleInvoker:
    return DefaultRoleInvoker(settings=settings)


class StartRunBody(BaseModel):
    identity_id: str | None = None
    thread_id: str | None = None
    trigger_type: Literal["prompt", "resume", "schedule", "system"] = "prompt"
    event_input: dict[str, Any] = Field(default_factory=dict)


class StartRunResponse(BaseModel):
    graph_run_id: str
    thread_id: str
    status: str


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


@app.post("/orchestrator/runs/start", response_model=StartRunResponse)
def start_run(
    body: StartRunBody,
    repo: InMemoryRepository = Depends(get_repo),
    invoker: DefaultRoleInvoker = Depends(get_invoker),
    settings: Settings = Depends(get_settings),
) -> StartRunResponse:
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=body.thread_id,
        graph_run_id=None,
        identity_id=body.identity_id,
        trigger_type=body.trigger_type,
        event_input=body.event_input,
    )
    run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={
            "thread_id": tid,
            "graph_run_id": gid,
            "identity_id": body.identity_id,
            "trigger_type": body.trigger_type,
            "event_input": body.event_input,
        },
    )
    return StartRunResponse(graph_run_id=gid, thread_id=tid, status="completed")


@app.get("/orchestrator/runs/{graph_run_id}", response_model=RunStatusResponse)
def run_status(
    graph_run_id: str,
    repo: InMemoryRepository = Depends(get_repo),
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
