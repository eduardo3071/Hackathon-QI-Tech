from controllers.rules.anomalia_rule import AnomaliaRule
from controllers.rules.base_rule import BaseRule
from controllers.rules.conta_recebedora_rule import ContaRecebedoraRule
from controllers.rules.limite_rule import LimiteRule
from controllers.rules.marcacao_rule import MarcacaoRule
from controllers.rules.perfil_rule import PerfilRule
from controllers.rules.quem_opera_rule import QuemOperaRule
from controllers.rules.policy_parameters import PolicyParameters
from controllers.rules.rastro_rule import RastroRule
from controllers.rules.ritmo_rule import RitmoRule
from controllers.rules.signal_result import SignalResult

# As regras do motor, na ordem em que aparecem no metadata.
RULES = [
    MarcacaoRule(),
    LimiteRule(),
    RitmoRule(),
    PerfilRule(),
    QuemOperaRule(),
    ContaRecebedoraRule(),
    RastroRule(),
    AnomaliaRule(),
]
