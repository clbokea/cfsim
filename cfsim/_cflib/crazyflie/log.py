"""Simulated cflib.crazyflie.log: LogConfig and the log subsystem.

Same rules as the real drone: variables must exist in the log TOC (and the
right deck must be present), one log block holds at most 26 bytes, and data
arrives through callbacks at the requested period."""
import math
import random
import threading
import time

from cfsim.engine import get_engine

TYPE_SIZE = {'uint8_t': 1, 'int8_t': 1, 'uint16_t': 2, 'int16_t': 2,
             'uint32_t': 4, 'int32_t': 4, 'float': 4, 'FP16': 2}
MAX_LOG_DATA_PACKET_SIZE = 26
RANGE_OUT_MM = 32766


def _mm(v):
    return RANGE_OUT_MM if v is None else int(round(v * 1000))


def _r(name):
    return lambda d: _mm(d.ranges()[name])


# name -> (type, getter(drone), required deck or None)
LOG_TOC = {
    'stateEstimate.x': ('float', lambda d: d.est_pos()[0], None),
    'stateEstimate.y': ('float', lambda d: d.est_pos()[1], None),
    'stateEstimate.z': ('float', lambda d: d.est_pos()[2], None),
    'stateEstimate.vx': ('float', lambda d: d.vel[0], None),
    'stateEstimate.vy': ('float', lambda d: d.vel[1], None),
    'stateEstimate.vz': ('float', lambda d: d.vel[2], None),
    'stateEstimate.roll': ('float', lambda d: d.roll, None),
    'stateEstimate.pitch': ('float', lambda d: d.pitch, None),
    'stateEstimate.yaw': ('float', lambda d: d.yaw, None),
    'kalman.stateX': ('float', lambda d: d.est_pos()[0], None),
    'kalman.stateY': ('float', lambda d: d.est_pos()[1], None),
    'kalman.stateZ': ('float', lambda d: d.est_pos()[2], None),
    'stabilizer.roll': ('float', lambda d: d.roll, None),
    'stabilizer.pitch': ('float', lambda d: d.pitch, None),
    'stabilizer.yaw': ('float', lambda d: d.yaw, None),
    'stabilizer.thrust': ('float', lambda d: float(d.m['hover_thrust']) if d.motors else 0.0, None),
    'acc.x': ('float', lambda d: math.sin(math.radians(-d.pitch)), None),
    'acc.y': ('float', lambda d: math.sin(math.radians(d.roll)), None),
    'acc.z': ('float', lambda d: 1.0, None),
    'gyro.x': ('float', lambda d: 0.0, None),
    'gyro.y': ('float', lambda d: 0.0, None),
    'gyro.z': ('float', lambda d: d.yaw_rate, None),
    'range.front': ('uint16_t', _r('front'), 'multiranger'),
    'range.back': ('uint16_t', _r('back'), 'multiranger'),
    'range.left': ('uint16_t', _r('left'), 'multiranger'),
    'range.right': ('uint16_t', _r('right'), 'multiranger'),
    'range.up': ('uint16_t', _r('up'), 'multiranger'),
    'range.zrange': ('uint16_t', _r('zrange'), 'flow'),
    'pm.vbat': ('float', lambda d: d.vbat(), None),
    'pm.batteryLevel': ('uint8_t', lambda d: int(max(0, min(100, (d.vbat() - 3.0) / 1.15 * 100))), None),
    'pm.state': ('int8_t', lambda d: 3 if d.vbat() < 3.2 else 0, None),
    'radio.rssi': ('uint8_t', lambda d: d.rssi(), None),
    'supervisor.info': ('uint16_t', lambda d: (int(d.armed) << 1) | (int(d.motors and not d.on_ground) << 5) | (int(d.crashed) << 7), None),
}


def available_variables():
    eng = get_engine()
    return sorted(n for n, (_, _, deck) in LOG_TOC.items() if deck is None or deck in eng.decks)


class Caller:
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


class LogVariable:
    TOC_TYPE = 0
    MEM_TYPE = 1

    def __init__(self, name='', fetchAs='float', storedAs='float', type=TOC_TYPE):
        self.name = name
        self.fetch_as = fetchAs
        self.stored_as = storedAs
        self.type = type


