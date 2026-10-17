from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from constants import LOCAL_TIMEZONE
from controllers.device_trust import DeviceTrust
from controllers.features import PixFeatures
from controllers.rules.policy_parameters import PolicyParameters
from database import Context
from models import Account, AnalysisStatus
from repositories import (
    DeviceOwnerRepository,
    FraudMarkerRepository,
    PayerPayeePairRepository,
    PayerProfileRepository,
    PixFeatureRepository,
)


class FeatureBuilder:
    """Transforma o histórico guardado nos números que as regras usam.

    As janelas (10 minutos, 1 hora, 90 dias, "esta noite") vêm dos
    parâmetros da política: a mesma tabela que diz o limite diz também
    o tamanho da janela. Os repositórios só contam e somam; quem diz
    DE ONDE ATÉ ONDE contar é este arquivo.
    """

    def __init__(self, context: Context) -> None:
        self.device_owner_repository = DeviceOwnerRepository(context)
        self.fraud_marker_repository = FraudMarkerRepository(context)
        self.payer_payee_pair_repository = PayerPayeePairRepository(context)
        self.payer_profile_repository = PayerProfileRepository(context)
        self.pix_feature_repository = PixFeatureRepository(context)

    def build(self, pix: dict, destination_account: Account, device, params: PolicyParameters) -> PixFeatures:
        transaction_date = pix["transaction_date"]
        local_date = transaction_date.astimezone(ZoneInfo(LOCAL_TIMEZONE))

        payer_document = pix["payer_document"]
        payee_document = pix["payee_document"]

        profile = self.payer_profile_repository.get(payer_document)
        device_owner = self.device_owner_repository.get(device.id, payer_document)
        pair = self.payer_payee_pair_repository.get(payer_document, destination_account.id)

        max_night_approved_amount = 0
        if profile is not None:
            max_night_approved_amount = profile.max_night_approved_amount

        pair_approved_count = 0
        pair_scam_step_up_count = 0
        if pair is not None:
            pair_approved_count = pair.approved_count
            pair_scam_step_up_count = pair.scam_step_up_count

        night = self._night(pix, local_date, params.of("LIMITE.noturno"))
        velocity = self._velocity(pix, params.of("RITMO.velocidade"))

        return PixFeatures(
            amount=pix["amount"],
            transaction_date=transaction_date.isoformat(),
            local_hour=local_date.hour,
            same_ownership=payer_document == payee_document,
            payer_type=pix["payer_type"],
            payee_type=pix["payee_type"],
            payer_markers=self._markers(payer_document, transaction_date),
            payee_markers=self._markers(payee_document, transaction_date),
            payer_known=self.pix_feature_repository.payer_has_pix(payer_document),
            payer_account_age_days=max(0, (transaction_date - pix["source_account"]["opening_date"]).days),
            device_trusted=DeviceTrust.is_trusted(
                device_owner, transaction_date, params.of("LIMITE.aparelho_nao_cadastrado")
            ),
            untrusted_devices_day_amount=self._untrusted_devices_day_amount(
                payer_document, transaction_date, local_date, params.of("LIMITE.aparelho_nao_cadastrado")
            ),
            is_night=night["is_night"],
            night_person_to_person_amount=night["amount"],
            max_night_approved_amount=max_night_approved_amount,
            velocity_attempts=velocity["attempts"],
            velocity_amount=velocity["amount"],
            profile_amounts=self._profile_amounts(profile, transaction_date, params.of("PERFIL.valor")),
            pair_approved_count=pair_approved_count,
            pair_scam_step_up_count=pair_scam_step_up_count,
            payee_account_age_days=max(0, (transaction_date - destination_account.opening_date).days),
            payee_prior_approved_credits=self.pix_feature_repository.count_credits(
                destination_account.id, AnalysisStatus.APPROVED
            ),
            payee_distinct_payers=self._distinct_payers(pix, params.of("CONTA_RECEBEDORA.fan_in")),
        )

    def _markers(self, document_number: str, transaction_date: datetime) -> list:
        markers = []
        for marker in self.fraud_marker_repository.get_valid(document_number, transaction_date):
            markers.append(
                {
                    "marker_type": marker.marker_type,
                    "origin": marker.origin,
                    "days_since_marked": (transaction_date - marker.marked_at).days,
                }
            )

        return markers

    def _untrusted_devices_day_amount(self, payer_document, transaction_date, local_date, parameters):
        """Quanto este pagador já mandou HOJE (dia de Brasília), aprovado, de aparelhos não confiáveis."""
        if parameters is None:
            return None

        day_start = local_date.replace(hour=0, minute=0, second=0, microsecond=0)

        return self.pix_feature_repository.sum_by_device_trust(
            payer_document, day_start, transaction_date, False, AnalysisStatus.APPROVED
        )

    def _night(self, pix: dict, local_date: datetime, parameters) -> dict:
        """Se o Pix é noturno e quanto o pagador já mandou PF→PF nesta noite.

        A noite que importa é a que contém o Pix: das 20h de hoje, se já
        passou das 20h; das 20h de ontem, se ainda é madrugada.
        """
        if parameters is None:
            return {"is_night": None, "amount": None}

        start_hour = parameters["night_start_hour"]
        end_hour = parameters["night_end_hour"]

        is_night = local_date.hour >= start_hour or local_date.hour < end_hour
        if not is_night:
            return {"is_night": False, "amount": 0}

        night_start = local_date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if local_date.hour < end_hour:
            night_start = night_start - timedelta(days=1)

        amount = self.pix_feature_repository.sum_approved_between_people(
            pix["payer_document"],
            night_start,
            pix["transaction_date"],
            Account.PERSON,
            AnalysisStatus.APPROVED,
        )
        return {"is_night": True, "amount": amount}

    def _velocity(self, pix: dict, parameters) -> dict:
        """Tentativas anteriores do pagador na janela, e quanto elas somam.

        O mesmo Pix refeito com `id` novo — mesmo recebedor, mesmo valor —
        conta como UMA tentativa: é o cliente que tomou um 2FA e refez o
        Pix, e contar de novo o empurraria para a recusa. Por isso a
        contagem é de pares (recebedor, valor) distintos, e o par deste Pix
        sai da conta (a regra soma o Pix atual à vista, "anteriores + 1").
        """
        if parameters is None:
            return {"attempts": None, "amount": None}

        window_start = pix["transaction_date"] - timedelta(minutes=parameters["window_minutes"])
        groups = set(
            self.pix_feature_repository.attempt_groups(pix["payer_document"], window_start, pix["transaction_date"])
        )
        groups.discard((pix["payee_document"], pix["amount"]))

        return {"attempts": len(groups), "amount": sum(amount for _payee, amount in groups)}

    def _profile_amounts(self, profile, transaction_date: datetime, parameters):
        """Os valores aprovados do pagador dentro da janela do perfil (90 dias)."""
        if parameters is None:
            return None

        if profile is None:
            return []

        window_start = transaction_date - timedelta(days=parameters["window_days"])

        amounts = []
        for approved in profile.recent_approved:
            approved_at = datetime.fromisoformat(approved["at"])
            if window_start <= approved_at <= transaction_date:
                amounts.append(approved["amount"])

        return amounts

    def _distinct_payers(self, pix: dict, parameters):
        """Pagadores distintos deste recebedor na janela, contando o pagador deste Pix.

        É a única contagem que já inclui o Pix atual, porque "distintos"
        não se resolve com "+ 1": se este pagador já mandou antes na
        janela, ele não é um pagador a mais.
        """
        if parameters is None:
            return None

        window_start = pix["transaction_date"] - timedelta(minutes=parameters["window_minutes"])

        payers = set(
            self.pix_feature_repository.distinct_payers(pix["payee_document"], window_start, pix["transaction_date"])
        )
        payers.add(pix["payer_document"])

        return len(payers)
