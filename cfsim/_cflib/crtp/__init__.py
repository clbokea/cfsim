"""Simulated cflib.crtp: no radio needed."""


def init_drivers(*args, **kwargs):
    """Nothing to initialise in the simulator."""
    return None


def scan_interfaces(address=None):
    from cfsim.engine import get_engine
    uris = list(get_engine().drones.keys()) or ['radio://0/80/2M/E7E7E7E7E7']
    return [[u, 'simulated'] for u in uris]


def get_interfaces_status():
    return {'radio': 'simulated (cfsim)'}


def get_link_driver(uri, *args, **kwargs):
    return None
