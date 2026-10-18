from dataclasses import dataclass
from typing import List, Optional

from controllers.rules.signal_result import APP, ATO, MULE, REJECT, TWO_FACTOR, SignalResult
from models import AnalysisStatus

# As tipologias que a decisão pode apontar.
FRAUD_MARKER = "fraud_marker"
ACCOUNT_TAKEOVER = "account_takeover"
APP_SCAM = "app_scam"
MULE_ACCOUNT = "mule_account"

# A ação recomendada de cada desfecho.
NONE = "none"
WARN = "warn"
STEP_UP = "step_up"
BLOCK = "block"

# POR QUE o 2FA foi pedido...
STEP_UP_ACCOUNT_TAKEOVER = "account_takeover"
STEP_UP_POSSIBLE_SCAM = "possible_scam"
STEP_UP_LIMIT = "limit"

# ...e COMO. Para invasão, biometria facial com prova de vida: no SIM swap
# o fraudador recebe o SMS, e o rosto é a prova que ele não tem. Para
# golpe e limite, confirmação no app: a vítima manipulada passa em
# qualquer segundo fator, e a fricção útil é o aviso de golpe na tela.
FACE_LIVENESS = "face_liveness"
IN_APP_CONFIRMATION = "in_app_confirmation"


@dataclass(frozen=True)
class Decision:
    status: str
    typology: Optional[str]
    recommended_action: str
    scores: dict
    step_up_reason: Optional[str] = None
    step_up_method: Optional[str] = None
    scam_warning: bool = False


class DecisionMaker:
    """Junta os vereditos dos sinais numa decisão só.

    O slide da QI Tech define as duas pontas: reprovar é "bloquear quando o
    risco é claro"; 2FA é "fricção só onde há dúvida". Por isso:

      • `rejected` só com evidência dura — marcação de fraude, conta sendo
        esvaziada (velocidade no corte de recusa), recebedor pago por conta
        marcada nas últimas 24 h, ou conta laranja vista por DOIS sinais
        diferentes. Um sinal de laranja sozinho, por mais
        pontos que tenha, é dúvida: pode ser o vendedor de carro usado que
        acabou de abrir conta;
      • `two_factor_required` quando há dúvida, dizendo POR QUE e COMO;
      • `approved` com aviso quando o golpe tem sinal fraco.

    Precedência: rejected > two_factor_required > approved.
    """

    def decide(
        self,
        results: List[SignalResult],
        cuts: dict,
        deep_layer_timed_out: bool,
        deep_layer_reason: Optional[str],
        strong_step_up: bool = False,
    ) -> Decision:
        scores = {ATO: 0, APP: 0, MULE: 0}
        for result in results:
            if result.typology is not None:
                scores[result.typology] = scores[result.typology] + result.points

        hard_rejects = [result for result in results if result.outcome == REJECT]
        two_factors = [result for result in results if result.outcome == TWO_FACTOR]
        mule_signals = {result.signal_code for result in results if result.typology == MULE and result.points > 0}

        mule_above_cut = scores[MULE] >= cuts["mule_cut"]

        if any(result.rule_code == "MARCACAO" for result in hard_rejects):
            return Decision(AnalysisStatus.REJECTED, FRAUD_MARKER, BLOCK, scores)

        if mule_above_cut and len(mule_signals) >= cuts["mule_min_distinct_signals"]:
            return Decision(AnalysisStatus.REJECTED, MULE_ACCOUNT, BLOCK, scores)

        # Recusa dura de conta laranja (proximidade de conta marcada a 1
        # salto) tem a tipologia dela; a que sobra é a conta sendo esvaziada.
        if any(result.typology == MULE for result in hard_rejects):
            return Decision(AnalysisStatus.REJECTED, MULE_ACCOUNT, BLOCK, scores)

        if hard_rejects:
            return Decision(AnalysisStatus.REJECTED, ACCOUNT_TAKEOVER, BLOCK, scores)

        takeover = scores[ATO] >= cuts["ato_cut"] or any(result.typology == ATO for result in two_factors)
        app_above_cut = scores[APP] >= cuts["app_cut"]
        scam = app_above_cut or mule_above_cut
        limit = any(result.typology is None for result in two_factors)

        # A camada profunda só roda quando já havia sinal de risco. Se ela
        # estourou o tempo, decidir no escuro seria aprovar com dúvida: o
        # seguro é pedir 2FA pelo motivo que levou até ela.
        if deep_layer_timed_out:
            takeover = takeover or deep_layer_reason == STEP_UP_ACCOUNT_TAKEOVER
            scam = scam or deep_layer_reason == STEP_UP_POSSIBLE_SCAM
            limit = limit or deep_layer_reason == STEP_UP_LIMIT

        if takeover:
            # Invasão e golpe ao mesmo tempo: o rosto prova quem opera, e o
            # aviso de golpe protege o titular que está sendo manipulado.
            return Decision(
                AnalysisStatus.TWO_FACTOR_REQUIRED,
                ACCOUNT_TAKEOVER,
                STEP_UP,
                scores,
                step_up_reason=STEP_UP_ACCOUNT_TAKEOVER,
                step_up_method=FACE_LIVENESS,
                scam_warning=scam,
            )

        # Golpe e limite pedem a confirmação no app, a menos que o contexto
        # diga que quem segura o celular pode não ser o titular: aí, biometria.
        method = FACE_LIVENESS if strong_step_up else IN_APP_CONFIRMATION

        if scam:
            typology = APP_SCAM if app_above_cut else MULE_ACCOUNT
            return Decision(
                AnalysisStatus.TWO_FACTOR_REQUIRED,
                typology,
                STEP_UP,
                scores,
                step_up_reason=STEP_UP_POSSIBLE_SCAM,
                step_up_method=method,
                scam_warning=True,
            )

        if limit:
            return Decision(
                AnalysisStatus.TWO_FACTOR_REQUIRED,
                None,
                STEP_UP,
                scores,
                step_up_reason=STEP_UP_LIMIT,
                step_up_method=method,
            )

        if scores[APP] >= cuts["app_warn_cut"]:
            return Decision(AnalysisStatus.APPROVED, APP_SCAM, WARN, scores)

        return Decision(AnalysisStatus.APPROVED, None, NONE, scores)
