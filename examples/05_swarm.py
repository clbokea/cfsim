"""05 - A small swarm: three drones take off together and fly a square.

Simulator:   python -m cfsim --world arena 05_swarm.py
Real drones: python 05_swarm.py   (change the URIs to your drones)
"""
import time

import cflib.crtp
from cflib.crazyflie.swarm import CachedCfFactory, Swarm
from cflib.positioning.motion_commander import MotionCommander

URIS = [
    'radio://0/80/2M/E7E7E7E701',
    'radio://0/80/2M/E7E7E7E702',
    'radio://0/80/2M/E7E7E7E703',
]

# Each drone gets its own height so they never meet
HEIGHTS = {uri: [0.4 + 0.2 * i] for i, uri in enumerate(URIS)}


def arm(scf):
    scf.cf.supervisor.send_arming_request(True)
    time.sleep(1.0)


def fly_square(scf, height):
    with MotionCommander(scf, default_height=height) as mc:
        time.sleep(1.0)
        for _ in range(4):
            mc.forward(0.5)
            mc.turn_left(90)
        time.sleep(1.0)


cflib.crtp.init_drivers()
factory = CachedCfFactory(rw_cache='./cache')

with Swarm(URIS, factory=factory) as swarm:
    swarm.parallel_safe(arm)
    swarm.parallel_safe(fly_square, args_dict=HEIGHTS)
print('Done')
