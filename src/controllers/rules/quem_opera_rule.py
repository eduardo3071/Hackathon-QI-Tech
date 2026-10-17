from controllers.features import PixFeatures
from controllers.rules.base_rule import BaseRule
from controllers.rules.perfil_rule import VALUE as PROFILE_VALUE
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.signal_result import ATO, MULE, NOT_EVALUATED, PASS, WARN, SignalResult
from utils.money import format_brl

SHARED_DEVICE = "QUEM_OPERA.aparelho_compartilhado"
IMPOSSIBLE_TRAVEL = "QUEM_OPERA.viagem_impossivel"
UNUSUAL_CHANNEL = "QUEM_OPERA.canal_incomum"
SHARED_IP = "QUEM_OPERA.ip_compartilhado"


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
            UNUSUAL_CHANNEL: (1, self._evaluate_unusual_channel),
            SHARED_DEVICE: (2, self._evaluate_shared_device),
            SHARED_IP: (2, self._evaluate_shared_ip),
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

    def _evaluate_unusual_channel(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Canal que o pagador nunca usou num Pix aprovado, com valor acima do limite de partida.

        Pontua `ato` abaixo do corte: reforça outro sinal de invasão, não
        decide sozinho — trocar do app para o internet banking é comum. O
        limite de partida vem do PERFIL.valor; sem ele, não há com que
        comparar. Cliente que o motor ainda não conhece não tem canal de
        costume: `not_evaluated`.
        """
        observed = {"channel": features.channel, "amount": features.amount}

        if not features.payer_known:
            return self.result(
                UNUSUAL_CHANNEL,
                1,
                NOT_EVALUATED,
                "O motor ainda não tem histórico deste pagador: não há canal de costume.",
                observed=observed,
            )

        if not params.is_enabled(PROFILE_VALUE):
            return self.result(
                UNUSUAL_CHANNEL, 1, NOT_EVALUATED, "PERFIL.valor desligado: sem limite de partida.", observed=observed
            )

        fallback_amount = params.of(PROFILE_VALUE)["fallback_amount"]
        threshold = {"fallback_amount": fallback_amount}
        observed["channel_used_before"] = features.channel_used_before

        if not features.channel_used_before and features.amount > fallback_amount:
            return self.result(
                UNUSUAL_CHANNEL,
                1,
                WARN,
                f"O pagador nunca teve um Pix aprovado pelo canal \"{features.channel}\", e este é de {format_brl(features.amount)}, "
                f"acima do limite de partida de {format_brl(fallback_amount)}: canal fora do costume.",
                typology=ATO,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            UNUSUAL_CHANNEL,
            1,
            PASS,
            "Canal de costume do pagador, ou valor dentro do limite de partida.",
            observed=observed,
            threshold=threshold,
        )

    def _evaluate_shared_ip(self, features: PixFeatures, parameters: dict, params: PolicyParameters) -> SignalResult:
        """Muitos CPFs pagando do mesmo IP na última hora — só conta com aparelho não confiável.

        Rede móvel e Wi-Fi público põem centenas de pessoas atrás do mesmo
        IP (CGNAT). Sozinho, o IP não diz nada; com um aparelho que ainda
        não é confiável para este pagador, reforça a suspeita de invasão.
        Pontua `ato` abaixo do corte: nunca decide sozinho.
        """
        distinct_payers = features.ip_distinct_payers
        min_distinct_payers = parameters["min_distinct_payers"]

        observed = {"distinct_payers": distinct_payers, "device_trusted": features.device_trusted}
        threshold = {"min_distinct_payers": min_distinct_payers, "window_minutes": parameters["window_minutes"]}

        if distinct_payers >= min_distinct_payers and not features.device_trusted:
            return self.result(
                SHARED_IP,
                2,
                WARN,
                f"{distinct_payers} CPFs diferentes pagaram deste IP em {parameters['window_minutes']} minutos, "
                "e o aparelho ainda não é confiável para este pagador.",
                typology=ATO,
                points=parameters["points"],
                observed=observed,
                threshold=threshold,
            )

        return self.result(
            SHARED_IP,
            2,
            PASS,
            f"{distinct_payers} CPF(s) pagador(es) neste IP na janela, ou aparelho confiável.",
            observed=observed,
            threshold=threshold,
        )
