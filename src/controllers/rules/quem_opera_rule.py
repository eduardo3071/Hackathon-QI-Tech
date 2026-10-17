from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import MULE, PASS, WARN, SignalResult

SHARED_DEVICE = "QUEM_OPERA.aparelho_compartilhado"


class QuemOperaRule(BaseRule):
    """Regra 5 — É o dono da conta quem está operando?

    O aparelho, o lugar, o canal e a rede de onde o Pix sai dizem quem
    aperta o botão. O motor só vê os Pix que passaram por ele: um aparelho
    que opera contas em outros bancos não aparece aqui.
    """

    rule_code = "QUEM_OPERA"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {SHARED_DEVICE: (2, self._evaluate_shared_device)}

    def _evaluate_shared_device(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Muitos CPFs pagando do mesmo aparelho: a fazenda de contas.

        Pontua `mule`, e não `ato`: quem opera várias contas do mesmo
        celular não invadiu uma conta, está movimentando contas laranja.
        Dois CPFs (o casal que divide o celular) não pontuam.
        """
        distinct_payers = features.device_distinct_payers
        min_distinct_payers = parameters["min_distinct_payers"]

        observed = {"distinct_payers": distinct_payers}
        threshold = {"min_distinct_payers": min_distinct_payers, "window_days": parameters["window_days"]}

        if distinct_payers >= min_distinct_payers:
            return self.result(
                SHARED_DEVICE,
                2,
                WARN,
                f"{distinct_payers} CPFs diferentes pagaram deste aparelho nos últimos {parameters['window_days']} dias: "
                "padrão de várias contas operadas do mesmo celular.",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            SHARED_DEVICE,
            2,
            PASS,
            f"{distinct_payers} CPF(s) pagador(es) neste aparelho na janela.",
            observed=observed,
            threshold=threshold,
        )
