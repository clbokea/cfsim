"""Simulated cflib.positioning.motion_commander - same behaviour as the real
one: a background thread sends hover setpoints every 0.1 s."""
import math
import time
from queue import Empty, Queue
from threading import Thread

from cflib.crazyflie.syncCrazyflie import SyncCrazyflie


class MotionCommander:
    VELOCITY = 0.2
    RATE = 360.0 / 5

    def __init__(self, crazyflie, default_height=0.3):
        self._cf = crazyflie.cf if isinstance(crazyflie, SyncCrazyflie) else crazyflie
        self.default_height = default_height
        self._is_flying = False
        self._thread = None

    # Distance based primitives
    def take_off(self, height=None, velocity=VELOCITY):
        if self._is_flying:
            raise Exception('Already flying')
        if not self._cf.is_connected():
            raise Exception('Crazyflie is not connected')
        self._is_flying = True
        self._reset_position_estimator()
        self._thread = _SetPointThread(self._cf)
        self._thread.start()
        if height is None:
            height = self.default_height
        self.up(height, velocity)

    def land(self, velocity=VELOCITY):
        if self._is_flying:
            self.down(self._thread.get_height(), velocity)
            self._thread.stop()
            self._thread = None
            self._cf.commander.send_stop_setpoint()
            self._cf.commander.send_notify_setpoint_stop()
            self._is_flying = False

    def __enter__(self):
        self.take_off()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.land()

    def left(self, distance_m, velocity=VELOCITY):
        self.move_distance(0.0, distance_m, 0.0, velocity)

    def right(self, distance_m, velocity=VELOCITY):
        self.move_distance(0.0, -distance_m, 0.0, velocity)

    def forward(self, distance_m, velocity=VELOCITY):
        self.move_distance(distance_m, 0.0, 0.0, velocity)

    def back(self, distance_m, velocity=VELOCITY):
        self.move_distance(-distance_m, 0.0, 0.0, velocity)

    def up(self, distance_m, velocity=VELOCITY):
        self.move_distance(0.0, 0.0, distance_m, velocity)

    def down(self, distance_m, velocity=VELOCITY):
        self.move_distance(0.0, 0.0, -distance_m, velocity)

    def turn_left(self, angle_degrees, rate=RATE):
        flight_time = angle_degrees / rate
        self.start_turn_left(rate)
        time.sleep(flight_time)
        self.stop()

    def turn_right(self, angle_degrees, rate=RATE):
        flight_time = angle_degrees / rate
        self.start_turn_right(rate)
        time.sleep(flight_time)
        self.stop()

    def circle_left(self, radius_m, velocity=VELOCITY, angle_degrees=360.0):
        distance = 2 * radius_m * math.pi * angle_degrees / 360.0
        flight_time = distance / velocity
        self.start_circle_left(radius_m, velocity)
        time.sleep(flight_time)
        self.stop()

    def circle_right(self, radius_m, velocity=VELOCITY, angle_degrees=360.0):
        distance = 2 * radius_m * math.pi * angle_degrees / 360.0
        flight_time = distance / velocity
        self.start_circle_right(radius_m, velocity)
        time.sleep(flight_time)
        self.stop()

    def move_distance(self, distance_x_m, distance_y_m, distance_z_m, velocity=VELOCITY):
        distance = math.sqrt(distance_x_m ** 2 + distance_y_m ** 2 + distance_z_m ** 2)
        if distance == 0:
            return
        flight_time = distance / velocity
        self.start_linear_motion(velocity * distance_x_m / distance,
                                 velocity * distance_y_m / distance,
                                 velocity * distance_z_m / distance)
        time.sleep(flight_time)
        self.stop()

    # Velocity based primitives
    def start_left(self, velocity=VELOCITY):
        self.start_linear_motion(0.0, velocity, 0.0)

    def start_right(self, velocity=VELOCITY):
        self.start_linear_motion(0.0, -velocity, 0.0)

    def start_forward(self, velocity=VELOCITY):
        self.start_linear_motion(velocity, 0.0, 0.0)

    def start_back(self, velocity=VELOCITY):
        self.start_linear_motion(-velocity, 0.0, 0.0)

    def start_up(self, velocity=VELOCITY):
        self.start_linear_motion(0.0, 0.0, velocity)

    def start_down(self, velocity=VELOCITY):
        self.start_linear_motion(0.0, 0.0, -velocity)

    def stop(self):
        self._set_vel_setpoint(0.0, 0.0, 0.0, 0.0)

    def start_turn_left(self, rate=RATE):
        self._set_vel_setpoint(0.0, 0.0, 0.0, rate)

    def start_turn_right(self, rate=RATE):
        self._set_vel_setpoint(0.0, 0.0, 0.0, -rate)

    def start_circle_left(self, radius_m, velocity=VELOCITY):
        rate = 360.0 * velocity / (2 * radius_m * math.pi)
        self._set_vel_setpoint(velocity, 0.0, 0.0, rate)

    def start_circle_right(self, radius_m, velocity=VELOCITY):
        rate = 360.0 * velocity / (2 * radius_m * math.pi)
        self._set_vel_setpoint(velocity, 0.0, 0.0, -rate)

    def start_linear_motion(self, velocity_x_m, velocity_y_m, velocity_z_m, rate_yaw=0.0):
        self._set_vel_setpoint(velocity_x_m, velocity_y_m, velocity_z_m, rate_yaw)

    def _set_vel_setpoint(self, velocity_x, velocity_y, velocity_z, rate_yaw):
        if not self._is_flying:
            raise Exception('Can not move on the ground. Take off first!')
        self._thread.set_vel_setpoint(velocity_x, velocity_y, velocity_z, rate_yaw)

    def _reset_position_estimator(self):
        self._cf.param.set_value('kalman.resetEstimation', '1')
        time.sleep(0.1)
        self._cf.param.set_value('kalman.resetEstimation', '0')
        time.sleep(0.5)


