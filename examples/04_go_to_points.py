"""04 - Fly to positions with the PositionHlCommander.

With a Flow deck, positions are measured from the take-off spot (0, 0).

Simulator:   python -m cfsim 04_go_to_points.py
Real drone:  python 04_go_to_points.py
"""
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.position_hl_commander import PositionHlCommander
from cflib.utils import uri_helper

URI = uri_helper.uri_from_env(default='radio://0/80/2M/E7E7E7E7E7')

WAYPOINTS = [
    (1.0, 0.0, 0.5),
    (1.0, 1.0, 1.0),
    (0.0, 1.0, 0.5),
    (0.0, 0.0, 0.5),
]

cflib.crtp.init_drivers()

with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    scf.cf.supervisor.send_arming_request(True)
    time.sleep(1.0)

    with PositionHlCommander(scf, default_velocity=0.4, default_height=0.5) as pc:
        for x, y, z in WAYPOINTS:
            print(f'Going to x={x} y={y} z={z}')
            pc.go_to(x, y, z)
print('Done')
