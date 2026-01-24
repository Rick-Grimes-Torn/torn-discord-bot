import inspect

from . import faction
#from . import api_keys
from . import balance
from . import leader
#from . import war_stats
#from . import leaderboard
from . import help_cmd
#from . import chain_timer
from . import negan
from . import status_cmd
#from . import war_chain_stats
#from . import market
#from . import war
#from . import chain
from . import neganquote
from . import warstats







def _call_register(mod, client, tree):
    """
    Support both legacy register(tree) and newer register(client, tree).
    """
    fn = getattr(mod, "register", None)
    if fn is None:
        return

    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        if len(params) == 1:
            fn(tree)
        else:
            fn(client, tree)
    except Exception:
        # Fallback: try new style then old style
        try:
            fn(client, tree)
        except TypeError:
            fn(tree)


def register_all(client, tree):
    _call_register(faction, client, tree)
#   _call_register(api_keys, client, tree)
    _call_register(balance, client, tree)
    _call_register(leader, client, tree)
#   _call_register(war_stats, client, tree)
#   _call_register(leaderboard, client, tree)
    _call_register(help_cmd, client, tree)
    _call_register(negan, client, tree)
#   _call_register(chain_timer, client, tree)
    _call_register(status_cmd, client, tree)
#   _call_register(war_chain_stats, client, tree)
    _call_register(market, client, tree)
    _call_register(war, client, tree)
    _call_register(chain, client, tree)
    _call_register(neganquote, client, tree)





