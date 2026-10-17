from typing import Optional

from models import PolicyVersion


class PolicyParameters:
    """Os parâmetros da política ativa, por código de sinal.

    As regras leem daqui e de mais lugar nenhum: nenhum limite mora em
    constante no código. Trocar um parâmetro é trocar uma linha da tabela
    `rule_parameter`, sem deploy.
    """

    def __init__(self, policy_version: PolicyVersion) -> None:
        self.version = policy_version.version
        self.ml_mode = policy_version.ml_mode
        self._parameters = {}
        self._enabled = {}

        for rule_parameter in policy_version.rule_parameters:
            self._parameters[rule_parameter.signal_code] = rule_parameter.parameters
            self._enabled[rule_parameter.signal_code] = rule_parameter.enabled

    def is_enabled(self, signal_code: str) -> bool:
        """Sinal que não está na política conta como desligado: sem parâmetro, não há limite."""
        return self._enabled.get(signal_code, False)

    def of(self, signal_code: str) -> Optional[dict]:
        return self._parameters.get(signal_code)
