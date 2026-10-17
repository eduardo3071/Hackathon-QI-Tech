import hashlib
import ipaddress
import json
from copy import deepcopy
from datetime import datetime
from typing import Tuple

from controllers.analysis_engine import AnalysisEngine, EngineResult
from controllers.base_controller import BaseController
from controllers.decision import FACE_LIVENESS, STEP_UP_ACCOUNT_TAKEOVER
from controllers.device_trust import DeviceTrust
from controllers.feature_builder import FeatureBuilder
from controllers.features import PixFeatures
from controllers.rules import PolicyParameters
from dtos import PixAnalysisDTO
from errors import (
    InvalidDate,
    InvalidDocumentNumber,
    InvalidIpAddress,
    NoActivePolicy,
    NotFoundPixTransaction,
    PixNotAwaitingTwoFactor,
    PixTransactionConflict,
    TwoFactorCompletedBeforePix,
    TwoFactorResultConflict,
)
from models import TWO_FACTOR_RESULT_STATUS, Account, AnalysisStatus, Device, PixTransaction
from models.analysis_status_event import TWO_FACTOR_PASSED
from repositories import (
    AccountRepository,
    AnalysisRepository,
    DeviceOwnerRepository,
    DeviceRepository,
    PayerPayeePairRepository,
    PayerProfileRepository,
    PixTransactionRepository,
    PolicyRepository,
)
from utils.document_number import CPF_LENGTH, is_valid_document, only_digits


