from dataclasses import dataclass
from typing import List, Optional

from controllers.rules.signal_result import APP, ATO, MULE, REJECT, TWO_FACTOR, SignalResult
from models import AnalysisStatus

# As tipologias que a decisão pode apontar, e a ação recomendada de cada
# desfecho. `hold_timer` é a recusa por suspeita de golpe: em produção,
# viraria a retenção de 30/60 minutos do BCB em vez de uma recusa seca.
FRAUD_MARKER = "fraud_marker"
ACCOUNT_TAKEOVER = "account_takeover"
APP_SCAM = "app_scam"
MULE_ACCOUNT = "mule_account"

NONE = "none"
WARN = "warn"
STEP_UP = "step_up"
HOLD_TIMER = "hold_timer"
BLOCK = "block"


@dataclass(frozen=True)
class Decision:
    status: str
    typology: Optional[str]
    recommended_action: str
    scores: dict


class DecisionMaker:
    """Junta os vereditos dos sinais numa decisão só.

    A decisão é pelo TIPO de fraude, não só pela intensidade:
      • conta invadida (ato) → 2FA, porque o invasor não tem o segundo fator;
      • golpe (app) e conta laranja (mule) → recusa, porque a vítima
        manipulada passa no 2FA (EBA-ECB 2025).

    Precedência: rejected > two_factor_required > approved. Dentro de
    cada desfecho, a ordem dos `if` abaixo diz qual motivo dá nome à
    decisão quando há mais de um.
    """

    def decide(self, results: List[SignalResult], cuts: dict, deep_layer_timed_out: bool) -> Decision:
        scores = {ATO: 0, APP: 0, MULE: 0}
        for result in results:
            if result.typology is not None:
                scores[result.typology] = scores[result.typology] + result.points

        hard_rejects = [result for result in results if result.outcome == REJECT]
        two_factors = [result for result in results if result.outcome == TWO_FACTOR]

        # A combinação explícita entre regras: um 2FA que, junto com cara
        # de golpe ou de conta laranja, vira recusa (o horário noturno).
        escalated = [
            result for result in two_factors if any(scores[typology] > 0 for typology in result.escalates_with)
        ]

        mule_above_cut = scores[MULE] >= cuts["mule_cut"]
        app_above_cut = scores[APP] >= cuts["app_cut"]

        if any(result.rule_code == "MARCACAO" for result in hard_rejects):
            return Decision(AnalysisStatus.REJECTED, FRAUD_MARKER, BLOCK, scores)

        if mule_above_cut:
            return Decision(AnalysisStatus.REJECTED, MULE_ACCOUNT, BLOCK, scores)

        if app_above_cut:
            return Decision(AnalysisStatus.REJECTED, APP_SCAM, HOLD_TIMER, scores)

        if hard_rejects:
            return Decision(AnalysisStatus.REJECTED, ACCOUNT_TAKEOVER, BLOCK, scores)

        if escalated:
            if scores[MULE] > 0:
                return Decision(AnalysisStatus.REJECTED, MULE_ACCOUNT, BLOCK, scores)
            return Decision(AnalysisStatus.REJECTED, APP_SCAM, HOLD_TIMER, scores)

        takeover = scores[ATO] >= cuts["ato_cut"] or any(result.typology == ATO for result in two_factors)

        if takeover:
            return Decision(AnalysisStatus.TWO_FACTOR_REQUIRED, ACCOUNT_TAKEOVER, STEP_UP, scores)

        # A camada profunda só roda quando já havia sinal de risco. Se ela
        # estourou o tempo, decidir no escuro seria aprovar com dúvida: o
        # seguro é pedir 2FA com o que já se sabe.
        if two_factors or deep_layer_timed_out:
            return Decision(AnalysisStatus.TWO_FACTOR_REQUIRED, None, STEP_UP, scores)

        if scores[APP] >= cuts["app_warn_cut"]:
            return Decision(AnalysisStatus.APPROVED, APP_SCAM, WARN, scores)

        return Decision(AnalysisStatus.APPROVED, None, NONE, scores)
