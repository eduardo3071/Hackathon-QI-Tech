from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import ATO, NOT_EVALUATED, PASS, REJECT, TWO_FACTOR, SignalResult
from models import Account
from utils.money import format_brl

UNREGISTERED_DEVICE = "LIMITE.aparelho_nao_cadastrado"
NIGHT = "LIMITE.noturno"
NO_GEOLOCATION = "LIMITE.sem_geolocalizacao"
NIGHT_AWAY_FROM_HOME = "LIMITE.noturno_fora_de_casa"


class LimiteRule(BaseRule):
    """Regra 2 — O valor cabe no limite deste contexto?

    Os sinais daqui são limites com base em norma, e por isso decidem 2FA
    sozinhos, sem passar pelos placares.
    """

    rule_code = "LIMITE"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {
            UNREGISTERED_DEVICE: (0, self._evaluate_unregistered_device),
            NIGHT: (0, self._evaluate_night),
            NIGHT_AWAY_FROM_HOME: (0, self._evaluate_night_away_from_home),
            NO_GEOLOCATION: (1, self._evaluate_no_geolocation),
        }

    def _evaluate_unregistered_device(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """R$ 200 por Pix e R$ 1.000 por dia em aparelho não cadastrado (BCB, nov/2024).

        "Cadastrado", aqui, é o aparelho CONFIÁVEL: 2 Pix aprovados, o
        primeiro há 24 h ou mais (veja o FeatureBuilder). O teto diário
        soma todos os Pix aprovados hoje de aparelhos não confiáveis. Vale
        também na mesma titularidade — o celular roubado transfere para
        onde o ladrão quiser, inclusive para outra conta da vítima.
        """
        max_per_pix = parameters["max_amount_per_pix"]
        max_per_day = parameters["max_amount_per_day"]
        threshold = {
            "max_amount_per_pix": max_per_pix,
            "max_amount_per_day": max_per_day,
            "trusted_min_approved_pix": parameters["trusted_min_approved_pix"],
            "trusted_min_hours": parameters["trusted_min_hours"],
        }

        if features.device_trusted:
            return self.result(
                UNREGISTERED_DEVICE, 0, PASS, "Aparelho confiável para este pagador.", threshold=threshold
            )

        day_amount = features.untrusted_devices_day_amount + features.amount
        observed = {"amount": features.amount, "day_amount": day_amount}

        if features.amount > max_per_pix:
            return self.result(
                UNREGISTERED_DEVICE,
                0,
                TWO_FACTOR,
                f"Aparelho ainda não confiável para este pagador e valor de {format_brl(features.amount)}, "
                f"acima dos {format_brl(max_per_pix)} por Pix permitidos sem cadastro.",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        if day_amount > max_per_day:
            return self.result(
                UNREGISTERED_DEVICE,
                0,
                TWO_FACTOR,
                f"Aparelhos não confiáveis somam {format_brl(day_amount)} hoje, "
                f"acima dos {format_brl(max_per_day)} por dia permitidos sem cadastro.",
                typology=ATO,
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            UNREGISTERED_DEVICE,
            0,
            PASS,
            "Aparelho ainda não confiável, mas dentro dos limites por Pix e por dia.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_night(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """R$ 1.000 entre 20h e 6h, PF para PF (Res. BCB 142/2021) — como SINAL, não teto.

        O motor não recebe o limite noturno que o cliente configurou no
        app. Quem já teve aprovado um Pix noturno maior que a soma desta
        noite mostrou que o limite dele é maior, e passa. Fora disso, 2FA
        de limite: confirmação no app, sem typology de fraude.
        """
        max_night_amount = parameters["max_night_amount"]
        threshold = {
            "max_night_amount": max_night_amount,
            "max_night_approved_amount": features.max_night_approved_amount,
            "night_hours": f"{parameters['night_start_hour']}h-{parameters['night_end_hour']}h",
        }

        if not features.is_night:
            return self.result(NIGHT, 0, PASS, "Fora do período noturno (horário de Brasília).", threshold=threshold)

        if features.same_ownership:
            return self.not_needed(NIGHT, 0, "Mesma titularidade: o limite noturno vale entre pessoas distintas.")

        if features.payer_type != Account.PERSON or features.payee_type != Account.PERSON:
            return self.not_needed(NIGHT, 0, "O limite noturno da Res. BCB 142 vale só de pessoa física para pessoa física.")

        night_amount = features.night_person_to_person_amount + features.amount
        observed = {"night_amount": night_amount, "local_hour": features.local_hour}

        if night_amount > max_night_amount and night_amount > features.max_night_approved_amount:
            return self.result(
                NIGHT,
                0,
                TWO_FACTOR,
                f"Pix noturno PF→PF somando {format_brl(night_amount)} nesta noite, acima de "
                f"{format_brl(max_night_amount)} e do maior Pix noturno já aprovado deste pagador.",
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            NIGHT, 0, PASS, "Soma noturna dentro do limite deste pagador.", observed=observed, threshold=threshold
        )

    def _evaluate_no_geolocation(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """Geolocalização desligada: limite reduzido (faculdade da IN BCB 669).

        Sem o local, a viagem impossível e a zona habitual ficam sem dado.
        Até o limite reduzido o Pix segue; acima dele, 2FA de limite —
        confirmação no app, sem tipologia de fraude: é limite, não suspeita.
        """
        max_amount = parameters["max_amount_without_geolocation"]
        observed = {"amount": features.amount, "has_geolocation": features.has_geolocation}
        threshold = {"max_amount_without_geolocation": max_amount}

        if features.has_geolocation:
            return self.result(
                NO_GEOLOCATION, 1, PASS, "Pix com geolocalização.", observed=observed, threshold=threshold
            )

        # A empresa que paga a folha pelo internet banking do computador não
        # manda geolocalização. A IN BCB 669 PERMITE o limite menor, não
        # obriga: no aparelho confiável dela e num canal que ela já usou num
        # Pix aprovado, o limite reduzido não se aplica.
        if features.payer_type == Account.COMPANY and features.device_trusted and features.channel_used_before:
            return self.not_needed(
                NO_GEOLOCATION,
                1,
                "Pagador PJ no aparelho confiável e no canal de sempre: o limite reduzido sem geolocalização não se aplica.",
            )

        if features.amount > max_amount:
            return self.result(
                NO_GEOLOCATION,
                1,
                TWO_FACTOR,
                f"Pix sem geolocalização de {format_brl(features.amount)}, acima do limite reduzido de "
                f"{format_brl(max_amount)} para quem não compartilha o local.",
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            NO_GEOLOCATION,
            1,
            PASS,
            "Pix sem geolocalização, dentro do limite reduzido.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_night_away_from_home(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """Pix noturno PF→PF para destino novo, longe dos locais habituais, passando de R$ 1.000: recusa.

        É o teto da Res. BCB 142 aplicado sem exceção no contexto de coação
        (sequestro relâmpago). Ali o 2FA não protege: a vítima coagida passa
        na própria biometria. E a norma diz que aumento de limite só vale
        24 h depois do pedido — um 2FA não pode funcionar como aumento
        imediato. Os locais habituais são os de Pix aprovados há pelo menos
        24 h. Sem geolocalização, ou sem nenhum local habitual, não decide.
        """
        night_parameters = params.of(NIGHT)
        min_distance = parameters["min_distance_km"]

        if night_parameters is None or not features.is_night:
            return self.result(NIGHT_AWAY_FROM_HOME, 0, PASS, "Fora do período noturno (horário de Brasília).")

        if features.same_ownership:
            return self.not_needed(NIGHT_AWAY_FROM_HOME, 0, "Mesma titularidade: o dinheiro não sai do titular.")

        if features.payer_type != Account.PERSON or features.payee_type != Account.PERSON:
            return self.not_needed(NIGHT_AWAY_FROM_HOME, 0, "O limite noturno da Res. BCB 142 é para Pix entre pessoas físicas.")

        max_night = night_parameters["max_night_amount"]
        night_amount = features.night_person_to_person_amount + features.amount
        threshold = {"min_distance_km": min_distance, "max_night_amount": max_night}

        if not features.has_geolocation:
            return self.result(NIGHT_AWAY_FROM_HOME, 0, NOT_EVALUATED, "Pix sem geolocalização.", threshold=threshold)

        if features.habitual_nearest_km is None:
            return self.result(
                NIGHT_AWAY_FROM_HOME, 0, NOT_EVALUATED,
                "O pagador não tem local de Pix aprovado há pelo menos 24 h para comparar.", threshold=threshold,
            )

        observed = {
            "night_amount": night_amount,
            "habitual_nearest_km": features.habitual_nearest_km,
            "destination_recurring": features.destination_recurring,
        }

        if (
            not features.destination_recurring
            and features.habitual_nearest_km > min_distance
            and night_amount > max_night
        ):
            return self.result(
                NIGHT_AWAY_FROM_HOME,
                0,
                REJECT,
                "Pix noturno acima de R$ 1.000 para destino novo, longe dos locais habituais: o limite noturno da "
                "Res. BCB 142 vale sem exceção; aumento de limite só vale 24 h depois de pedido no app",
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            NIGHT_AWAY_FROM_HOME,
            0,
            PASS,
            "Destino recorrente, perto dos locais habituais, ou soma noturna dentro de R$ 1.000.",
            observed=observed,
            threshold=threshold,
        )
