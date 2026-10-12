"""Bounded buffers used on real-time audio paths."""

from __future__ import annotations

from collections import deque
from threading import Lock

import numpy as np


class AudioRingBuffer:
    def __init__(self, capacity_samples: int):
        if capacity_samples <= 0:
            raise ValueError("capacity_samples must be positive")
        self._capacity = capacity_samples
        self._chunks: deque[np.ndarray] = deque()
        self._samples = 0
        self._lock = Lock()

    def append(self, chunk: np.ndarray) -> None:
        value = np.asarray(chunk, dtype=np.float32).reshape(-1).copy()
        with self._lock:
            self._chunks.append(value)
            self._samples += value.size
            while self._samples > self._capacity and self._chunks:
                excess = self._samples - self._capacity
                first = self._chunks[0]
                if first.size <= excess:
                    self._chunks.popleft()
                    self._samples -= first.size
                else:
                    self._chunks[0] = first[excess:].copy()
                    self._samples -= excess

    def tail(self, samples: int) -> np.ndarray:
        if samples <= 0:
            return np.empty(0, dtype=np.float32)
        with self._lock:
            if not self._chunks:
                return np.empty(0, dtype=np.float32)
            merged = np.concatenate(tuple(self._chunks))
        return merged[-samples:].copy()

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._samples = 0

    def __len__(self) -> int:
        with self._lock:
            return self._samples
