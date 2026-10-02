"""Simulated cflib.crazyflie.swarm."""
import time
from collections import namedtuple
from threading import Thread

from . import Crazyflie
from .log import LogConfig
from .syncCrazyflie import SyncCrazyflie
from .syncLogger import SyncLogger

SwarmPosition = namedtuple('SwarmPosition', 'x y z')


class _Factory:
    def construct(self, uri):
        return SyncCrazyflie(uri)


class CachedCfFactory:
    def __init__(self, ro_cache=None, rw_cache=None):
        self.ro_cache = ro_cache
        self.rw_cache = rw_cache

    def construct(self, uri):
        return SyncCrazyflie(uri, cf=Crazyflie(ro_cache=self.ro_cache, rw_cache=self.rw_cache))


class Swarm:
    def __init__(self, uris, factory=_Factory()):
        from cfsim.engine import get_engine
        eng = get_engine()
        for uri in uris:                 # place drones in the order given
            eng.get_drone(uri)
        self._cfs = {uri: factory.construct(uri) for uri in uris}
        self._is_open = False
        self._positions = dict()

    def open_links(self):
        if self._is_open:
            raise Exception('Already opened')
        try:
            self.parallel_safe(lambda scf: scf.open_link())
            self._is_open = True
        except Exception as e:
            self.close_links()
            raise e

    def close_links(self):
        for uri, cf in self._cfs.items():
            cf.close_link()
        self._is_open = False

    def __enter__(self):
        self.open_links()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_links()

    def get_estimated_positions(self):
        self.parallel_safe(self.__get_estimated_position)
        return self._positions

    def __get_estimated_position(self, scf):
        lc = LogConfig(name='stateEstimate', period_in_ms=10)
        for v in ('x', 'y', 'z'):
            lc.add_variable('stateEstimate.' + v, 'float')
        with SyncLogger(scf, lc) as logger:
            for entry in logger:
                d = entry[1]
                self._positions[scf.cf.link_uri] = SwarmPosition(
                    d['stateEstimate.x'], d['stateEstimate.y'], d['stateEstimate.z'])
                break

    def reset_estimators(self):
        def reset(scf):
            scf.cf.param.set_value('kalman.resetEstimation', '1')
            time.sleep(0.1)
            scf.cf.param.set_value('kalman.resetEstimation', '0')
        self.parallel_safe(reset)

    def sequential(self, func, args_dict=None):
        for uri, cf in self._cfs.items():
            func(*self._process_args_dict(cf, uri, args_dict))

    def parallel(self, func, args_dict=None):
        try:
            self.parallel_safe(func, args_dict)
        except Exception:
            pass

    def parallel_safe(self, func, args_dict=None):
        threads = []
        errors = []

        def run(*args):
            try:
                func(*args)
            except Exception as e:
                errors.append(e)

        for uri, scf in self._cfs.items():
            t = Thread(target=run, args=self._process_args_dict(scf, uri, args_dict), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        if errors:
            raise Exception('One or more threads raised an exception when executing '
                            'parallel task') from errors[0]

    def _process_args_dict(self, scf, uri, args_dict):
        args = [scf]
        if args_dict:
            args += args_dict[uri]
        return args
