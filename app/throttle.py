"""Ograniczanie prób logowania — ochrona przed zgadywaniem haseł przy publicznym adresie."""

import time
from collections import deque

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def client_ip(peer, forwarded_for=None):
    """Adres klienta. Nagłówek X-Forwarded-For ufamy tylko, gdy połączenie przyszło z lokalnego proxy
    (tunel na tym samym komputerze); bierzemy ostatni wpis, czyli ten dopisany przez najbliższe proxy."""
    peer = (peer or "unknown").strip()
    if peer in LOOPBACK and forwarded_for:
        parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        if parts:
            return parts[-1]
    return peer


class LoginThrottle:
    def __init__(self, max_failures=8, window_seconds=600, clock=time.monotonic, max_keys=10000):
        self.max_failures = max_failures
        self.window = window_seconds
        self.clock = clock
        self.max_keys = max_keys
        self._failures = {}

    def _recent(self, key):
        queue = self._failures.get(key)
        if not queue:
            return None
        cutoff = self.clock() - self.window
        while queue and queue[0] <= cutoff:
            queue.popleft()
        if not queue:
            del self._failures[key]
            return None
        return queue

    def retry_after(self, key):
        """Ile sekund trzeba jeszcze czekać (0 = można próbować)."""
        queue = self._recent(key)
        if queue and len(queue) >= self.max_failures:
            return max(1, int(queue[0] + self.window - self.clock()) + 1)
        return 0

    def failure(self, key):
        if len(self._failures) >= self.max_keys and key not in self._failures:
            oldest = min(self._failures, key=lambda item: self._failures[item][-1])
            del self._failures[oldest]
        self._failures.setdefault(key, deque()).append(self.clock())

    def success(self, key):
        self._failures.pop(key, None)
