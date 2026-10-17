from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import ATO, MULE, NOT_EVALUATED, PASS, WARN, SignalResult

SHARED_DEVICE = "QUEM_OPERA.aparelho_compartilhado"
IMPOSSIBLE_TRAVEL = "QUEM_OPERA.viagem_impossivel"


class QuemOperaRule(BaseRule):
    """Regra 5 — É o dono da conta quem está operando?

    O aparelho, o lugar, o canal e a rede de onde o Pix sai dizem quem
    aperta o botão. O motor só vê os Pix que passaram por ele: um aparelho
    que opera contas em outros bancos não aparece aqui.
    """

    rule_code = "QUEM_OPERA"

    def __init__(self) -> None:
        super().__init__()
        self.signals = {
            IMPOSSIBLE_TRAVEL: (1, self._evaluate_impossible_travel),
            SHARED_DEVICE: (2, self._evaluate_shared_device),
        }

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

    def _evaluate_impossible_travel(
        self, features: PixFeatures, parameters: dict, params: PolicyParameters
    ) -> SignalResult:
        """Do último Pix aprovado até este, mais rápido que um avião: não é a mesma pessoa.

        Pontua `ato` no corte (biometria), e nunca recusa: GPS errado e VPN
        existem. Sem geolocalização no Pix ou no histórico, ou com o Pix
        chegando fora de ordem, não há velocidade: `not_evaluated`, nunca
        aprovar em silêncio. Abaixo de 5 km é imprecisão do GPS.
        """
        max_speed = parameters["max_speed_kmh"]
        min_distance = parameters["min_distance_km"]
        threshold = {"max_speed_kmh": max_speed, "min_distance_km": min_distance}

        if not features.has_geolocation:
            return self.result(IMPOSSIBLE_TRAVEL, 1, NOT_EVALUATED, "Pix sem geolocalização.", threshold=threshold)

        if features.last_location_distance_km is None:
            return self.result(
                IMPOSSIBLE_TRAVEL,
                1,
                NOT_EVALUATED,
                "O pagador não tem Pix aprovado com geolocalização para comparar.",
                threshold=threshold,
            )

        distance_km = features.last_location_distance_km
        hours = features.last_location_hours
        observed = {"distance_km": distance_km, "hours": round(hours, 4)}

        if hours <= 0:
            return self.result(
                IMPOSSIBLE_TRAVEL,
                1,
                NOT_EVALUATED,
                "Pix com data anterior ou igual à do último local conhecido: não há velocidade para calcular.",
                observed=observed,
                threshold=threshold,
            )

        if distance_km < min_distance:
            return self.result(
                IMPOSSIBLE_TRAVEL,
                1,
                PASS,
                f"{distance_km:.1f} km do último local: dentro da imprecisão do GPS.",
                observed=observed,
                threshold=threshold,
            )

        speed_kmh = distance_km / hours
        observed["speed_kmh"] = round(speed_kmh, 1)

        if speed_kmh > max_speed:
            return self.result(
                IMPOSSIBLE_TRAVEL,
                1,
                WARN,
                f"{distance_km:.0f} km em {hours * 60:.0f} minutos desde o último Pix aprovado "
                f"({speed_kmh:.0f} km/h): ninguém viaja tão rápido.",
                typology=ATO,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            IMPOSSIBLE_TRAVEL,
            1,
            PASS,
            f"{distance_km:.0f} km desde o último Pix aprovado, a {speed_kmh:.0f} km/h: viagem possível.",
            observed=observed,
            threshold=threshold,
        )
