"""One simulated Crazyflie: simple physics, controllers, estimator, sensors.

The model is deliberately simple (a point mass that follows velocity
commands with a short delay), but it keeps the behaviour that matters for
programming the real drone:

* the firmware's commander watchdog (no setpoint for 0.5 s -> stop moving,
  no setpoint for 2 s -> motors off and the drone falls),
* Flow deck positioning that is relative to the take-off spot and drifts,
* Multi-ranger / Flow deck ranges in millimetres, with noise and max range,
* the thrust lock for raw setpoints, arming for the Brushless model,
* crashes into walls, the ceiling, other drones and hard landings,
* a battery that runs down while flying.
"""
import math
import random
import time

G = 9.81

MODELS = {
    '2.1+': {
        'label': 'Crazyflie 2.1+', 'color': '#2f7ed8',
        'vmax_xy': 1.5, 'vmax_z': 1.0, 'acc_max': 3.0, 'tau': 0.25,
        'flight_time_s': 7 * 60, 'hover_thrust': 38000,
        'requires_arming': False, 'radius': 0.06,
    },
    'brushless': {
        'label': 'Crazyflie 2.1 Brushless', 'color': '#e8731c',
        'vmax_xy': 2.5, 'vmax_z': 1.5, 'acc_max': 5.0, 'tau': 0.18,
        'flight_time_s': 10 * 60, 'hover_thrust': 26000,
        'requires_arming': True, 'radius': 0.07,
    },
}
MODEL_ALIASES = {'2.1': '2.1+', '21': '2.1+', 'cf21': '2.1+', 'cf2.1+': '2.1+',
                 'bl': 'brushless', 'cf21bl': 'brushless'}

RANGE_MAX_M = 4.0           # VL53L1x max range
RANGE_OUT_MM = 32766        # value reported when nothing is in range
WDT_STABILIZE_S = 0.5       # firmware commander watchdog
WDT_SHUTDOWN_S = 2.0
HARD_LANDING_MS = 3.5       # impact speed that counts as a crash (~0.6 m fall)


def model_name(name):
    key = str(name).strip().lower()
    key = MODEL_ALIASES.get(key, key)
    if key not in MODELS:
        raise ValueError(f"Unknown model '{name}'. Use '2.1+' or 'brushless'.")
    return key


def _wrap_deg(a):
    return (a + 180.0) % 360.0 - 180.0


def _clip(v, lim):
    return max(-lim, min(lim, v))


def _smoothstep(s):
    s = max(0.0, min(1.0, s))
    return s * s * (3 - 2 * s)


