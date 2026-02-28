from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.detect import (
    ClaimItem,
    ContentDraftData,
    DetectResponse,
    EvidenceItem,
    ReportResponse,
    SimulateResponse,
)


class ExportDataRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input_text: str = Field(alias="inputText")
    detect_data: DetectResponse | None = Field(default=None, alias="detectData")
    claims: list[ClaimItem] = Field(default_factory=list)
    evidences: list[EvidenceItem] = Field(default_factory=list)
    report: ReportResponse | None = None
    simulation: SimulateResponse | None = None
    content: ContentDraftData | None = None
    exported_at: str | None = Field(default=None, alias="exportedAt")
