from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import PASS, REJECT, SignalResult
from models import FraudMarker

LIST = "MARCACAO.lista"


class MarcacaoRule(BaseRule):
    """Regra 1 — Alguém já marcou esta pessoa?

    A Res. BCB 587/2026 manda rejeitar todas as transações do usuário com
    marcação de fundada suspeita, como pagador OU recebedor. A tabela
    `fraud_marker` simula a consulta ao DICT: a marcação própria vale
    enquanto estiver vigente; a de outro PSP vale na janela de 90 dias
    que o DICT expõe (d90).

    Nem a mesma titularidade isenta: a marcação é da pessoa.
    """

    rule_code = "MARCACAO"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {LIST: (0, self._evaluate_list)}

    def _evaluate_list(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        window_days = parameters["third_party_window_days"]

        markers = []
        for side, side_markers in [("pagador", features.payer_markers), ("recebedor", features.payee_markers)]:
            for marker in side_markers:
                if marker["origin"] == FraudMarker.OWN or marker["days_since_marked"] <= window_days:
                    markers.append({"side": side, **marker})

        threshold = {"third_party_window_days": window_days}

        if not markers:
            return self.result(
                LIST, 0, PASS, "Pagador e recebedor sem marcação de fraude vigente.", threshold=threshold
            )

        sides = " e ".join(sorted({marker["side"] for marker in markers}))
        return self.result(
            LIST,
            0,
            REJECT,
            f"Marcação de fraude vigente no {sides} (Res. BCB 587/2026): transação rejeitada.",
            observed={"markers": markers},
            threshold=threshold,
        )
