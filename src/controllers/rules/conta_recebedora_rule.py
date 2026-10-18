from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.perfil_rule import VALUE as PROFILE_VALUE
from controllers.rules.perfil_rule import PerfilRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import APP, MULE, PASS, WARN, SignalResult
from models import Account
from utils.money import format_brl

NEW_ACCOUNT = "CONTA_RECEBEDORA.conta_nova"
FAN_IN = "CONTA_RECEBEDORA.fan_in"
PRIOR_SUSPICION = "CONTA_RECEBEDORA.suspeita_anterior"
DORMANT = "CONTA_RECEBEDORA.dormente"
SEVERAL_INSTITUTIONS = "CONTA_RECEBEDORA.varias_instituicoes"


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
            PRIOR_SUSPICION: (1, self._evaluate_prior_suspicion),
            DORMANT: (2, self._evaluate_dormant),
            SEVERAL_INSTITUTIONS: (2, self._evaluate_several_institutions),
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

        # Conta nova converge com menos pagadores: a falsa venda e a laranja
        # recém-aberta só travavam na 5ª vítima. E o valor conta: 8 amigos
        # mandando R$ 20 a uma rifa são R$ 160, não um golpe.
        min_distinct_payers = parameters["min_distinct_payers"]
        if features.payee_account_age_days < parameters["new_account_max_age_days"]:
            min_distinct_payers = parameters["new_account_min_distinct_payers"]

        distinct_payers = features.payee_distinct_payers
        window_amount = features.payee_window_received
        min_window_amount = parameters["min_window_amount"]

        observed = {"distinct_payers": distinct_payers, "window_amount": window_amount}
        threshold = {
            "min_distinct_payers": min_distinct_payers,
            "min_window_amount": min_window_amount,
            "window_minutes": parameters["window_minutes"],
        }

        if distinct_payers >= min_distinct_payers and window_amount >= min_window_amount:
            return self.result(
                FAN_IN,
                1,
                WARN,
                f"{distinct_payers} pagadores diferentes enviaram {format_brl(window_amount)} para esta pessoa "
                f"física em {parameters['window_minutes']} minutos.",
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

    def _evaluate_prior_suspicion(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """Destino que já pediu 2FA por suspeita de golpe a este pagador, e de novo um valor fora do perfil.

        É o golpe repetido do falso investimento: a vítima confirma o
        primeiro Pix e volta a pagar o mesmo golpista. A suspeita de antes
        não some porque o 2FA passou — quem está sendo manipulado passa em
        qualquer 2FA. Pontua golpe no valor do corte de golpe: sozinho, já
        pede de novo a confirmação com aviso.
        """
        if features.same_ownership:
            return self.not_needed(PRIOR_SUSPICION, 1, "Mesma titularidade: não há golpista do outro lado.")

        prior_step_ups = features.payee_prior_scam_step_ups

        if features.destination_monthly_bill:
            return self.result(
                PRIOR_SUSPICION,
                1,
                PASS,
                "Valor parecido com um pagamento já confirmado a esta conta, de semanas atrás: a conta do mês, "
                "e não um golpe repetido.",
                observed={"prior_scam_step_ups": prior_step_ups, "monthly_bill": True},
                threshold={
                    "monthly_min_days": parameters["monthly_min_days"],
                    "monthly_amount_tolerance_percent": parameters["monthly_amount_tolerance_percent"],
                },
            )

        out_of_profile = False
        if params.is_enabled(PROFILE_VALUE):
            out_of_profile = PerfilRule.profile_check(features, params.of(PROFILE_VALUE))["out_of_profile"]

        observed = {"prior_scam_step_ups": prior_step_ups, "out_of_profile": out_of_profile}
        threshold = {"window_days": parameters["window_days"]}

        if prior_step_ups > 0 and out_of_profile:
            return self.result(
                PRIOR_SUSPICION,
                1,
                WARN,
                f"Este pagador já recebeu {prior_step_ups} 2FA(s) por suspeita de golpe para esta conta nos "
                f"últimos {parameters['window_days']} dias, e o valor está fora do perfil: padrão de golpe repetido.",
                typology=APP,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            PRIOR_SUSPICION,
            1,
            PASS,
            "Sem suspeita de golpe anterior para esta conta, ou valor dentro do perfil.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_dormant(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Destino que reaparece depois de 60 dias sem movimento na nossa base.

        A conta laranja alugada costuma ser antiga e parada, e volta a
        receber de repente. O motor só sabe que ela ficou parada NA NOSSA
        BASE: pode ter movimentado em outro banco. Por isso pontua `mule`
        abaixo do corte — reforça outro sinal de laranja, não decide só.
        Conta que o motor nunca viu receber não "reaparece".
        """
        if features.same_ownership:
            return self.not_needed(DORMANT, 2, "Mesma titularidade: a conta é do próprio pagador.")

        days_without_movement = features.payee_days_without_movement
        min_days = parameters["min_days_without_movement"]

        observed = {"days_without_movement": days_without_movement}
        threshold = {"min_days_without_movement": min_days}

        if days_without_movement is not None and days_without_movement >= min_days:
            return self.result(
                DORMANT,
                2,
                WARN,
                f"Destino que reaparece depois de {days_without_movement} dias sem movimento na nossa base.",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            DORMANT,
            2,
            PASS,
            "Destino com movimento recente na nossa base, ou que o motor nunca viu receber.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_several_institutions(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """O mesmo CPF recebedor com contas novas em várias instituições: a laranja que abre contas em série.

        O motor só conhece as contas que já apareceram como destino na
        nossa base. Pontua `mule` abaixo do corte: reforça outro sinal.
        """
        if features.same_ownership:
            return self.not_needed(SEVERAL_INSTITUTIONS, 2, "Mesma titularidade: as contas são do próprio pagador.")

        if features.payee_type != Account.PERSON:
            return self.not_needed(SEVERAL_INSTITUTIONS, 2, "Recebedor PJ: empresa tem contas em vários bancos.")

        institutions = features.payee_new_account_institutions
        min_institutions = parameters["min_institutions"]

        observed = {"institutions": institutions}
        threshold = {"min_institutions": min_institutions, "max_account_age_days": parameters["max_account_age_days"]}

        if institutions >= min_institutions:
            return self.result(
                SEVERAL_INSTITUTIONS,
                2,
                WARN,
                f"O recebedor abriu contas em {institutions} instituições diferentes nos últimos "
                f"{parameters['max_account_age_days']} dias.",
                typology=MULE,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            SEVERAL_INSTITUTIONS,
            2,
            PASS,
            f"Contas novas do recebedor em {institutions} instituição(ões) na nossa base.",
            observed=observed,
            threshold=threshold,
        )
