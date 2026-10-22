"""Deepgram Listen v1 streaming provider adapter."""

import asyncio
import os
import threading

from deepgram import DeepgramClient
try:
    from deepgram.core.events import EventType
except ImportError:  # Compatibility with older SDK releases.
    from deepgram.listen.v1.socket_client import EventType

from .base import STTProvider


class DeepgramProvider(STTProvider):
    def __init__(self, api_key: str = None):
        key = api_key or os.getenv("DEEPGRAM_API_KEY")
        self.deepgram = DeepgramClient(api_key=key)

    async def process_audio_stream(self, audio_queue: asyncio.Queue, handler_callback):
        loop = asyncio.get_running_loop()
        try:
            with self.deepgram.listen.v1.connect(
                model="nova-3", smart_format=True, diarize=True,
                encoding="linear16", sample_rate=16000, channels=1,
                interim_results=True, endpointing=650, language="en",
                keyterm=["LangChain", "LangGraph", "land graph", "Landra", "MilvusDB",
                         "BM25", "Agentic AI", "Agentic", "RAG", "Prometheus", "Grafana", "CloudWatch"],
            ) as connection:
                def on_message(*args, **kwargs):
                    del kwargs
                    message = args[1] if len(args) > 1 else args[0]
                    try:
                        channel = getattr(message, "channel", None)
                        alternatives = getattr(channel, "alternatives", None)
                        if not alternatives:
                            return
                        alt = alternatives[0]
                        sentence = (getattr(alt, "transcript", "") or "").strip()
                        if not sentence:
                            return
                        segment_final = bool(getattr(message, "is_final", False))
                        speech_final = bool(getattr(message, "speech_final", False))
                        confidence = getattr(alt, "confidence", None)
                        speakers = []
                        for word in (getattr(alt, "words", None) or []):
                            speaker = getattr(word, "speaker", None)
                            if speaker is None and isinstance(word, dict):
                                speaker = word.get("speaker")
                            if speaker is not None:
                                speakers.append(speaker)
                        speaker_id = max(set(speakers), key=speakers.count) if speakers else None
                        kind = "FINAL" if segment_final else "PARTIAL"
                        print(f"[DEEPGRAM][{kind}][speech_final={speech_final}] {sentence}", flush=True)
                        asyncio.run_coroutine_threadsafe(
                            handler_callback(sentence, segment_final, speaker_id, confidence, speech_final), loop
                        )
                    except Exception as exc:
                        print(f"Deepgram message parse error: {exc}", flush=True)

                def on_error(*args, **kwargs):
                    error = args[1] if len(args) > 1 else args[0]
                    print(f"Deepgram Error: {error}", flush=True)

                connection.on(EventType.MESSAGE, on_message)
                connection.on(EventType.ERROR, on_error)
                listen_thread = threading.Thread(target=connection.start_listening, daemon=True)
                listen_thread.start()
                try:
                    connection.send_keep_alive()
                except Exception as exc:
                    print(f"Failed to send initial keepalive: {exc}", flush=True)
                while True:
                    try:
                        try:
                            chunk = await asyncio.wait_for(audio_queue.get(), timeout=2.0)
                        except asyncio.TimeoutError:
                            try:
                                connection.send_keep_alive()
                            except Exception:
                                pass
                            continue
                        if chunk is None:
                            break
                        connection.send_media(chunk)
                    except Exception as exc:
                        print(f"Error sending audio to Deepgram: {exc}", flush=True)
                        break
                listen_thread.join(timeout=3.0)
                print("Deepgram streaming finished.", flush=True)
        except Exception as exc:
            print(f"Could not open Deepgram socket: {exc}", flush=True)
            raise
