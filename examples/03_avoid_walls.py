"""03 - Explore a room without hitting the walls (Multi-ranger).

Fly forward. When a wall is closer than 0.5 m in front, turn left 90 degrees.
Walls that come too close on the left or right push the drone sideways.

Simulator:   python -m cfsim --world obstacles 03_avoid_walls.py
Real drone:  python 03_avoid_walls.py   (needs Flow deck + Multi-ranger)
"""
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander
from cflib.utils import uri_helper
from cflib.utils.multiranger import Multiranger

URI = uri_helper.uri_from_env(default='radio://0/80/2M/E7E7E7E7E7')
SAFE_DISTANCE = 0.5     # metres
FLIGHT_TIME = 40        # seconds


def is_close(distance):
    return distance is not None and distance < SAFE_DISTANCE


cflib.crtp.init_drivers()

with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    scf.cf.supervisor.send_arming_request(True)
    time.sleep(1.0)

    with MotionCommander(scf, default_height=0.5) as mc:
        with Multiranger(scf) as ranger:
            end_time = time.time() + FLIGHT_TIME
            while time.time() < end_time:
                if is_close(ranger.up):         # hand above the drone = stop
                    break
                if is_close(ranger.front):
                    mc.turn_left(90)            # turn on the spot (waits until done)
                    continue
                side = 0.0                      # sideways speed, + = left
                if is_close(ranger.left):
                    side -= 0.2
                if is_close(ranger.right):
                    side += 0.2
                mc.start_linear_motion(0.3, side, 0.0)
                time.sleep(0.1)
            mc.stop()
print('Done')
