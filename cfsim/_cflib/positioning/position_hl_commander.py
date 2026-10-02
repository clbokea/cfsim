"""Simulated cflib.positioning.position_hl_commander (absolute positions via
the high-level commander)."""
import math
import time

from cflib.crazyflie.syncCrazyflie import SyncCrazyflie


class PositionHlCommander:
    CONTROLLER_PID = 1
    CONTROLLER_MELLINGER = 2
    CONTROLLER_INDI = 3
    CONTROLLER_BRESCIANINI = 4
    DEFAULT = None

    def __init__(self, crazyflie, x=0.0, y=0.0, z=0.0, default_velocity=0.5,
                 default_height=0.5, controller=None, default_landing_height=0.0):
        self._cf = crazyflie.cf if isinstance(crazyflie, SyncCrazyflie) else crazyflie
        self._default_velocity = default_velocity
        self._default_height = default_height
        self._controller = controller
        self._hl_commander = self._cf.high_level_commander
        self._x, self._y, self._z = x, y, z
        self._is_flying = False
        self._init_time = time.time()
        self._default_landing_height = default_landing_height

    def take_off(self, height=DEFAULT, velocity=DEFAULT):
        if self._is_flying:
            raise Exception('Already flying')
        if not self._cf.is_connected():
            raise Exception('Crazyflie is not connected')
        hold_back = self._init_time + 1.0 - time.time()
        if hold_back > 0.0:
            time.sleep(hold_back)
        self._is_flying = True
        height = self._height(height)
        duration_s = height / self._velocity(velocity)
        self._hl_commander.takeoff(height, duration_s)
        time.sleep(duration_s)
        self._z = height

    def land(self, velocity=DEFAULT, landing_height=DEFAULT):
        if self._is_flying:
            landing_height = self._landing_height(landing_height)
            duration_s = (self._z - landing_height) / self._velocity(velocity)
            self._hl_commander.land(landing_height, duration_s)
            time.sleep(duration_s)
            self._z = landing_height
            self._hl_commander.stop()
            self._is_flying = False

    def __enter__(self):
        self.take_off()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.land()

    def left(self, distance_m, velocity=DEFAULT):
        self.move_distance(0.0, distance_m, 0.0, velocity)

    def right(self, distance_m, velocity=DEFAULT):
        self.move_distance(0.0, -distance_m, 0.0, velocity)

    def forward(self, distance_m, velocity=DEFAULT):
        self.move_distance(distance_m, 0.0, 0.0, velocity)

    def back(self, distance_m, velocity=DEFAULT):
        self.move_distance(-distance_m, 0.0, 0.0, velocity)

    def up(self, distance_m, velocity=DEFAULT):
        self.move_distance(0.0, 0.0, distance_m, velocity)

    def down(self, distance_m, velocity=DEFAULT):
        self.move_distance(0.0, 0.0, -distance_m, velocity)

    def move_distance(self, distance_x_m, distance_y_m, distance_z_m, velocity=DEFAULT):
        self.go_to(self._x + distance_x_m, self._y + distance_y_m,
                   self._z + distance_z_m, velocity)

    def go_to(self, x, y, z=DEFAULT, velocity=DEFAULT):
        z = self._height(z)
        dx, dy, dz = x - self._x, y - self._y, z - self._z
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        if distance > 0.0:
            duration_s = distance / self._velocity(velocity)
            self._hl_commander.go_to(x, y, z, 0, duration_s)
            time.sleep(duration_s)
            self._x, self._y, self._z = x, y, z

    def set_default_velocity(self, velocity):
        self._default_velocity = velocity

    def set_default_height(self, height):
        self._default_height = height

    def set_landing_height(self, landing_height):
        self._default_landing_height = landing_height

    def get_position(self):
        return self._x, self._y, self._z

    def _velocity(self, velocity):
        return self._default_velocity if velocity is self.DEFAULT else velocity

    def _height(self, height):
        return self._default_height if height is self.DEFAULT else height

    def _landing_height(self, landing_height):
        return self._default_landing_height if landing_height is self.DEFAULT else landing_height
