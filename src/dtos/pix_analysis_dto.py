from models import Analysis

# Os desfechos que explicam a decisão. Um sinal que passou não é motivo
# de nada, mas aparece em `passed`: quem audita quer saber o que foi
# conferido, não só o que disparou.
REASON_OUTCOMES = ("warn", "two_factor", "reject")


class PixAnalysisDTO:
    """Traduz a análise gravada na resposta do contrato: `key`, `status` e `metadata`.

    O mesmo DTO serve o POST e o GET, e é isso que garante que os dois
    devolvem a MESMA resposta: não existem dois jeitos de montar.

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
