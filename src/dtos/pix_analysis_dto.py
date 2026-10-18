from datetime import timezone

from models import Analysis

ML_SIGNAL = "ANOMALIA.ml"
ML_STATUS = {"pass": "evaluated", "warn": "evaluated", "not_evaluated": "not_evaluated", "not_needed": "not_needed"}

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
        ml_result = None
        not_evaluated = []
        not_needed = []
        passed = []

        for rule_result in analysis.rule_results:
            if rule_result.signal_code == ML_SIGNAL:
                ml_result = rule_result

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
            "ml": PixAnalysisDTO.ml_to_dict(analysis.policy_version.ml_mode, ml_result),
            "latency_ms": analysis.latency_ms,
        }

        # O status com que a análise NASCEU, e não o atual: é a resposta do
        # POST, e o reenvio do mesmo POST tem de receber a mesma resposta,
        # mesmo depois do retorno do 2FA. O status atual mora no dossiê.
        return {
            "key": analysis.analysis_key,
            "status": analysis.birth_event.to_status.enumerator,
            "metadata": metadata,
        }

    @staticmethod
    def obj_to_dossier_dict(analysis: Analysis) -> dict:
        """A decisão mais a trilha de status: por onde a análise passou, não só onde está.

        O `status` é o ATUAL — depois de um retorno do 2FA, o resultado
        final. O `metadata` conta de onde ele veio: o status inicial, como
        o 2FA terminou (ou `None`, se não voltou ou nem foi pedido) e a
        trilha inteira.
        """
        analysis_dto = PixAnalysisDTO.obj_to_dict(analysis)
        analysis_dto["status"] = analysis.status.enumerator

        two_factor = None
        two_factor_event = analysis.two_factor_event
        if two_factor_event is not None:
            two_factor = {
                "result": two_factor_event.two_factor_result,
                "completed_at": PixAnalysisDTO.datetime_to_str(two_factor_event.event_datetime),
            }

        metadata = analysis_dto["metadata"]
        metadata["initial_status"] = analysis.birth_event.to_status.enumerator
        metadata["two_factor"] = two_factor
        metadata["status_history"] = [
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
            "event_datetime": PixAnalysisDTO.datetime_to_str(status_event.event_datetime),
        }

    @staticmethod
    def datetime_to_str(value) -> str:
        """Em UTC, sempre: o mesmo instante sai escrito do mesmo jeito,
        tenha ele chegado com -03:00 no PATCH ou voltado do banco."""
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def ml_to_dict(ml_mode: str, ml_result) -> dict:
        """O modelo de anomalia em destaque: o modo, o escore e as 3 features que mais fugiram do normal.

        `status` diz se o modelo rodou (`evaluated`), se faltou o modelo
        (`not_evaluated`) ou se o Pix saiu pelo caminho rápido e ele nem
        precisou rodar (`not_needed`).
        """
        observed = {}
        status = "not_evaluated"
        if ml_result is not None:
            observed = ml_result.observed
            status = ML_STATUS.get(ml_result.outcome, "evaluated")

        return {
            "mode": ml_mode,
            "status": status,
            "model_version": observed.get("model_version"),
            "anomaly_score": observed.get("anomaly_score"),
            "top_features": observed.get("top_features", []),
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