class SimDrone:
    def __init__(self, engine, uri, index, start, model='2.1+'):
        self.engine = engine
        self.uri = uri
        self.index = index
        self.model_key = model_name(model)
        self.m = MODELS[self.model_key]
        self.start = start
        self.pos = [start[0], start[1], 0.0]
        self.vel = [0.0, 0.0, 0.0]
        self.yaw = 0.0               # degrees, 0 = +x
        self.yaw_rate = 0.0
        self.roll = 0.0
        self.pitch = 0.0
        self.motors = False
        self.on_ground = True
        self.crashed = False
        self.crash_reason = ''
        self.armed = not self.m['requires_arming']
        self.thrust_locked = True
        self.battery_used_s = 0.0
        self.battery_empty = False

        # Positioning / estimator
        self.est_err = [0.0, 0.0]
        self.est_origin = (start[0], start[1]) if engine.positioning == 'flow' else (0.0, 0.0)

        # Commanding
        self.mode = 'off'            # off | low | hl
        self.low = None              # (kind, values)
        self.low_time = 0.0
        self.hl = None               # dict with trajectory
        self.hl_hold = None          # position held after a trajectory
        self._warned = set()
        self.trail = []

        # Sensor cache
        self._ranges = None
        self._ranges_time = -1.0
        self.boot_time = time.monotonic()

    # ------------------------------------------------------------- helpers
    @property
    def label(self):
        tail = self.uri.rstrip('/').split('/')[-1]
        return f'{self.index + 1}:{tail[-4:]}' if tail else str(self.index + 1)

    def say(self, msg, once_key=None):
        if once_key:
            if once_key in self._warned:
                return
            self._warned.add(once_key)
        self.engine.message(f'[drone {self.label}] {msg}')

    def est_pos(self):
        return (self.pos[0] - self.est_origin[0] + self.est_err[0],
                self.pos[1] - self.est_origin[1] + self.est_err[1],
                self.pos[2])

    def reset_estimator(self):
        self.est_err = [0.0, 0.0]
        if self.engine.positioning == 'flow':
            self.est_origin = (self.pos[0], self.pos[1])

    def _can_fly(self):
        if self.crashed:
            self.say('ignores commands: it has crashed.', 'crashed_cmd')
            return False
        if self.battery_empty:
            self.say('ignores commands: battery is empty.', 'battery_cmd')
            return False
        if not self.armed:
            self.say('is NOT ARMED and ignores flight commands. Brushless drones '
                     'must be armed first: cf.supervisor.send_arming_request(True)',
                     'not_armed')
            return False
        return True

    # ------------------------------------------------- low-level commander
    def set_low(self, kind, values):
        now = self.engine.now()
        if kind == 'stop':
            self.low = None
            self.hl = self.hl_hold = None
            self._motors_off('stop setpoint received')
            return
        if kind == 'attitude':
            thrust = values[3]
            if self.thrust_locked:
                if thrust == 0:
                    self.thrust_locked = False
                else:
                    self.say('ignores send_setpoint(): the thrust lock is on. Send one '
                             'setpoint with thrust 0 first to unlock (same as the real drone).',
                             'thrust_lock')
                    return
        if not self._can_fly():
            return
        self.low = (kind, values)
        self.low_time = now
        self.mode = 'low'
        if kind != 'attitude' or values[3] > 0:
            self._motors_on()

    def notify_stop(self):
        self.low = None
        if self.mode == 'low':
            if self.hl is not None or self.hl_hold is not None:
                self.mode = 'hl'
            elif self.on_ground:
                self.mode = 'off'
                self.motors = False
            else:
                # Hand over to the high-level commander: hold position
                self.mode = 'hl'
                self.hl_hold = self.est_pos() + (self.yaw,)

    # ------------------------------------------------ high-level commander
    def hl_goto(self, x, y, z, yaw, duration, relative=False):
        if not self._can_fly():
            return
        ex, ey, ez = self.est_pos()
        if self.mode == 'hl' and self.hl is not None:
            ex, ey, ez = self.hl_target_now()[:3]
        if relative:
            x, y, z, yaw = ex + x, ey + y, ez + z, self.yaw + yaw
        self.hl = {'from': (ex, ey, ez, self.yaw), 'to': (x, y, z, yaw),
                   't0': self.engine.now(), 'T': max(0.05, float(duration))}
        self.hl_hold = None
        self.mode = 'hl'
        self.low = None
        self._motors_on()

    def hl_takeoff(self, height, duration, yaw=None):
        ex, ey, _ = self.est_pos()
        self.hl_goto(ex, ey, height, self.yaw if yaw is None else yaw, duration)

    def hl_land(self, height, duration, yaw=None):
        ex, ey, _ = self.est_pos()
        if self.mode == 'hl' and self.hl is not None:
            ex, ey = self.hl_target_now()[:2]
        self.hl_goto(ex, ey, height, self.yaw if yaw is None else yaw, duration)
        if self.hl is not None:
            self.hl['landing'] = True

    def hl_stop(self):
        self.hl = self.hl_hold = None
        if self.mode == 'hl':
            self._motors_off('high-level stop')

    def hl_velocity_now(self):
        h = self.hl
        s = (self.engine.now() - h['t0']) / h['T']
        if s <= 0.0 or s >= 1.0:
            return (0.0, 0.0, 0.0)
        ds = 6 * s * (1 - s) / h['T']
        f, t = h['from'], h['to']
        return ((t[0] - f[0]) * ds, (t[1] - f[1]) * ds, (t[2] - f[2]) * ds)

    def hl_target_now(self):
        h = self.hl
        s = _smoothstep((self.engine.now() - h['t0']) / h['T'])
        f, t = h['from'], h['to']
        dyaw = _wrap_deg(t[3] - f[3])
        return (f[0] + (t[0] - f[0]) * s, f[1] + (t[1] - f[1]) * s,
                f[2] + (t[2] - f[2]) * s, f[3] + dyaw * s)

    # ---------------------------------------------------------------- motors
    def _motors_on(self):
        if not self.motors:
            self.motors = True

    def _motors_off(self, why=''):
        self.motors = False
        self.mode = 'off'
        self.low = None
        self.hl = self.hl_hold = None
        if not self.on_ground and self.pos[2] > 0.2 and why and not self.crashed:
            self.say(f'motors stopped in the air ({why}) - it falls!')

    def crash(self, reason):
        if self.crashed:
            return
        self.crashed = True
        self.crash_reason = reason
        self.motors = False
        self.mode = 'off'
        self.low = None
        self.hl = self.hl_hold = None
        self.vel[0] = self.vel[1] = 0.0          # stops at the obstacle and drops
        self.vel[2] = min(self.vel[2], 0.0)
        x, y, z = self.pos
        self.say(f'CRASHED: {reason} at x={x:.2f} y={y:.2f} z={max(0.0, z):.2f} (world)')

    # ---------------------------------------------------------------- physics
    def step(self, dt, now):
        m = self.m
        ax = ay = az = 0.0
        yaw_rate_d = 0.0
        flying_cmd = self.motors and not self.crashed

        if flying_cmd:
            vd, yaw_rate_d, acc_cmd = self._controller(now)
            if acc_cmd is not None:
                ax, ay, az = acc_cmd
            else:
                vdx, vdy, vdz = vd
                tau = m['tau']
                ax = (vdx - self.vel[0]) / tau
                ay = (vdy - self.vel[1]) / tau
                az = (vdz - self.vel[2]) / tau
                a_xy = math.hypot(ax, ay)
                if a_xy > m['acc_max']:
                    ax, ay = ax * m['acc_max'] / a_xy, ay * m['acc_max'] / a_xy
                az = _clip(az, m['acc_max'])
        else:
            az = -G
            yaw_rate_d = 0.0

        if not self.motors:
            ax = -2.0 * self.vel[0] if self.on_ground else -0.3 * self.vel[0]
            ay = -2.0 * self.vel[1] if self.on_ground else -0.3 * self.vel[1]

        self.vel[0] += ax * dt
        self.vel[1] += ay * dt
        self.vel[2] += az * dt
        if self.motors:
            sp = math.hypot(self.vel[0], self.vel[1])
            if sp > m['vmax_xy']:
                self.vel[0] *= m['vmax_xy'] / sp
                self.vel[1] *= m['vmax_xy'] / sp
            self.vel[2] = _clip(self.vel[2], m['vmax_z'])

        self.yaw_rate += (yaw_rate_d - self.yaw_rate) * min(1.0, dt / 0.1)
        if not self.on_ground or self.motors:
            self.yaw = _wrap_deg(self.yaw + self.yaw_rate * dt)

        # Tilt for logging/display (from horizontal acceleration)
        c, s = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
        a_fwd = ax * c + ay * s
        a_left = -ax * s + ay * c
        if self.motors and not self.on_ground:
            self.pitch = -math.degrees(math.atan2(a_fwd, G))   # nose down = negative
            self.roll = math.degrees(math.atan2(a_left, G))
        else:
            self.roll = self.pitch = 0.0

        for i in range(3):
            self.pos[i] += self.vel[i] * dt

        # Ground contact
        if self.pos[2] <= 0.0:
            if not self.on_ground and self.vel[2] < -HARD_LANDING_MS:
                self.crash(f'hard landing ({-self.vel[2]:.1f} m/s)')
            self.pos[2] = 0.0
            if self.vel[2] < 0:
                self.vel[2] = 0.0
            self.on_ground = True
            if not self.motors:
                self.vel[0] = self.vel[1] = 0.0
        elif self.pos[2] > 0.02:
            self.on_ground = False

        # Landing with the high-level commander switches the motors off
        if (self.mode == 'hl' and self.hl is None and self.hl_hold is not None
                and self.hl_hold[2] <= 0.06 and self.pos[2] < 0.06):
            self.motors = False
            self.mode = 'off'
            self.hl_hold = None

        self._estimator(dt)
        self._battery(dt)
        self._collisions()

        if not self.trail or math.dist(self.trail[-1], self.pos) > 0.03:
            self.trail.append(tuple(round(v, 3) for v in self.pos))
            if len(self.trail) > 1500:
                del self.trail[:300]

    def _controller(self, now):
        """Returns (desired world velocity, desired yaw rate, raw accel or None)."""
        m = self.m
        ex, ey, ez = self.est_pos()
        c, s = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
        kp_xy, kp_z, kp_yaw = 2.0, 2.5, 4.0

        def pos_ctrl(tx, ty, tz, tyaw, ff=(0.0, 0.0, 0.0)):
            vx = _clip(ff[0] + kp_xy * (tx - ex), m['vmax_xy'])
            vy = _clip(ff[1] + kp_xy * (ty - ey), m['vmax_xy'])
            vz = _clip(ff[2] + kp_z * (tz - ez), m['vmax_z'])
            yr = _clip(kp_yaw * _wrap_deg(tyaw - self.yaw), 200.0)
            return (vx, vy, vz), yr, None

        if self.mode == 'hl':
            if self.hl is not None:
                tx, ty, tz, tyaw = self.hl_target_now()
                ff = self.hl_velocity_now()
                if now - self.hl['t0'] >= self.hl['T']:
                    self.hl_hold = self.hl['to']
                    self.hl = None
                return pos_ctrl(tx, ty, tz, tyaw, ff)
            if self.hl_hold is not None:
                return pos_ctrl(*self.hl_hold)
            return (0.0, 0.0, 0.0), 0.0, None

        if self.mode == 'low' and self.low is not None:
            age = now - self.low_time
            if age > WDT_SHUTDOWN_S:
                self.say('no setpoint for 2 s - the commander watchdog switched the '
                         'motors off (send setpoints continuously, e.g. every 0.1 s).')
                self._motors_off()
                return (0.0, 0.0, 0.0), 0.0, None
            kind, v = self.low
            stale = age > WDT_STABILIZE_S
            if kind == 'hover':
                vx_b, vy_b, yr, z = v
                if stale:
                    vx_b = vy_b = yr = 0.0
                vx, vy = vx_b * c - vy_b * s, vx_b * s + vy_b * c
                vz = _clip(kp_z * (z - ez), m['vmax_z'])
                return (vx, vy, vz), yr, None
            if kind == 'velocity':
                vx, vy, vz, yr = v
                if stale:
                    vx = vy = vz = yr = 0.0
                return (vx, vy, vz), yr, None
            if kind == 'position':
                x, y, z, yaw = v
                return pos_ctrl(x, y, z, yaw)
            if kind == 'zdistance':
                roll, pitch, yr, z = v
                if stale:
                    roll = pitch = yr = 0.0
                a_fwd = G * math.tan(math.radians(_clip(pitch, 30)))
                a_left = -G * math.tan(math.radians(_clip(roll, 30)))
                vz = _clip(kp_z * (z - ez), m['vmax_z'])
                az = (vz - self.vel[2]) / m['tau']
                return None, yr, (a_fwd * c - a_left * s, a_fwd * s + a_left * c, az)
            if kind == 'attitude':
                roll, pitch, yr, thrust = v
                if stale:
                    roll = pitch = yr = 0.0
                if thrust <= 0:
                    self.motors = False
                    return (0.0, 0.0, 0.0), 0.0, (0.0, 0.0, -G)
                a_fwd = G * math.tan(math.radians(_clip(pitch, 30)))
                a_left = -G * math.tan(math.radians(_clip(roll, 30)))
                az = G * (thrust / m['hover_thrust'] - 1.0) - 0.5 * self.vel[2]
                drag = 0.3
                return None, yr, (a_fwd * c - a_left * s - drag * self.vel[0],
                                  a_fwd * s + a_left * c - drag * self.vel[1], az)
        return (0.0, 0.0, 0.0), 0.0, None

    def _estimator(self, dt):
        pos_mode = self.engine.positioning
        if not self.engine.noise or pos_mode == 'perfect':
            return
        speed = math.hypot(self.vel[0], self.vel[1])
        if pos_mode == 'flow':
            sigma = (0.01 if not self.on_ground else 0.0) + 0.04 * speed
        elif pos_mode == 'lighthouse':
            # Absolute positioning: small noise, no long-term drift
            self.est_err[0] += (-self.est_err[0]) * dt * 2 + random.gauss(0, 0.01) * math.sqrt(dt)
            self.est_err[1] += (-self.est_err[1]) * dt * 2 + random.gauss(0, 0.01) * math.sqrt(dt)
            return
        else:   # 'none': no positioning deck - the estimate drifts a lot
            sigma = 0.0 if self.on_ground else 0.35
        if 'flow' not in self.engine.decks and pos_mode == 'flow':
            sigma = 0.0 if self.on_ground else 0.35
        k = sigma * math.sqrt(dt)
        self.est_err[0] += random.gauss(0, k)
        self.est_err[1] += random.gauss(0, k)

    def _battery(self, dt):
        if self.motors and not self.on_ground:
            self.battery_used_s += dt * self.engine.battery_drain
        if not self.battery_empty and self.battery_used_s >= self.m['flight_time_s']:
            self.battery_empty = True
            self.say('battery EMPTY - motors stop.')
            self._motors_off('battery empty')

    def vbat(self):
        frac = min(1.0, self.battery_used_s / self.m['flight_time_s'])
        v = 4.15 - 1.1 * frac
        if self.motors and not self.on_ground:
            v -= 0.15     # voltage sag under load
        return v

    def _collisions(self):
        if self.crashed:
            return
        x, y, z = self.pos
        r = self.m['radius']
        w = self.engine.world
        if w.bounded and z > 0.01 and w.hits_wall(x, y, r):
            self.crash('flew into a wall')
        elif w.bounded and z > w.height - 0.05:
            self.crash('hit the ceiling')

    # ---------------------------------------------------------------- sensors
    def ranges(self):
        """Multi-ranger + Flow deck ranges in metres (None = out of range)."""
        now = self.engine.now()
        if self._ranges is not None and now - self._ranges_time < 0.03:
            return self._ranges
        x, y, z = self.pos
        w = self.engine.world
        others = [(d.pos[0], d.pos[1], d.m['radius'])
                  for d in self.engine.drones_list()
                  if d is not self and abs(d.pos[2] - z) < 0.15]
        out = {}
        for name, ang in (('front', 0), ('left', 90), ('back', 180), ('right', -90)):
            a = math.radians(self.yaw + ang)
            d = w.raycast(x, y, math.cos(a), math.sin(a), RANGE_MAX_M, others)
            out[name] = d
        up = (w.height - z) if w.bounded else None
        out['up'] = up if (up is not None and up < RANGE_MAX_M) else None
        out['zrange'] = z if z < RANGE_MAX_M else None
        if self.engine.noise:
            for k, v in out.items():
                if v is not None:
                    out[k] = max(0.0, v + random.gauss(0, 0.004 + 0.005 * v))
        self._ranges, self._ranges_time = out, now
        return out

    def rssi(self):
        bx, by = self.engine.world.beacon
        d = max(0.1, math.dist((bx, by, 0.0), self.pos))
        val = 42 + 22 * math.log10(d)
        if self.engine.noise:
            val += random.gauss(0, 2.0)
        return int(max(20, min(100, round(val))))

    def state_for_viewer(self):
        r = self.ranges() if 'multiranger' in self.engine.decks else None
        return {
            'id': self.uri, 'label': self.label, 'color': self.m['color'],
            'model': self.m['label'],
            'x': round(self.pos[0], 3), 'y': round(self.pos[1], 3),
            'z': round(self.pos[2], 3), 'yaw': round(self.yaw, 1),
            'roll': round(self.roll, 1), 'pitch': round(self.pitch, 1),
            'motors': self.motors, 'crashed': self.crashed,
            'vbat': round(self.vbat(), 2),
            'ranges': None if r is None else {k: (None if v is None else round(v, 3))
                                              for k, v in r.items()},
        }
