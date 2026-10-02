"""01 - First flight: take off, fly a square, land.

Simulator:   python -m cfsim 01_hello_fly.py
Real drone:  python 01_hello_fly.py
"""
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander
from cflib.utils import uri_helper

URI = uri_helper.uri_from_env(default='radio://0/80/2M/E7E7E7E7E7')

cflib.crtp.init_drivers()

with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    # Brushless drones must be armed first (harmless on a Crazyflie 2.1+)
    scf.cf.supervisor.send_arming_request(True)
    time.sleep(1.0)

    with MotionCommander(scf, default_height=0.5) as mc:   # takes off here
        time.sleep(1.0)
        for side in range(4):
            print('Side', side + 1)
            mc.forward(0.5)
            mc.turn_left(90)
        time.sleep(1.0)
    # ... and lands when the 'with' block ends
print('Done')
