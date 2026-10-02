"""Simulated cflib.crazyflie.syncLogger."""
from queue import Empty, Queue

from .syncCrazyflie import SyncCrazyflie


class SyncLogger:
    DISCONNECT_EVENT = 'DISCONNECT_EVENT'

    def __init__(self, crazyflie, log_config):
        self._cf = crazyflie.cf if isinstance(crazyflie, SyncCrazyflie) else crazyflie
        self._log_config = log_config if isinstance(log_config, list) else [log_config]
        self._queue = Queue()
        self._is_connected = False

    def connect(self):
        if self._is_connected:
            raise Exception('Already connected')
        self._cf.disconnected.add_callback(self._disconnected)
        for lc in self._log_config:
            self._cf.log.add_config(lc)
            lc.data_received_cb.add_callback(self._log_callback)
            lc.start()
        self._is_connected = True

    def disconnect(self):
        if self._is_connected:
            for lc in self._log_config:
                lc.stop()
                lc.delete()
                lc.data_received_cb.remove_callback(self._log_callback)
            self._cf.disconnected.remove_callback(self._disconnected)
            self._queue.empty()
            self._is_connected = False

    def is_connected(self):
        return self._is_connected

    def __iter__(self):
        return self

    def __next__(self):
        if not self._is_connected:
            raise StopIteration
        data = self._queue.get()
        if data == self.DISCONNECT_EVENT:
            raise StopIteration
        return data

    next = __next__

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def _log_callback(self, ts, data, logblock):
        self._queue.put((ts, data, logblock))

    def _disconnected(self, link_uri):
        self._queue.put(self.DISCONNECT_EVENT)
        self.disconnect()
