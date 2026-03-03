from app.schemas.detect import (
    ClaimItem,
    EvidenceItem,
    ReportResponse,
    SimulateResponse,
    StrategyConfig,
)
from app.skills.base import SkillContext

from .registry import SkillRegistry


class OrchestratorEngine:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def run_claims(
        self, text: str, strategy: StrategyConfig | None = None
    ) -> list[ClaimItem]:
        skill = self.registry.get("claim_extractor")
        ctx = SkillContext()
        ctx.strategy = strategy
        return skill.run(text, ctx)

    def run_evidence(
        self,
        text: str | None = None,
        claims: list[ClaimItem] | None = None,
        strategy: StrategyConfig | None = None,
    ) -> list[EvidenceItem]:
        resolved_claims = claims or self.run_claims(text or "", strategy=strategy)
        skill = self.registry.get("evidence_retriever")
        ctx = SkillContext()
        ctx.strategy = strategy
        return skill.run(resolved_claims, ctx)

    def run_report(
        self,
        text: str | None = None,
        claims: list[ClaimItem] | None = None,
        evidences: list[EvidenceItem] | None = None,
        strategy: StrategyConfig | None = None,
        source_url: str | None = None,
        source_title: str | None = None,
        source_publish_date: str | None = None,
    ) -> dict:
        resolved_claims = claims or self.run_claims(text or "", strategy=strategy)
        resolved_evidences = evidences or self.run_evidence(
            claims=resolved_claims, strategy=strategy
        )
        skill = self.registry.get("report_builder")
        ctx = SkillContext()
        ctx.strategy = strategy
        return skill.run(
            (
                resolved_claims,
                resolved_evidences,
                text or "",
                source_url,
                source_title,
                source_publish_date,
            ),
            ctx,
        )

    def run_simulation(
        self,
        text: str,
        time_window_hours: int,
        platform: str,
        comments: list[str],
        claims: list[ClaimItem] | None = None,
        evidences: list[EvidenceItem] | None = None,
        report: ReportResponse | None = None,
    ) -> SimulateResponse:
        skill = self.registry.get("opinion_simulator")
        return skill.run(
            (text, time_window_hours, platform, comments, claims, evidences, report),
            SkillContext(),
        )
