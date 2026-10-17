from uuid import uuid4

from database import Context
from models import Analysis, AnalysisRuleResult, AnalysisStatus


class AnalysisRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, analysis_data: dict, status_enumerator: str) -> Analysis:
        analysis = Analysis(**analysis_data)
        analysis.analysis_key = str(uuid4())
        analysis.status = self.get_status(status_enumerator)

        self.session.add(analysis)
        return analysis

    def add_rule_result(self, analysis: Analysis, rule_result_data: dict) -> None:
        analysis.rule_results.append(AnalysisRuleResult(**rule_result_data))

    def get_status(self, enumerator: str) -> AnalysisStatus:
        return self.session.query(AnalysisStatus).filter(AnalysisStatus.enumerator == enumerator).one()
