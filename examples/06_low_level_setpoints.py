"""06 - Low-level setpoints and the commander watchdog.

Low-level setpoints must be sent CONTINUOUSLY (here every 0.1 s). The
firmware stops the drone if they stop arriving:
  * after 0.5 s without a setpoint it stops moving sideways,
  * after 2 s the motors switch off and the drone falls.
Try it: set STOP_SENDING = True and watch what happens.

Simulator:   python -m cfsim 06_low_level_setpoints.py
Real drone:  python 06_low_level_setpoints.py   (with STOP_SENDING = False!)
"""
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.utils import uri_helper

URI = uri_helper.uri_from_env(default='radio://0/80/2M/E7E7E7E7E7')
STOP_SENDING = False


def send_for(cf, seconds, vx, vy, yawrate, z):
    """Send the same hover setpoint every 0.1 s for some time."""
    for _ in range(int(seconds * 10)):
        cf.commander.send_hover_setpoint(vx, vy, yawrate, z)
        time.sleep(0.1)


cflib.crtp.init_drivers()

with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    cf = scf.cf
    cf.supervisor.send_arming_request(True)
    time.sleep(1.0)

    # Take off by slowly raising the target height
    for z10 in range(1, 6):
        send_for(cf, 0.5, 0, 0, 0, z10 / 10)
    send_for(cf, 2, 0.3, 0, 0, 0.5)       # forward 0.3 m/s for 2 s
    send_for(cf, 2, 0, 0, 45, 0.5)        # turn left at 45 deg/s

    if STOP_SENDING:
        print('Stopped sending setpoints ...')
        time.sleep(4)

    # Land by lowering the target height, then stop the motors
    for z10 in range(5, 0, -1):
        send_for(cf, 0.5, 0, 0, 0, z10 / 10)
    cf.commander.send_stop_setpoint()
    cf.commander.send_notify_setpoint_stop()
print('Done')
