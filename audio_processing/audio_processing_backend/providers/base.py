from abc import ABC, abstractmethod
import asyncio
from typing import Callable, Awaitable

class STTProvider(ABC):
    @abstractmethod
    async def process_audio_stream(
        self, 
        audio_queue: asyncio.Queue, 
        handler_callback: Callable[[str], Awaitable[None]]
    ) -> None:
        """
        Process the audio queue and call handler_callback with raw transcribed text.
        """
        pass
