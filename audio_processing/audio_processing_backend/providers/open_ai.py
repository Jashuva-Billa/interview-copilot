import io
import asyncio
import os
from openai import OpenAI
from audio_processing_backend.utils import is_hallucination, is_valid_webm, is_valid_audio
from .base import STTProvider

class OpenAIProvider(STTProvider):
    def __init__(self, api_key: str = None):
        key = api_key or os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=key)

    async def process_audio_stream(
        self,
        audio_queue: asyncio.Queue,
        handler_callback
    ):
        while True:
            try:
                # Wait for next audio chunk
                chunk = await audio_queue.get()

                if chunk is None:
                    break  # Disconnected

                # Skip tiny chunks (likely silence or noise)
                if len(chunk) < 500:
                    print(f"⏭️  Skipping small chunk: {len(chunk)} bytes")
                    continue

                if not is_valid_audio(chunk):
                    print(f"  Invalid audio chunk (missing EBML or RIFF header): {len(chunk)} bytes")
                    continue

                # Transcribe the audio
                raw_text = await self._transcribe_audio(chunk)
                if raw_text:
                    await handler_callback(raw_text)

            except Exception as e:
                print(f"  OpenAI provider error: {e}")

    async def _transcribe_audio(self, audio_data: bytes) -> str:
        try:
            print(f" Transcribing {len(audio_data)} bytes", flush=True)
            
            audio_file = io.BytesIO(audio_data)
            if audio_data[:4] == b'RIFF':
                audio_file.name = "audio.wav"
            else:
                audio_file.name = "audio.webm"

            # Run blocking API call in thread pool
            response = await asyncio.to_thread(
                self.client.audio.transcriptions.create,
                model="whisper-1",
                file=audio_file,
                response_format="text",
                language="en",
                prompt="LangChain, LangGraph, MilvusDB, BM25, Agentic AI, RAG, Prometheus, Grafana, AWS CloudWatch, Docker, Kubernetes.",
                timeout=10
            )

            text = response.strip() if isinstance(response, str) else response.text.strip()
            print(f"   OpenAI API response text: '{text}'", flush=True)

            if not text:
                print("   Empty transcription (likely silence)", flush=True)
                return None
            if not text or is_hallucination(text):
                print(f"   Skipping hallucination/silence: '{text}'", flush=True)
                return None
            return text

        except asyncio.TimeoutError:
            print("   Transcription timeout", flush=True)
            return None
        except Exception as e:
            print(f"  Transcription error: {e}", flush=True)
            return None
