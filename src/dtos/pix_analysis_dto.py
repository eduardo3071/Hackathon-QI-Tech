from models import Analysis

# Os desfechos que explicam a decisão. Um sinal que passou não é motivo
# de nada, mas aparece em `passed`: quem audita quer saber o que foi
# conferido, não só o que disparou.
REASON_OUTCOMES = ("warn", "two_factor", "reject")


class PixAnalysisDTO:
    """Traduz a análise gravada na resposta do contrato: `key`, `status` e `metadata`.

    O mesmo DTO serve o POST e o GET, e é isso que garante que a decisão
    sai igual nos dois: não existem dois jeitos de montar. O GET é o
    dossiê — a decisão (`obj_to_dict`) mais a história dela
    (`obj_to_dossier_dict`), como o `obj_to_dict` e o
    `obj_to_simplified_dict` do sample_entity do Base Service.

    Repare no que não sai: nenhum `id` interno, nenhuma coluna de
    `features`. O que este dicionário monta é exatamente o que vai para o
    cliente — não existe ninguém depois dele conferindo a forma.
    """

    @staticmethod
    def obj_to_dict(analysis: Analysis) -> dict:
        reasons = []
        not_evaluated = []
        not_needed = []
        passed = []

        for rule_result in analysis.rule_results:
            if rule_result.outcome == "not_evaluated":
                not_evaluated.append({"signal": rule_result.signal_code, "reason": rule_result.message})
            elif rule_result.outcome == "not_needed":
                not_needed.append({"signal": rule_result.signal_code, "reason": rule_result.message})
            elif rule_result.outcome in REASON_OUTCOMES or rule_result.points > 0:
                reasons.append(PixAnalysisDTO.rule_result_to_dict(rule_result))
            else:
                passed.append(rule_result.signal_code)

        metadata = {
            "policy_version": analysis.policy_version.version,
            "path": analysis.path,
            "layers": list(analysis.layers),
            "typology": analysis.typology,
            "recommended_action": analysis.recommended_action,
            "step_up_reason": analysis.step_up_reason,
            "step_up_method": analysis.step_up_method,
            "scam_warning": analysis.scam_warning,
            "scores": {
                "ato": analysis.score_ato,
                "app": analysis.score_app,
                "mule": analysis.score_mule,
            },
            "reasons": reasons,
            "not_evaluated": not_evaluated,
            "not_needed": not_needed,
            "passed": passed,
        }

        return {
            "key": analysis.analysis_key,
            "status": analysis.status.enumerator,
            "metadata": metadata,
        }

    @staticmethod
    def obj_to_dossier_dict(analysis: Analysis) -> dict:
        """A decisão mais a trilha de status: por onde a análise passou, não só onde está."""
        analysis_dto = PixAnalysisDTO.obj_to_dict(analysis)
        analysis_dto["metadata"]["status_history"] = [
            PixAnalysisDTO.status_event_to_dict(status_event) for status_event in analysis.status_events
        ]

        return analysis_dto

    @staticmethod
    def status_event_to_dict(status_event) -> dict:
        from_status = None
        if status_event.from_status is not None:
            from_status = status_event.from_status.enumerator

        return {
            "from_status": from_status,
            "to_status": status_event.to_status.enumerator,
            "event_datetime": status_event.event_datetime.isoformat(),
        }

    @staticmethod
    def rule_result_to_dict(rule_result) -> dict:
        return {
            "signal": rule_result.signal_code,
            "outcome": rule_result.outcome,
            "typology": rule_result.typology,
            "points": rule_result.points,
            "observed": rule_result.observed,
            "threshold": rule_result.threshold,
            "message": rule_result.message,
        }
