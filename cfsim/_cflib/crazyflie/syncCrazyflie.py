"""Simulated cflib.crazyflie.syncCrazyflie."""
import threading

from . import Crazyflie


class SyncCrazyflie:
    def __init__(self, link_uri, cf=None):
        self._link_uri = link_uri
        self.cf = cf if cf is not None else Crazyflie()
        self._connect_event = threading.Event()
        self._params_event = threading.Event()
        self._is_link_open = False

    def open_link(self):
        if self.is_link_open():
            raise Exception('Link already open')
        self._connect_event.clear()
        self._params_event.clear()
        self.cf.fully_connected.add_callback(self._fully)
        self.cf.open_link(self._link_uri)
        if not self._connect_event.wait(timeout=10):
            raise Exception(f'Failed to connect to {self._link_uri} (simulator)')
        self._is_link_open = True

    def _fully(self, uri):
        self._connect_event.set()
        self._params_event.set()

    def wait_for_params(self):
        self._params_event.wait()

    def __enter__(self):
        self.open_link()
        return self

    def close_link(self):
        self.cf.close_link()
        self.cf.fully_connected.remove_callback(self._fully)
        self._is_link_open = False

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_link()

    def is_link_open(self):
        return self._is_link_open

    def is_params_updated(self):
        return self._params_event.is_set()