class LogConfig:
    def __init__(self, name, period_in_ms):
        self.name = name
        self.period_in_ms = period_in_ms
        self.variables = []
        self.default_fetch_as = []
        self.cf = None
        self.id = None
        self.useV2 = True
        self.added = False
        self.started = False
        self.valid = False
        self.pending = False
        self.data_received_cb = Caller()
        self.error_cb = Caller()
        self.started_cb = Caller()
        self.added_cb = Caller()
        self.err_no = 0
        self._next_due = 0.0

    @property
    def period_in_ms(self):
        return self._period_ms

    @period_in_ms.setter
    def period_in_ms(self, value):
        self._period_ms = value
        self.period = int(value / 10)

    def add_variable(self, name, fetch_as=None):
        self.variables.append(LogVariable(name, fetch_as, fetch_as))
        if fetch_as is None:
            self.default_fetch_as.append(name)

    def add_memory(self, *args, **kwargs):
        raise NotImplementedError('Memory logging is not simulated in cfsim')

    def create(self):
        pass

    def start(self):
        if self.cf is None:
            raise AttributeError('The log configuration must be added to a '
                                 'Crazyflie first: cf.log.add_config(logconf)')
        self.started = True
        self._next_due = 0.0
        self.started_cb.call(self, True)

    def stop(self):
        self.started = False
        self.started_cb.call(self, False)

    def delete(self):
        self.started = False
        if self.cf is not None and self in self.cf.log.log_blocks:
            self.cf.log.log_blocks.remove(self)
        self.added = False


class Log:
    def __init__(self, crazyflie):
        self.cf = crazyflie
        self.log_blocks = []
        self.block_added_cb = Caller()
        self._running = False
        self._thread = None

    def add_config(self, logconf):
        eng = get_engine()
        size = 0
        for var in logconf.variables:
            entry = LOG_TOC.get(var.name)
            if entry is None or (entry[2] is not None and entry[2] not in eng.decks):
                hint = ''
                if entry is not None:
                    hint = f" (needs the {entry[2]} deck - it is not enabled in the simulator)"
                raise KeyError(f'Variable {var.name} not in TOC{hint}')
            if var.fetch_as is None:
                var.fetch_as = var.stored_as = entry[0]
            size += TYPE_SIZE.get(var.fetch_as, 4)
        if size > MAX_LOG_DATA_PACKET_SIZE:
            raise AttributeError(
                f'The log configuration is too large ({size} bytes, max '
                f'{MAX_LOG_DATA_PACKET_SIZE}). Split it into two LogConfigs.')
        if not (10 <= logconf.period_in_ms <= 2550):
            raise AttributeError('period_in_ms must be between 10 and 2550')
        logconf.cf = self.cf
        logconf.valid = True
        logconf.added = True
        self.log_blocks.append(logconf)
        self.block_added_cb.call(logconf)
        logconf.added_cb.call(logconf, True)

    def reset(self):
        for lc in list(self.log_blocks):
            lc.delete()

    # ------------------------------------------------------------ internal
    def _start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name='cfsim-log', daemon=True)
        self._thread.start()

    def _stop(self):
        self._running = False

    def _run(self):
        eng = get_engine()
        while self._running:
            now = time.monotonic()
            due = []
            for lc in list(self.log_blocks):
                if lc.started and now >= lc._next_due:
                    lc._next_due = now + lc.period_in_ms / 1000.0 if lc._next_due == 0.0 \
                        else max(lc._next_due + lc.period_in_ms / 1000.0, now)
                    due.append(lc)
            if due:
                drone = self.cf._drone
                if drone is None:
                    break
                batch = []
                with eng.lock:
                    ts = int((now - drone.boot_time) * 1000)
                    for lc in due:
                        data = {}
                        for var in lc.variables:
                            val = LOG_TOC[var.name][1](drone)
                            if var.fetch_as and var.fetch_as not in ('float', 'FP16'):
                                val = int(val)
                            elif eng.noise and LOG_TOC[var.name][0] == 'float' \
                                    and var.name.startswith(('stateEstimate.v', 'acc.', 'gyro.')):
                                val = float(val) + random.gauss(0, 0.01)
                            data[var.name] = val
                        batch.append((ts, data, lc))
                for ts, data, lc in batch:
                    try:
                        lc.data_received_cb.call(ts, data, lc)
                    except Exception as e:          # same as cflib: report, keep going
                        print(f'[cfsim] error in log callback: {e!r}')
            time.sleep(0.004)
