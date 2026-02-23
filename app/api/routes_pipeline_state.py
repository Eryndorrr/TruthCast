from __future__ import annotations

from fastapi import APIRouter
from fastapi import Query

from app.schemas.pipeline_state import (
    PipelineStateLatestResponse,
    PipelineStateUpsertRequest,
    PipelineStateUpsertResponse,
    PhaseSnapshot,
)
from app.services.pipeline_state_store import load_latest_task, load_task, upsert_phase_snapshot


router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/save-phase", response_model=PipelineStateUpsertResponse)
def save_phase(payload: PipelineStateUpsertRequest) -> PipelineStateUpsertResponse:
    updated_at = upsert_phase_snapshot(
        task_id=payload.task_id,
        input_text=payload.input_text,
        phases=payload.phases,
        phase=payload.phase,
        status=payload.status,
        duration_ms=payload.duration_ms,
        error_message=payload.error_message,
        payload=payload.payload,
        meta=payload.meta,
    )
    return PipelineStateUpsertResponse(
        task_id=payload.task_id,
        phase=payload.phase,
        status=payload.status,
        updated_at=updated_at,
    )


@router.get("/load-latest", response_model=PipelineStateLatestResponse)
def load_latest(task_id: str | None = Query(default=None)) -> PipelineStateLatestResponse:
    latest = load_task(task_id) if task_id else load_latest_task()
    if latest is None:
        return PipelineStateLatestResponse(
            task_id="",
            input_text="",
            phases={
                "detect": "idle",
                "claims": "idle",
                "evidence": "idle",
                "report": "idle",
                "simulation": "idle",
                "content": "idle",
            },
            meta={},
            updated_at="",
            snapshots=[],
        )

    return PipelineStateLatestResponse(
        task_id=latest["task_id"],
        input_text=latest["input_text"],
        phases=latest["phases"],
        meta=latest.get("meta") or {},
        updated_at=latest["updated_at"],
        snapshots=[PhaseSnapshot(**s) for s in latest.get("snapshots") or []],
    )

