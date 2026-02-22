from fastapi import APIRouter, HTTPException, Query

from app.schemas.detect import (
    HistoryDetailResponse,
    HistoryFeedbackRequest,
    HistoryListResponse,
    SimulateResponse,
    ContentDraftData,
)
from app.services.history_store import (
    get_history,
    list_history,
    save_feedback,
    update_simulation,
    update_content,
)

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=HistoryListResponse)
def history_list(limit: int = Query(default=20, ge=1, le=100)) -> HistoryListResponse:
    return HistoryListResponse(items=list_history(limit=limit))


@router.get("/{record_id}", response_model=HistoryDetailResponse)
def history_detail(record_id: str) -> HistoryDetailResponse:
    record = get_history(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="history not found")
    return HistoryDetailResponse(**record)


@router.post("/{record_id}/feedback")
def history_feedback(record_id: str, payload: HistoryFeedbackRequest) -> dict[str, str]:
    ok = save_feedback(record_id=record_id, status=payload.status, note=payload.note)
    if not ok:
        raise HTTPException(status_code=404, detail="history not found")
    return {"status": "ok"}


@router.post("/{record_id}/simulation")
def history_update_simulation(record_id: str, payload: SimulateResponse) -> dict[str, str]:
    ok = update_simulation(record_id=record_id, simulation=payload.model_dump())
    if not ok:
        raise HTTPException(status_code=404, detail="history not found")
    return {"status": "ok"}


@router.post("/{record_id}/content")
def history_update_content(record_id: str, payload: ContentDraftData) -> dict[str, str]:
    """更新历史记录的应对内容生成结果"""
    ok = update_content(record_id=record_id, content=payload.model_dump())
    if not ok:
        raise HTTPException(status_code=404, detail="history not found")
    return {"status": "ok"}