class PixTransactionController(BaseController):
    """Recebe o Pix, decide, grava e devolve a análise. Aqui mora o "pode"."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.analysis_repository = AnalysisRepository(self.context)
        self.device_owner_repository = DeviceOwnerRepository(self.context)
        self.device_repository = DeviceRepository(self.context)
        self.payer_payee_pair_repository = PayerPayeePairRepository(self.context)
        self.payer_profile_repository = PayerProfileRepository(self.context)
        self.pix_transaction_repository = PixTransactionRepository(self.context)
        self.policy_repository = PolicyRepository(self.context)
        self.feature_builder = FeatureBuilder(self.context)
        self.analysis_engine = AnalysisEngine()

    def create(self, pix_payload: dict) -> Tuple[dict, bool]:
        """Analisa um Pix e devolve `(análise, se_foi_criada_agora)`.

        A ordem abaixo é a regra:

        1. Conferir o que só se sabe olhando o valor (documento, data).
           Recusa aqui não deixa nada no banco.
        2. Travar. Daqui até o commit, ninguém mais mexe nas contagens
           deste pagador, deste recebedor PF ou deste aparelho.
        3. Só DEPOIS da trava perguntar se o `id` já existe. Perguntar
           antes deixaria dois reenvios simultâneos passarem juntos pela
           pergunta e criarem dois Pix com o mesmo `id`.
        4. Avaliar, gravar e salvar — o commit é a última linha.
        """
        self.logger.debug(f"Analisando o Pix {pix_payload['id']}")

        pix = self._parse_pix(pix_payload)

        self.pix_transaction_repository.lock(
            self._lock_keys(
                pix["external_id"], pix["payer_document"], pix["payee_document"], pix["payee_type"], pix["device_id"]
            )
        )

        recorded_pix = self.pix_transaction_repository.get_by_external_id(pix["external_id"])
        if recorded_pix is not None:
            return self._replay(recorded_pix, pix), False

        policy, params = self._active_policy()

        source_account = self.account_repository.get_or_create(pix["source_account"])
        destination_account = self.account_repository.get_or_create(pix["destination_account"])
        device = self.device_repository.get_or_create(pix["device_id"], pix["transaction_date"])

        # As features são calculadas ANTES de o Pix ser gravado: toda
        # contagem é do histórico anterior a ele, e nenhuma consulta
        # precisa lembrar de excluí-lo.
        features = self.feature_builder.build(pix, destination_account, device, params)
        engine_result = self.analysis_engine.run(features, params)

        pix_transaction = self._record_pix(pix, source_account, destination_account, device)
        analysis = self._record_analysis(pix_transaction, policy, features, engine_result)
        self._update_aggregates(pix, destination_account, device, features, engine_result, params)

        analysis_dto = PixAnalysisDTO.obj_to_dict(analysis)
        self.session.commit()

        return analysis_dto, True

    def get_by_id(self, pix_id: str) -> dict:
        self.logger.debug(f"Buscando a análise do Pix {pix_id}")

        pix_transaction = self.pix_transaction_repository.get_by_external_id(pix_id)

        if pix_transaction is None:
            raise NotFoundPixTransaction(pix_id)

        return PixAnalysisDTO.obj_to_dossier_dict(pix_transaction.analysis)

    def apply_two_factor_result(self, pix_id: str, two_factor_payload: dict) -> dict:
        """O retorno do 2FA: `two_factor_required` vira `approved` ou `rejected`, uma vez só.

        A ordem é a mesma do `create`: conferir o valor, travar, e só
        DEPOIS da trava perguntar em que estado a análise está. Dois
        retornos simultâneos viram fila, e o segundo encontra o primeiro
        já gravado. A trava é a mesma do POST porque o retorno atualiza
        as mesmas agregadas (perfil, par, aparelho).

        O retorno não reavalia as regras: a decisão foi tomada no POST, e
        aqui só se registra como o 2FA terminou. Ele também não conta
        como tentativa na velocidade — nenhum Pix novo é gravado.
        """
        self.logger.debug(f"Aplicando o retorno do 2FA do Pix {pix_id}")

        result = two_factor_payload["two_factor_result"]
        completed_at = self._parse_date("completed_at", two_factor_payload["completed_at"])

        pix_transaction = self.pix_transaction_repository.get_by_external_id(pix_id)
        if pix_transaction is None:
            raise NotFoundPixTransaction(pix_id)

        if completed_at < pix_transaction.transaction_date:
            raise TwoFactorCompletedBeforePix(pix_id)

        self.pix_transaction_repository.lock(
            self._lock_keys(
                pix_transaction.external_id,
                pix_transaction.payer_document_number,
                pix_transaction.payee_document_number,
                pix_transaction.destination_account.owner_type,
                pix_transaction.device.device_id,
            )
        )
        analysis = self.analysis_repository.get_current(pix_transaction.id)

        two_factor_event = analysis.two_factor_event
        if two_factor_event is not None:
            recorded_result = two_factor_event.two_factor_result
            if recorded_result != result:
                raise TwoFactorResultConflict(pix_id, recorded_result)

            return PixAnalysisDTO.obj_to_dossier_dict(analysis)

        if analysis.status.enumerator != AnalysisStatus.TWO_FACTOR_REQUIRED:
            raise PixNotAwaitingTwoFactor(pix_id, analysis.status.enumerator)

        self.analysis_repository.change_status(analysis, TWO_FACTOR_RESULT_STATUS[result], completed_at)
        self._learn_from_two_factor(pix_transaction, analysis, result, completed_at)

        analysis_dto = PixAnalysisDTO.obj_to_dossier_dict(analysis)
        self.session.commit()

        return analysis_dto

    def _learn_from_two_factor(self, pix_transaction, analysis, result: str, completed_at: datetime) -> None:
        """O que o motor aprende com o resultado do 2FA.

          • passou → o Pix saiu: entra no perfil, na soma noturna e no par,
            como qualquer Pix aprovado. Com duas ressalvas:
              – biometria facial aprovada é o cadastro do aparelho que o
                BCB prevê: o aparelho fica confiável na hora. A confirmação
                no app (2FA por limite ou por golpe) não cadastra nada;
              – 2FA com aviso de golpe confirmado NÃO torna o destino
                recorrente. A vítima de falso investimento confirma o Pix e
                volta a pagar o mesmo golpista; se o destino virasse "a
                conta do mês", o segundo Pix sairia sem fricção.
          • falhou → nada entra no perfil. Se a suspeita era invasão, o
            aparelho fica com a confiança bloqueada por 24 h.
        """
        _policy, params = self._active_policy()
        payer_document = pix_transaction.payer_document_number
        device_owner = self.device_owner_repository.get(pix_transaction.device_id, payer_document)

        if result != TWO_FACTOR_PASSED:
            if analysis.step_up_reason == STEP_UP_ACCOUNT_TAKEOVER:
                self.device_owner_repository.register_step_up_failure(device_owner, completed_at)
            return

        if analysis.step_up_method == FACE_LIVENESS:
            self.device_owner_repository.register_face_liveness(device_owner, completed_at)

        self._learn_approved(
            {
                "payer_document": payer_document,
                "amount": pix_transaction.amount,
                "transaction_date": pix_transaction.transaction_date,
                "latitude": pix_transaction.latitude,
                "longitude": pix_transaction.longitude,
            },
            device_owner,
            self.payer_payee_pair_repository.get(payer_document, pix_transaction.destination_account_id),
            is_night=bool(analysis.features["is_night"]),
            same_ownership=analysis.features["same_ownership"],
            recurring_destination=not analysis.scam_warning,
            params=params,
        )

    def _active_policy(self):
        policy = self.policy_repository.get_active()
        if policy is None:
            raise NoActivePolicy()

        return policy, PolicyParameters(policy)

    def _replay(self, recorded_pix, pix: dict) -> dict:
        """O mesmo `id` de novo: retentativa devolve o gravado; conteúdo novo é conflito.

        Nada é reavaliado nem contado de novo — um retry de rede não pode
        virar uma segunda tentativa na regra de velocidade.
        """
        if recorded_pix.payload_hash != pix["payload_hash"]:
            raise PixTransactionConflict(pix["external_id"])

        return PixAnalysisDTO.obj_to_dict(recorded_pix.analysis)

    def _record_pix(
        self, pix: dict, source_account: Account, destination_account: Account, device: Device
    ) -> PixTransaction:
        return self.pix_transaction_repository.create(
            {
                "external_id": pix["external_id"],
                "payload_hash": pix["payload_hash"],
                "amount": pix["amount"],
                "transaction_date": pix["transaction_date"],
                "source_account_id": source_account.id,
                "destination_account_id": destination_account.id,
                "device_id": device.id,
                "payer_document_number": pix["payer_document"],
                "payee_document_number": pix["payee_document"],
                "channel": pix["channel"],
                "ip": pix["ip"],
                "latitude": pix["latitude"],
                "longitude": pix["longitude"],
                "raw_payload": pix["raw_payload"],
            }
        )

    def _record_analysis(self, pix_transaction, policy, features: PixFeatures, engine_result: EngineResult):
        """A decisão e um resultado por sinal — inclusive os que passaram ou não rodaram."""
        decision = engine_result.decision

        analysis = self.analysis_repository.create(
            analysis_data={
                "pix_transaction": pix_transaction,
                "policy_version": policy,
                "typology": decision.typology,
                "recommended_action": decision.recommended_action,
                "step_up_reason": decision.step_up_reason,
                "step_up_method": decision.step_up_method,
                "scam_warning": decision.scam_warning,
                "score_ato": decision.scores["ato"],
                "score_app": decision.scores["app"],
                "score_mule": decision.scores["mule"],
                "path": engine_result.path,
                "device_trusted": features.device_trusted,
                "layers": engine_result.layers,
                "features": features.to_dict(),
            },
            status_enumerator=decision.status,
            event_datetime=pix_transaction.transaction_date,
        )

        for result in engine_result.results:
            self.analysis_repository.add_rule_result(
                analysis,
                {
                    "rule_code": result.rule_code,
                    "signal_code": result.signal_code,
                    "layer": result.layer,
                    "outcome": result.outcome,
                    "typology": result.typology,
                    "points": result.points,
                    "observed": result.observed,
                    "threshold": result.threshold,
                    "message": result.message,
                },
            )

        return analysis

    def _update_aggregates(
        self,
        pix: dict,
        destination_account: Account,
        device: Device,
        features: PixFeatures,
        engine_result: EngineResult,
        params: PolicyParameters,
    ) -> None:
        """Atualiza as tabelas agregadas no mesmo commit do Pix.

        Higiene do histórico: toda tentativa registra que o aparelho e o
        destino foram VISTOS, mas só o Pix APROVADO ensina o perfil. Se a
        tentativa recusada entrasse na mediana, o fraudador "educaria" a
        linha de base subindo valores aos poucos. O Pix que pediu 2FA
        ensina depois, se o 2FA passar (`_learn_from_two_factor`).
        """
        payer_document = pix["payer_document"]
        transaction_date = pix["transaction_date"]

        device_owner = self.device_owner_repository.register_attempt(device.id, payer_document, transaction_date)
        pair = self.payer_payee_pair_repository.register_attempt(
            payer_document, destination_account.id, transaction_date
        )

        if engine_result.decision.status != AnalysisStatus.APPROVED:
            return

        self._learn_approved(
            pix,
            device_owner,
            pair,
            is_night=bool(features.is_night),
            same_ownership=features.same_ownership,
            recurring_destination=True,
            params=params,
        )

    def _learn_approved(
        self,
        pix: dict,
        device_owner,
        pair,
        is_night: bool,
        same_ownership: bool,
        recurring_destination: bool,
        params: PolicyParameters,
    ) -> None:
        """Um Pix que saiu: o perfil, o par e o aparelho aprendem com ele.

        Serve ao Pix aprovado direto (POST) e ao que passou no 2FA (PATCH):
        "Pix aprovado" é um só, por qualquer caminho que tenha saído.
        """
        payer_document = pix["payer_document"]
        transaction_date = pix["transaction_date"]

        profile = self.payer_profile_repository.get_or_create(payer_document)
        self.payer_profile_repository.add_approved(profile, pix["amount"], transaction_date)

        if recurring_destination:
            self.payer_payee_pair_repository.add_approved(pair, pix["amount"])
        else:
            self.payer_payee_pair_repository.add_scam_step_up(pair)

        # Com a confiança bloqueada (biometria reprovada há menos de 24 h),
        # o Pix aprovado não conta para tornar o aparelho confiável.
        if not DeviceTrust.is_blocked(device_owner, transaction_date, params.of("LIMITE.aparelho_nao_cadastrado")):
            self.device_owner_repository.add_approved(device_owner, transaction_date)

        # Mover o próprio dinheiro de madrugada não diz nada sobre o limite
        # noturno que o cliente configurou para pagar terceiros.
        if is_night and not same_ownership:
            self.payer_profile_repository.update_max_night_approved_amount(profile, pix["amount"])

        if pix["latitude"] is not None:
            self.payer_profile_repository.add_location(profile, pix["latitude"], pix["longitude"], transaction_date)

        # O último local é o do Pix aprovado mais RECENTE: um Pix que chega
        # fora de ordem não pode voltar o relógio da viagem impossível.
        if pix["latitude"] is not None and (
            profile.last_geolocation_at is None or transaction_date >= profile.last_geolocation_at
        ):
            self.payer_profile_repository.update_last_geolocation(
                profile, pix["latitude"], pix["longitude"], transaction_date
            )

    def _lock_keys(
        self, external_id: str, payer_document: str, payee_document: str, payee_type: str, device_id: str
    ) -> list:
        """As chaves da trava, em ordem crescente — sempre a mesma ordem para todos.

        Duas requisições que travam as mesmas duas chaves em ordens
        diferentes podem esperar uma pela outra para sempre (impasse).
        Ordenando, quem chega segundo espera na PRIMEIRA chave, sem
        segurar nenhuma.

        Quem entra na trava:
          • o `id` do Pix: dois reenvios simultâneos viram fila, e o
            segundo encontra o primeiro já gravado;
          • o documento do pagador: velocidade e perfil;
          • o documento do recebedor, só se PF: pagadores distintos
            (fan-in). O PJ fica fora porque o fan-in não vale para ele e
            um lojista grande viraria fila;
          • o aparelho.
        Pagador e recebedor dividem o prefixo `document:` de propósito: o
        recebedor de agora é o pagador de daqui a pouco, e a contagem é
        da PESSOA, não do papel que ela tem neste Pix.
        """
        lock_keys = {
            f"pix:{external_id}",
            f"document:{payer_document}",
            f"device:{device_id}",
        }

        if payee_type == Account.PERSON:
            lock_keys.add(f"document:{payee_document}")

        return sorted(lock_keys)

    def _parse_pix(self, pix_payload: dict) -> dict:
        """O payload já conferido pelo schema, virado nos valores que as regras usam.

        O schema garantiu o FORMATO. O que ele não sabe, e é cobrado
        aqui com 422: se o CPF/CNPJ fecha a conta dos dígitos
        verificadores, se a data existe no calendário e se o IP é um IPv4
        ou IPv6 de verdade.
        """
        source_account = pix_payload["source_account"]
        destination_account = pix_payload["destination_account"]
        source = pix_payload["source"]

        payer_document = self._parse_document(source_account["owner"]["document_number"])
        payee_document = self._parse_document(destination_account["owner"]["document_number"])
        transaction_date = self._parse_date("transaction_date", pix_payload["transaction_date"])

        latitude = None
        longitude = None
        geolocation = source.get("geolocation")
        if geolocation is not None:
            latitude = geolocation["latitude"]
            longitude = geolocation["longitude"]

        return {
            "external_id": pix_payload["id"],
            "payload_hash": self._payload_hash(pix_payload, payer_document, payee_document),
            "amount": int(pix_payload["amount"]),
            "transaction_date": transaction_date,
            "payer_document": payer_document,
            "payer_type": self._owner_type(payer_document),
            "payee_document": payee_document,
            "payee_type": self._owner_type(payee_document),
            "source_account": {
                "ispb": None,
                "branch": source_account["branch"],
                "account_number": source_account["account_number"],
                "opening_date": self._parse_date("source_account.opening_date", source_account["opening_date"]),
                "owner_document_number": payer_document,
                "owner_type": self._owner_type(payer_document),
            },
            "destination_account": {
                "ispb": destination_account["participant"],
                "branch": destination_account["branch"],
                "account_number": destination_account["account_number"],
                "opening_date": self._parse_date(
                    "destination_account.opening_date", destination_account["opening_date"]
                ),
                "owner_document_number": payee_document,
                "owner_type": self._owner_type(payee_document),
            },
            "device_id": source["device_id"],
            "channel": source["channel"],
            "ip": self._parse_ip(source["ip"]),
            "latitude": latitude,
            "longitude": longitude,
            "raw_payload": pix_payload,
        }

    def _parse_document(self, raw_document: str) -> str:
        if not is_valid_document(raw_document):
            raise InvalidDocumentNumber(raw_document)

        return only_digits(raw_document)

    def _parse_ip(self, raw_ip: str) -> str:
        """O IP na forma canônica: o mesmo IPv6 escrito de dois jeitos vira o mesmo texto."""
        try:
            return str(ipaddress.ip_address(raw_ip))
        except ValueError:
            raise InvalidIpAddress(raw_ip)

    def _parse_date(self, field_name: str, raw_date: str) -> datetime:
        try:
            return datetime.fromisoformat(raw_date)
        except ValueError:
            raise InvalidDate(field_name, raw_date)

    def _owner_type(self, document_number: str) -> str:
        if len(document_number) == CPF_LENGTH:
            return Account.PERSON

        return Account.COMPANY

    def _payload_hash(self, pix_payload: dict, payer_document: str, payee_document: str) -> str:
        """A impressão digital do conteúdo, para comparar reenvios do mesmo `id`.

        O hash é do payload NORMALIZADO, com os documentos só com dígitos:
        "123.456.789-09" e "12345678909" são o mesmo CPF, e o cliente que
        reenvia formatando o documento de outro jeito está reenviando o
        mesmo Pix — não pedindo outro. `sort_keys` faz o mesmo pela ordem
        dos campos.

        O `deepcopy` não é frescura: sem ele, a troca dos documentos sujaria
        o payload que vai ser gravado como chegou, em `raw_payload`.
        """
        normalized_payload = deepcopy(pix_payload)
        normalized_payload["source_account"]["owner"]["document_number"] = payer_document
        normalized_payload["destination_account"]["owner"]["document_number"] = payee_document

        canonical = json.dumps(normalized_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
