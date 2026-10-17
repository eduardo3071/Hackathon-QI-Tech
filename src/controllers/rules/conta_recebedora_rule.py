from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.perfil_rule import VALUE as PROFILE_VALUE
from controllers.rules.perfil_rule import PerfilRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import MULE, PASS, WARN, SignalResult
from models import Account

NEW_ACCOUNT = "CONTA_RECEBEDORA.conta_nova"
FAN_IN = "CONTA_RECEBEDORA.fan_in"


class ContaRecebedoraRule(BaseRule):
    """Regra 6 — Quem recebe é confiável?

    A conta laranja passa no onboarding (é aberta com documento
    verdadeiro), então ela só se denuncia pelo comportamento, na hora de
    receber. Os sinais daqui pontuam o placar de conta laranja; quem
    decide recusar é o placar, somando o que cada um viu.
    """

    rule_code = "CONTA_RECEBEDORA"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {
            NEW_ACCOUNT: (1, self._evaluate_new_account),
            FAN_IN: (1, self._evaluate_fan_in),
        }

    def _evaluate_new_account(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Conta recente + primeiro crédito + valor fora do perfil → pontua o bastante para recusar.

        Sozinha, a idade é sinal fraco: a maioria das laranjas de banco
        tradicional tem mais de um ano (RUSI/Lloyds). Por isso só a
        combinação inteira pontua forte, e a idade sozinha pontua pouco.
        """
        if features.same_ownership:
            return self.not_needed(NEW_ACCOUNT, 1, "Mesma titularidade: a conta nova é do próprio pagador.")

        max_age_days = parameters["max_account_age_days"]
        age_days = features.payee_account_age_days
        first_credit = features.payee_prior_approved_credits == 0

        observed = {"account_age_days": age_days, "first_credit": first_credit}
        threshold = {"max_account_age_days": max_age_days}

        if age_days >= max_age_days:
            return self.result(
                NEW_ACCOUNT,
                1,
                PASS,
                f"Conta recebedora aberta há {age_days} dias.",
                observed=observed,
                threshold=threshold,
            )

        out_of_profile = False
        profile_parameters = params.of(PROFILE_VALUE)
        if params.is_enabled(PROFILE_VALUE):
            out_of_profile = PerfilRule.profile_check(features, profile_parameters)["out_of_profile"]
        observed["out_of_profile"] = out_of_profile

        if first_credit and out_of_profile:
            return self.result(
                NEW_ACCOUNT,
                1,
                WARN,
                f"Conta recebedora aberta há {age_days} dias recebendo o primeiro Pix, fora do perfil do pagador.",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            NEW_ACCOUNT,
            1,
            WARN,
            f"Conta recebedora aberta há {age_days} dias.",
            typology=MULE,
            points=parameters["age_only_points"],
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_fan_in(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Muitos pagadores distintos para uma pessoa física numa janela curta.

        O motor só enxerga o próprio tráfego: a mesma laranja pode estar
        recebendo de outras 40 instituições. É uma limitação conhecida, e
        o caminho para superá-la é a consulta ao DICT.
        """
        if features.same_ownership:
            return self.not_needed(FAN_IN, 1, "Mesma titularidade: não há terceiros convergindo.")

        if features.payee_type != Account.PERSON:
            return self.not_needed(FAN_IN, 1, "Recebedor PJ: lojista recebe de muitos pagadores.")

        min_distinct_payers = parameters["min_distinct_payers"]
        distinct_payers = features.payee_distinct_payers

        observed = {"distinct_payers": distinct_payers}
        threshold = {"min_distinct_payers": min_distinct_payers, "window_minutes": parameters["window_minutes"]}

        if distinct_payers >= min_distinct_payers:
            return self.result(
                FAN_IN,
                1,
                WARN,
                f"{distinct_payers} pagadores diferentes enviaram para esta pessoa física em "
                f"{parameters['window_minutes']} minutos.",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            FAN_IN,
            1,
            PASS,
            f"{distinct_payers} pagador(es) distinto(s) na janela.",
            observed=observed,
            threshold=threshold,
        )
