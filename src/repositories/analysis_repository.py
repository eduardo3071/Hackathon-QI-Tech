from datetime import datetime
from typing import Optional
from uuid import uuid4

from database import Context
from models import Analysis, AnalysisRuleResult, AnalysisStatus, AnalysisStatusEvent


class AnalysisRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, analysis_data: dict, status_enumerator: str, event_datetime: datetime) -> Analysis:
        """A análise e o primeiro evento da trilha: de nenhum status para o decidido."""
        analysis = Analysis(**analysis_data)
        analysis.analysis_key = str(uuid4())
        analysis.status = self.get_status(status_enumerator)

        self._add_status_event(analysis, None, analysis.status, event_datetime)

        self.session.add(analysis)
        return analysis

    def change_status(self, analysis: Analysis, new_status_enumerator: str, event_datetime: datetime) -> None:
        """Troca o status e deixa o evento na trilha, do status atual para o novo."""
        new_status = self.get_status(new_status_enumerator)

        self._add_status_event(analysis, analysis.status, new_status, event_datetime)
        analysis.status = new_status

    def add_rule_result(self, analysis: Analysis, rule_result_data: dict) -> None:
        analysis.rule_results.append(AnalysisRuleResult(**rule_result_data))

    def get_status(self, enumerator: str) -> AnalysisStatus:
        return self.session.query(AnalysisStatus).filter(AnalysisStatus.enumerator == enumerator).one()

    def _add_status_event(
        self,
        analysis: Analysis,
        from_status: Optional[AnalysisStatus],
        to_status: AnalysisStatus,
        event_datetime: datetime,
    ) -> None:
        status_event = AnalysisStatusEvent()
        status_event.from_status = from_status
        status_event.to_status = to_status
        status_event.event_datetime = event_datetime

        analysis.status_events.append(status_event)
