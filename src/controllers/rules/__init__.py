from controllers.rules.base_rule import BaseRule
from controllers.rules.conta_recebedora_rule import ContaRecebedoraRule
from controllers.rules.limite_rule import LimiteRule
from controllers.rules.marcacao_rule import MarcacaoRule
from controllers.rules.perfil_rule import PerfilRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.rastro_rule import RastroRule
from controllers.rules.ritmo_rule import RitmoRule
from controllers.rules.signal_result import SignalResult

# As regras do motor, na ordem em que aparecem no metadata. As Regras 5
# (quem opera), 7 (rastro do dinheiro) e 8 (anomalia) entram na Fase 3 e
# na Fase 4, cada uma como mais uma linha aqui.
RULES = [
    MarcacaoRule(),
    LimiteRule(),
    RitmoRule(),
    PerfilRule(),
    ContaRecebedoraRule(),
    RastroRule(),
]
