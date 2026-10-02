"""Simulated cflib.crazyflie: the Crazyflie object and its subsystems."""
import threading
import time

from cfsim.engine import get_engine

from .log import Log

__all__ = ['Crazyflie', 'State']


class State:
    DISCONNECTED = 0
    INITIALIZED = 1
    CONNECTED = 2
    SETUP_FINISHED = 3


class Caller:
    """Same as cflib.utils.callbacks.Caller."""

    def __init__(self):
        self.callbacks = []

    def add_callback(self, cb):
        if cb not in self.callbacks:
            self.callbacks.append(cb)

    def remove_callback(self, cb):
        if cb in self.callbacks:
            self.callbacks.remove(cb)

    def call(self, *args):
        for cb in list(self.callbacks):
            cb(*args)


class Crazyflie:
    """Simulated Crazyflie. Same attributes and methods students use on the
    real one: commander, high_level_commander, log, param, supervisor,
    platform and the connection callbacks."""

    def __init__(self, link=None, ro_cache=None, rw_cache=None):
        self.link_uri = ''
        self.state = State.DISCONNECTED
        self._drone = None

        self.connected = Caller()
        self.fully_connected = Caller()
        self.disconnected = Caller()
        self.connection_failed = Caller()
        self.connection_lost = Caller()
        self.connection_requested = Caller()
        self.link_established = Caller()
        self.link_quality_updated = Caller()
        self.packet_received = Caller()
        self.packet_sent = Caller()

        self.commander = Commander(self)
        self.high_level_commander = HighLevelCommander(self)
        self.param = Param(self)
        self.log = Log(self)
        self.supervisor = Supervisor(self)
        self.platform = PlatformService(self)

    # ------------------------------------------------------------ link
    def open_link(self, link_uri):
        self.link_uri = link_uri
        self.connection_requested.call(link_uri)
        self.state = State.INITIALIZED

        def connect():
            time.sleep(0.3)                          # pretend radio handshake
            self._drone = get_engine().get_drone(link_uri)
            self.state = State.CONNECTED
            self.link_established.call(link_uri)
            self.connected.call(link_uri)
            self.log._start()
            time.sleep(0.2)                          # pretend TOC download
            self.state = State.SETUP_FINISHED
            self.param._fire_initial_callbacks()
            self.fully_connected.call(link_uri)

        threading.Thread(target=connect, name='cfsim-connect', daemon=True).start()

    def close_link(self):
        uri = self.link_uri
        self.log._stop()
        was = self.state
        self.state = State.DISCONNECTED
        self._drone = None
        if was != State.DISCONNECTED:
            self.disconnected.call(uri)

    def is_connected(self):
        return self.state == State.SETUP_FINISHED

    def send_packet(self, pk, expected_reply=(), resend=False, timeout=0.2):
        pass   # raw packets are not simulated

    # ------------------------------------------------------------ helpers
    def _sim(self):
        if self._drone is None:
            raise Exception('Crazyflie is not connected')
        return self._drone

    def _do(self, fn, *args):
        eng = get_engine()
        with eng.lock:
            return fn(*args)