class _SetPointThread(Thread):
    TERMINATE_EVENT = 'terminate'
    UPDATE_PERIOD = 0.2
    ABS_Z_INDEX = 3

    def __init__(self, cf, update_period=UPDATE_PERIOD):
        Thread.__init__(self, daemon=True)
        self.update_period = update_period
        self._queue = Queue()
        self._cf = cf
        self._hover_setpoint = [0.0, 0.0, 0.0, 0.0]
        self._z_base = 0.0
        self._z_velocity = 0.0
        self._z_base_time = 0.0

    def stop(self):
        self._queue.put(self.TERMINATE_EVENT)
        self.join()

    def set_vel_setpoint(self, velocity_x, velocity_y, velocity_z, rate_yaw):
        self._queue.put((velocity_x, velocity_y, velocity_z, rate_yaw))

    def get_height(self):
        return self._hover_setpoint[self.ABS_Z_INDEX]

    def run(self):
        while True:
            try:
                event = self._queue.get(block=True, timeout=self.update_period)
                if event == self.TERMINATE_EVENT:
                    return
                self._new_setpoint(*event)
            except Empty:
                pass
            self._update_z_in_setpoint()
            if self._cf.is_connected():
                self._cf.commander.send_hover_setpoint(*self._hover_setpoint)

    def _new_setpoint(self, velocity_x, velocity_y, velocity_z, rate_yaw):
        self._z_base = self._current_z()
        self._z_velocity = velocity_z
        self._z_base_time = time.time()
        self._hover_setpoint = [velocity_x, velocity_y, rate_yaw, self._z_base]

    def _update_z_in_setpoint(self):
        self._hover_setpoint[self.ABS_Z_INDEX] = self._current_z()

    def _current_z(self):
        now = time.time()
        return self._z_base + self._z_velocity * (now - self._z_base_time)
