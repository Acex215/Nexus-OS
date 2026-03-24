from .kernel import NexusKernel
from .contracts import get_contract, load_contract_info
from .token_client import TokenClient
from .nexus_storage import NexusStorage

# FlockCoordinator may not be deployed yet — import lazily
try:
    from .flock_client import FlockClient
except FileNotFoundError:
    FlockClient = None

# TournamentManager may not be deployed yet — import lazily
try:
    from .tournament_client import TournamentClient
except FileNotFoundError:
    TournamentClient = None

__version__ = '0.4.0'
__all__ = [
    'NexusKernel',
    'TokenClient',
    'FlockClient',
    'TournamentClient',
    'NexusStorage',
    'get_contract',
    'load_contract_info',
]