class Commander:
    """Low-level setpoints (must be sent continuously, like on the real drone)."""

    def __init__(self, cf):
        self._cf = cf
        self._x_mode = False

    def set_client_xmode(self, enabled):
        self._x_mode = enabled

    def send_setpoint(self, roll, pitch, yawrate, thrust):
        if thrust > 0xFFFF or thrust < 0:
            raise ValueError('Thrust must be between 0 and 0xFFFF')
        if self._x_mode:
            roll, pitch = 0.707 * (roll - pitch), 0.707 * (roll + pitch)
        d = self._cf._sim()
        self._cf._do(d.set_low, 'attitude', (roll, pitch, yawrate, thrust))

    def send_notify_setpoint_stop(self, remain_valid_milliseconds=0):
        d = self._cf._sim()
        self._cf._do(d.notify_stop)

    def send_stop_setpoint(self):
        d = self._cf._sim()
        self._cf._do(d.set_low, 'stop', ())

    def send_velocity_world_setpoint(self, vx, vy, vz, yawrate):
        d = self._cf._sim()
        self._cf._do(d.set_low, 'velocity', (vx, vy, vz, yawrate))

    def send_zdistance_setpoint(self, roll, pitch, yawrate, zdistance):
        d = self._cf._sim()
        self._cf._do(d.set_low, 'zdistance', (roll, pitch, yawrate, zdistance))

    def send_hover_setpoint(self, vx, vy, yawrate, zdistance):
        d = self._cf._sim()
        self._cf._do(d.set_low, 'hover', (vx, vy, yawrate, zdistance))

    def send_position_setpoint(self, x, y, z, yaw):
        d = self._cf._sim()
        self._cf._do(d.set_low, 'position', (x, y, z, yaw))

    def send_full_state_setpoint(self, pos, vel, acc, orientation, rollrate, pitchrate, yawrate):
        self.send_position_setpoint(pos[0], pos[1], pos[2], 0.0)

    def send_setpoint_manual(self, *args, **kwargs):
        raise NotImplementedError('send_setpoint_manual() is not simulated in cfsim')


class HighLevelCommander:
    """Trajectories planned on board; no need to send anything continuously."""
    ALL_GROUPS = 0
    TRAJECTORY_LOCATION_MEM = 1
    TRAJECTORY_TYPE_POLY4D = 0
    TRAJECTORY_TYPE_POLY4D_COMPRESSED = 1

    def __init__(self, cf):
        self._cf = cf

    def set_group_mask(self, group_mask=ALL_GROUPS):
        pass

    def takeoff(self, absolute_height_m, duration_s, group_mask=ALL_GROUPS, yaw=0.0):
        d = self._cf._sim()
        self._cf._do(d.hl_takeoff, absolute_height_m, duration_s, yaw)

    def land(self, absolute_height_m, duration_s, group_mask=ALL_GROUPS, yaw=0.0):
        d = self._cf._sim()
        self._cf._do(d.hl_land, absolute_height_m, duration_s, yaw)

    def stop(self, group_mask=ALL_GROUPS):
        d = self._cf._sim()
        self._cf._do(d.hl_stop)

    def go_to(self, x, y, z, yaw, duration_s, relative=False, linear=False,
              group_mask=ALL_GROUPS):
        d = self._cf._sim()
        self._cf._do(d.hl_goto, x, y, z, yaw, duration_s, relative)

    def spiral(self, *args, **kwargs):
        raise NotImplementedError('spiral() is not simulated in cfsim')

    def start_trajectory(self, *args, **kwargs):
        raise NotImplementedError('Uploaded trajectories are not simulated in cfsim')

    def define_trajectory(self, *args, **kwargs):
        raise NotImplementedError('Uploaded trajectories are not simulated in cfsim')


