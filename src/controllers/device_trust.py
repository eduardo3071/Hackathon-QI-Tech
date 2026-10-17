from datetime import datetime, timedelta
from typing import Optional

from models import DeviceOwner


class DeviceTrust:
    """Quando um aparelho é confiável para um pagador — num lugar só.

    Quem LÊ a confiança (o FeatureBuilder, para as regras) e quem a
    ESCREVE (o controller, ao contar um Pix aprovado) fazem a mesma
    pergunta, e não podem ter duas respostas.

    Confiável quando:
      • a biometria facial passou no retorno do 2FA — é o cadastro do
        aparelho que o BCB prevê; ou
      • há N Pix aprovados deste pagador neste aparelho, o primeiro há
        pelo menos X horas. Um Pix aprovado só não basta: senão o ladrão
        "aquece" o aparelho com um Pix de R$ 10, e o seguinte, de
        R$ 5.000, não pede 2FA. Exigir que o primeiro tenha mais de 24 h
        faz a confiança atravessar um dia — o tempo de o titular perceber
        que perdeu o celular.

    E nunca enquanto a confiança está bloqueada: biometria reprovada num
    2FA por suspeita de invasão é o sinal mais forte de que outra pessoa
    está com o aparelho.
    """

    @staticmethod
    def is_trusted(device_owner: Optional[DeviceOwner], at: datetime, parameters: Optional[dict]) -> bool:
        if parameters is None or device_owner is None:
            return False

        if DeviceTrust.is_blocked(device_owner, at, parameters):
            return False

        if device_owner.face_liveness_passed_at is not None and device_owner.face_liveness_passed_at <= at:
            return True

        if device_owner.first_approved_at is None:
            return False

        trusted_since = device_owner.first_approved_at + timedelta(hours=parameters["trusted_min_hours"])

        return device_owner.approved_count >= parameters["trusted_min_approved_pix"] and trusted_since <= at

    @staticmethod
    def is_blocked(device_owner: Optional[DeviceOwner], at: datetime, parameters: Optional[dict]) -> bool:
        """Se `at` cai nas horas seguintes a uma biometria reprovada (e sem biometria aprovada depois dela)."""
        if parameters is None or device_owner is None or device_owner.step_up_failed_at is None:
            return False

        failed_at = device_owner.step_up_failed_at
        if device_owner.face_liveness_passed_at is not None and device_owner.face_liveness_passed_at > failed_at:
            return False

        blocked_until = failed_at + timedelta(hours=parameters["step_up_failed_block_hours"])

        return failed_at <= at < blocked_until
