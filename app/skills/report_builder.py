from app.schemas.detect import ClaimItem, EvidenceItem
from app.services.pipeline import build_report
from app.skills.base import SkillContext


class ReportBuilderSkill:
    name = "report_builder"

    def run(
        self,
        payload: tuple[
            list[ClaimItem],
            list[EvidenceItem],
            str,
            str | None,
            str | None,
            str | None,
        ],
        context: SkillContext,
    ) -> dict:
        context.metadata["last_skill"] = self.name
        (
            claims,
            evidences,
            original_text,
            source_url,
            source_title,
            source_publish_date,
        ) = payload
        return build_report(
            claims,
            evidences,
            original_text=original_text,
            strategy=context.strategy,
            source_url=source_url,
            source_title=source_title,
            source_publish_date=source_publish_date,
        )
