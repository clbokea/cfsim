"""02 - Read sensors while hovering: position estimate, height and the
Multi-ranger distances, delivered by a log callback.

Simulator:   python -m cfsim 02_read_sensors.py
Real drone:  python 02_read_sensors.py   (needs Flow deck + Multi-ranger)
"""
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander
from cflib.utils import uri_helper

URI = uri_helper.uri_from_env(default='radio://0/80/2M/E7E7E7E7E7')


def position_callback(timestamp, data, logconf):
    print(f"[{timestamp:7d} ms] x={data['stateEstimate.x']:5.2f}  "
          f"y={data['stateEstimate.y']:5.2f}  z={data['stateEstimate.z']:5.2f}")


def range_callback(timestamp, data, logconf):
    # Ranges are in millimetres. Values above 8000 mean "nothing in range".
    def fmt(mm):
        return '  --  ' if mm >= 8000 else f'{mm / 1000:4.2f} m'
    print(f"           front={fmt(data['range.front'])}  back={fmt(data['range.back'])}  "
          f"left={fmt(data['range.left'])}  right={fmt(data['range.right'])}")


cflib.crtp.init_drivers()

# One log block can hold at most 26 bytes: floats are 4 bytes, ranges 2 bytes
log_pos = LogConfig(name='Position', period_in_ms=500)
log_pos.add_variable('stateEstimate.x', 'float')
log_pos.add_variable('stateEstimate.y', 'float')
log_pos.add_variable('stateEstimate.z', 'float')

log_range = LogConfig(name='Ranges', period_in_ms=500)
for name in ('range.front', 'range.back', 'range.left', 'range.right'):
    log_range.add_variable(name)

with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    scf.cf.supervisor.send_arming_request(True)
    time.sleep(1.0)

    scf.cf.log.add_config(log_pos)
    scf.cf.log.add_config(log_range)
    log_pos.data_received_cb.add_callback(position_callback)
    log_range.data_received_cb.add_callback(range_callback)
    log_pos.start()
    log_range.start()

    with MotionCommander(scf, default_height=0.5) as mc:
        time.sleep(3)
        mc.forward(1.0)
        time.sleep(3)

    log_pos.stop()
    log_range.stop()
