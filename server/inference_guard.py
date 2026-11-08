"""One memory-intensive local model operation per gateway process."""
import threading

class InferenceLock:
    def __init__(self):
        self._lock = threading.Lock()
        self._poisoned = False

    def acquire(self, blocking=True, timeout=-1):
        if self._poisoned:
            return False
        acquired = self._lock.acquire(blocking, timeout)
        if acquired and self._poisoned:
            self._lock.release()
            return False
        return acquired

    def release(self):
        self._lock.release()

    def poison(self):
        self._poisoned = True

    def poisoned(self):
        return self._poisoned

    def locked(self):
        return self._lock.locked()

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError('Inference requires supervised restart')
        return self

    def __exit__(self, *args):
        self.release()


local_inference_lock = InferenceLock()
