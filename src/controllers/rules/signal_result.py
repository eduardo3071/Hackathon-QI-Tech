from dataclasses import dataclass, field
from typing import Optional

# O que cada sinal pode dizer sobre o Pix.
#   pass           — conferiu e está dentro do limite
#   warn           — sinal de risco que pontua num placar (não decide sozinho)
#   two_factor     — pede 2FA sozinho (regra dura)
#   reject         — recusa sozinho (regra dura)
#   not_evaluated  — faltou dado, ou o sinal está desligado na política
#   not_needed     — não precisava rodar (mesma titularidade, recebedor PJ...)
PASS = "pass"
WARN = "warn"
TWO_FACTOR = "two_factor"
REJECT = "reject"
NOT_EVALUATED = "not_evaluated"
NOT_NEEDED = "not_needed"

# Os três placares. Cada tipologia de fraude pede uma resposta diferente:
# o invasor (ato) não tem o segundo fator; a vítima de golpe (app) passa
# no 2FA; a conta laranja (mule) recebe de quem quer que seja.
ATO = "ato"
APP = "app"
MULE = "mule"


@dataclass(frozen=True)
class SignalResult:
    """O veredito de UM sinal: o que se viu, contra qual limite, e o que deu."""

    rule_code: str
    signal_code: str
    layer: int
    outcome: str
    message: str
    typology: Optional[str] = None
    points: int = 0
    observed: dict = field(default_factory=dict)
    threshold: dict = field(default_factory=dict)

    def is_risk(self) -> bool:
        return self.outcome in (WARN, TWO_FACTOR, REJECT) or self.points > 0
