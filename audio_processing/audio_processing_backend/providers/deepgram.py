import asyncio
import os
import threading
from deepgram import DeepgramClient
from deepgram.listen.v1.socket_client import EventType
from .base import STTProvider


class DeepgramProvider(STTProvider):
    def __init__(self, api_key: str = None):
        key = api_key or os.getenv("DEEPGRAM_API_KEY")
        # v7.3.1: api_key must be a keyword argument
        self.deepgram = DeepgramClient(api_key=key)

    async def process_audio_stream(
        self,
        audio_queue: asyncio.Queue,
        handler_callback
    ):
        loop = asyncio.get_running_loop()

        try:
            with self.deepgram.listen.v1.connect(
                model="nova-3",
                smart_format=True,   # Maximum formatting/punctuation accuracy
                diarize=True,        # Enable speaker diarization
                encoding="linear16", # Tells Deepgram we stream raw PCM
                sample_rate=16000,
                channels=1,
                interim_results=True,
                endpointing=250,
                language="en",
                keyterm=["LangChain", "LangGraph", "land graph", "Landra", "MilvusDB", "BM25", "Agentic AI", "Agentic", "RAG", "Prometheus", "Grafana", "CloudWatch"]
            ) as connection:

                def on_message(*args, **kwargs):
                    message = args[1] if len(args) > 1 else args[0]
                    try:
                        if hasattr(message, "channel") and hasattr(message.channel, "alternatives"):
                            alt = message.channel.alternatives[0]
                            sentence = getattr(alt, "transcript", "")
                            if sentence and sentence.strip():
                                is_final = getattr(message, "is_final", False)
                                confidence = getattr(alt, "confidence", None)
                                speaker_id = None
                                
                                words = getattr(alt, "words", None) or []
                                speakers = []
                                for w in words:
                                    spk = getattr(w, "speaker", None)
                                    if spk is not None:
                                        speakers.append(spk)
                                    elif isinstance(w, dict) and w.get("speaker") is not None:
                                        speakers.append(w.get("speaker"))
                                
                                if speakers:
                                    speaker_id = max(set(speakers), key=speakers.count)
                                else:
                                    for obj in (message, alt, getattr(message, "channel", None)):
                                        spk = getattr(obj, "speaker", None)
                                        if spk is not None:
                                            speaker_id = spk
                                            break

                                kind_str = "FINAL" if is_final else "PARTIAL"
                                spk_str = f"speaker={speaker_id}" if speaker_id is not None else "speaker=unknown"
                                print(f"[DEEPGRAM][{kind_str}][{spk_str}]\n{sentence}", flush=True)

                                asyncio.run_coroutine_threadsafe(
                                    handler_callback(sentence, is_final, speaker_id, confidence), loop
                                )
                    except Exception as e:
                        print(f"Deepgram message parse error: {e}")

                def on_error(*args, **kwargs):
                    error = args[1] if len(args) > 1 else args[0]
                    print(f"Deepgram Error: {error}")

                connection.on(EventType.MESSAGE, on_message)
                connection.on(EventType.ERROR, on_error)

                # start_listening() is blocking — run in a thread
                listen_thread = threading.Thread(
                    target=connection.start_listening, daemon=True
                )
                listen_thread.start()

                # Send initial keepalive immediately to prevent early timeout
                try:
                    connection.send_keep_alive()
                except Exception as e:
                    print(f"Failed to send initial keepalive: {e}", flush=True)

                # Stream audio chunks to Deepgram
                while True:
                    try:
                        try:
                            chunk = await asyncio.wait_for(audio_queue.get(), timeout=2.0)
                        except asyncio.TimeoutError:
                            # Send KeepAlive to prevent Deepgram timeout
                            try:
                                connection.send_keep_alive()
                            except Exception:
                                pass
                            continue

                        if chunk is None:  # EOF / sender disconnected
                            break

                        connection.send_media(chunk)

                    except Exception as e:
                        print(f"Error sending audio to Deepgram: {e}", flush=True)
                        break

                listen_thread.join(timeout=3.0)
                print("Deepgram streaming finished.")

        except Exception as e:
            print(f"Could not open Deepgram socket: {e}")
