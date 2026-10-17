import hashlib
import json
from datetime import datetime
from typing import Tuple

from controllers.base_controller import BaseController
from dtos import PixAnalysisDTO
from errors import InvalidDate, InvalidDocumentNumber, NoActivePolicy, NotFoundPixTransaction, PixTransactionConflict
from models import Account, AnalysisStatus
from repositories import (
    AccountRepository,
    AnalysisRepository,
    DeviceRepository,
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
        self.device_repository = DeviceRepository(self.context)
        self.pix_transaction_repository = PixTransactionRepository(self.context)
        self.policy_repository = PolicyRepository(self.context)

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

        self.pix_transaction_repository.lock(self._lock_keys(pix))

        recorded_pix = self.pix_transaction_repository.get_by_external_id(pix["external_id"])
        if recorded_pix is not None:
            return self._replay(recorded_pix, pix), False

        policy = self.policy_repository.get_active()
        if policy is None:
            raise NoActivePolicy()

        pix_transaction = self._record_pix(pix)

        analysis = self.analysis_repository.create(
            analysis_data={
                "pix_transaction": pix_transaction,
                "policy_version": policy,
                "typology": None,
                "recommended_action": "none",
                "score_ato": 0,
                "score_app": 0,
                "score_mule": 0,
                "path": "fast",
                "layers": [0, 1],
                "features": {},
            },
            status_enumerator=AnalysisStatus.APPROVED,
        )

        analysis_dto = PixAnalysisDTO.obj_to_dict(analysis)
        self.session.commit()

        return analysis_dto, True

    def get_by_id(self, pix_id: str) -> dict:
        self.logger.debug(f"Buscando a análise do Pix {pix_id}")

        pix_transaction = self.pix_transaction_repository.get_by_external_id(pix_id)

        if pix_transaction is None:
            raise NotFoundPixTransaction(pix_id)

        return PixAnalysisDTO.obj_to_dict(pix_transaction.analysis)

    def _replay(self, recorded_pix, pix: dict) -> dict:
        """O mesmo `id` de novo: retentativa devolve o gravado; conteúdo novo é conflito.

        Nada é reavaliado nem contado de novo — um retry de rede não pode
        virar uma segunda tentativa na regra de velocidade.
        """
        if recorded_pix.payload_hash != pix["payload_hash"]:
            raise PixTransactionConflict(pix["external_id"])

        return PixAnalysisDTO.obj_to_dict(recorded_pix.analysis)

    def _record_pix(self, pix: dict):
        source_account = self.account_repository.get_or_create(pix["source_account"])
        destination_account = self.account_repository.get_or_create(pix["destination_account"])
        device = self.device_repository.get_or_create(pix["device_id"], pix["transaction_date"])

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

    def _lock_keys(self, pix: dict) -> list:
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
            f"pix:{pix['external_id']}",
            f"document:{pix['payer_document']}",
            f"device:{pix['device_id']}",
        }

        if pix["payee_type"] == Account.PERSON:
            lock_keys.add(f"document:{pix['payee_document']}")

        return sorted(lock_keys)

    def _parse_pix(self, pix_payload: dict) -> dict:
        """O payload já conferido pelo schema, virado nos valores que as regras usam.

        O schema garantiu o FORMATO. O que ele não sabe, e é cobrado
        aqui com 422: se o CPF/CNPJ fecha a conta dos dígitos
        verificadores e se a data existe no calendário.
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
            "payload_hash": self._payload_hash(pix_payload),
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
            "ip": source["ip"],
            "latitude": latitude,
            "longitude": longitude,
            "raw_payload": pix_payload,
        }

    def _parse_document(self, raw_document: str) -> str:
        if not is_valid_document(raw_document):
            raise InvalidDocumentNumber(raw_document)

        return only_digits(raw_document)

    def _parse_date(self, field_name: str, raw_date: str) -> datetime:
        try:
            return datetime.fromisoformat(raw_date)
        except ValueError:
            raise InvalidDate(field_name, raw_date)

    def _owner_type(self, document_number: str) -> str:
        if len(document_number) == CPF_LENGTH:
            return Account.PERSON

        return Account.COMPANY

    def _payload_hash(self, pix_payload: dict) -> str:
        """A impressão digital do conteúdo, para comparar reenvios do mesmo `id`.

        `sort_keys` faz a ordem das chaves não importar: o mesmo Pix com os
        campos em outra ordem continua sendo o mesmo Pix.
        """
        canonical = json.dumps(pix_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