class Param:
    """Parameters. Known ones behave like the real drone; unknown ones are
    accepted (with a note) so scripts written for the real drone still run."""

    def __init__(self, cf):
        self._cf = cf
        self._values = {}
        self._callbacks = []        # (group, name, cb)
        self._noted = set()
        self.all_updated = Caller()
        self.is_updated = True

    def _defaults(self):
        eng = get_engine()
        decks = eng.decks
        return {
            'commander.enHighLevel': 1,
            'stabilizer.estimator': 2,
            'stabilizer.controller': 1,
            'kalman.resetEstimation': 0,
            'deck.bcFlow2': int('flow' in decks),
            'deck.bcMultiranger': int('multiranger' in decks),
            'deck.bcLighthouse4': int(eng.positioning == 'lighthouse'),
            'deck.bcAI': 0,
            'deck.bcLoco': 0,
            'motorPowerSet.enable': 0,
            'led.bitmask': 0,
            'ring.effect': 0,
        }

    def _get(self, name):
        if name in self._values:
            return self._values[name]
        return self._defaults().get(name)

    def set_value(self, complete_name, value):
        if '.' not in complete_name:
            raise KeyError(f'{complete_name} not in param TOC (use "group.name")')
        if complete_name not in self._defaults() and complete_name not in self._noted:
            self._noted.add(complete_name)
            get_engine().message(f'parameter {complete_name} has no effect in the simulator')
        self._values[complete_name] = value
        if complete_name == 'kalman.resetEstimation' and str(value) == '1':
            d = self._cf._sim()
            self._cf._do(d.reset_estimator)
        group, name = complete_name.split('.', 1)
        for g, n, cb in list(self._callbacks):
            if (g in (None, group)) and (n in (None, name)):
                cb(complete_name, str(value))

    def set_value_raw(self, complete_name, type, value):
        self.set_value(complete_name, value)

    def get_value(self, complete_name, timeout=60):
        v = self._get(complete_name)
        if v is None:
            raise KeyError(f'{complete_name} not in param TOC')
        return str(v)

    def add_update_callback(self, group=None, name=None, cb=None):
        self._callbacks.append((group, name, cb))
        if self._cf.is_connected():
            threading.Timer(0.05, self._fire_one, args=(group, name, cb)).start()

    def remove_update_callback(self, group, name=None, cb=None):
        self._callbacks = [c for c in self._callbacks if c[2] is not cb]

    def request_param_update(self, complete_name):
        group, name = complete_name.split('.', 1)
        self._fire_one(group, name, None)

    def _fire_one(self, group, name, only_cb):
        for full in list(self._defaults()) + list(self._values):
            g, n = full.split('.', 1)
            if (group in (None, g)) and (name in (None, n)):
                for cg, cn, cb in list(self._callbacks):
                    if only_cb is not None and cb is not only_cb:
                        continue
                    if (cg in (None, g)) and (cn in (None, n)):
                        cb(full, str(self._get(full)))

    def _fire_initial_callbacks(self):
        for g, n, cb in list(self._callbacks):
            self._fire_one(g, n, cb)
        self.all_updated.call()


class Supervisor:
    def __init__(self, cf):
        self._cf = cf

    def send_arming_request(self, do_arm: bool):
        d = self._cf._sim()

        def arm():
            d.armed = bool(do_arm) or not d.m['requires_arming']
            if not do_arm and d.motors:
                d._motors_off('disarmed')
        self._cf._do(arm)

    def send_crash_recovery_request(self):
        d = self._cf._sim()

        def recover():
            if d.crashed and d.on_ground:
                d.crashed = False
                d._warned.discard('crashed_cmd')
                get_engine().message(f'drone {d.label} recovered from crash')
        self._cf._do(recover)

    def send_emergency_stop(self):
        d = self._cf._sim()
        self._cf._do(d._motors_off, 'emergency stop')

    def send_emergency_stop_watchdog(self):
        pass

    def is_armed(self):
        return self._cf._sim().armed

    def is_auto_armed(self):
        return not self._cf._sim().m['requires_arming']

    def can_be_armed(self):
        return not self._cf._sim().crashed

    def can_fly(self):
        d = self._cf._sim()
        return d.armed and not d.crashed and not d.battery_empty

    def is_flying(self):
        d = self._cf._sim()
        return d.motors and not d.on_ground

    def is_tumbled(self):
        return False

    def is_locked(self):
        return False

    def is_crashed(self):
        return self._cf._sim().crashed


class PlatformService:
    def __init__(self, cf):
        self._cf = cf

    def send_arming_request(self, do_arm):
        self._cf.supervisor.send_arming_request(do_arm)

    def send_crash_recovery_request(self):
        self._cf.supervisor.send_crash_recovery_request()

    def get_protocol_version(self):
        return 10

    def get_device_type_name(self):
        return self._cf._sim().m['label'] + ' (simulated)'

    def set_continous_wave(self, enabled):
        pass
