import threading
import time
from utils.logger import get_logger

_logger = get_logger(__name__)


class LivePollManager:
    """
    Background polling manager for PSU live readback.

    - Polls devices in a background thread
    - Stores latest readings in a cache
    - Never touches Tkinter widgets directly
    """

    def __init__(self, registry_getter, channels_getter):
        """
        registry_getter: callable returning current driver registry dict
        channels_getter: callable returning current channel config dict
        """
        self._registry_getter = registry_getter
        self._channels_getter = channels_getter

        self._thread = None
        self._stop_event = threading.Event()
        self._running = False

        self._cache = {}
        self._cache_lock = threading.Lock()

    def is_running(self) -> bool:
        return self._running

    def get_cache_snapshot(self) -> dict:
        with self._cache_lock:
            return dict(self._cache)

    def clear_cache(self):
        with self._cache_lock:
            self._cache.clear()

    def ensure_channel(self, ch_id: str):
        with self._cache_lock:
            self._cache.setdefault(
                ch_id,
                {
                    "meas_v": "---",
                    "meas_a": "---",
                    "error": "",
                    "timestamp": 0.0,
                },
            )

    def remove_missing_channels(self, valid_ids):
        valid_ids = set(valid_ids)
        with self._cache_lock:
            for key in list(self._cache.keys()):
                if key not in valid_ids:
                    self._cache.pop(key, None)

    def start(self, interval_ms: int):
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval_ms,),
            daemon=True,
        )
        self._thread.start()
        _logger.info(f"LivePollManager started @ {interval_ms} ms")

    def stop(self):
        self._running = False
        self._stop_event.set()
        _logger.info("LivePollManager stop requested")

    def poll_once(self):
        channels = self._channels_getter() or {}
        for ch_id in list(channels.keys()):
            self.ensure_channel(ch_id)
            self._poll_one_channel(ch_id)

    def _run_loop(self, interval_ms: int):
        stagger_s = 0.03

        while not self._stop_event.is_set():
            cycle_start = time.time()

            channels = self._channels_getter() or {}
            channel_ids = list(channels.keys())

            self.remove_missing_channels(channel_ids)

            for ch_id in channel_ids:
                if self._stop_event.is_set():
                    break
                self.ensure_channel(ch_id)
                self._poll_one_channel(ch_id)

                if self._stop_event.wait(stagger_s):
                    break

            elapsed_ms = int((time.time() - cycle_start) * 1000.0)
            remaining_ms = max(50, interval_ms - elapsed_ms)
            self._stop_event.wait(remaining_ms / 1000.0)

        self._running = False
        _logger.info("LivePollManager stopped")

    def _poll_one_channel(self, ch_id: str):
        channels = self._channels_getter() or {}
        info = channels.get(ch_id)
        if not info:
            return

        registry = self._registry_getter() or {}
        drv = registry.get(info["supply"])

        if drv is None:
            self._update_cache(
                ch_id,
                meas_v="---",
                meas_a="---",
                error="not connected",
            )
            return

        meas_v = "---"
        meas_a = "---"
        err = ""

        try:
            v = drv.measure_voltage(info["channel"])
            meas_v = f"{float(v):.4f}"
        except Exception as e:
            meas_v = "ERR"
            err = f"V: {e}"
            _logger.warning(f"Voltage readback failed {ch_id}: {e}")

        try:
            a = drv.measure_current(info["channel"])
            meas_a = f"{float(a):.4f}"
        except Exception as e:
            meas_a = "ERR"
            err = f"{err} | I: {e}" if err else f"I: {e}"
            _logger.warning(f"Current readback failed {ch_id}: {e}")

        self._update_cache(
            ch_id,
            meas_v=meas_v,
            meas_a=meas_a,
            error=err,
        )

    def _update_cache(self, ch_id: str, meas_v: str, meas_a: str, error: str):
        with self._cache_lock:
            self._cache[ch_id] = {
                "meas_v": meas_v,
                "meas_a": meas_a,
                "error": error,
                "timestamp": time.time(),
            }