import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
import uvicorn
from dotenv import load_dotenv

from audio_processing_backend.utils import is_valid_webm, safe_send
from audio_processing_backend.services import llm_cleaning
from audio_processing_backend.providers import get_stt_provider
import os

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://192.168.0.205:3001",
        "http://192.168.0.205:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STT_PROVIDER = os.getenv("STT_PROVIDER", "openai").lower()

# Manage session broadcasts
class ConnectionManager:
    def __init__(self):
        self.active_listeners: dict[str, list[WebSocket]] = {}

    async def connect_listener(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_listeners:
            self.active_listeners[session_id] = []
        self.active_listeners[session_id].append(websocket)
        print(f"📡 Listener joined session: {session_id}")

    def disconnect_listener(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_listeners:
            if websocket in self.active_listeners[session_id]:
                self.active_listeners[session_id].remove(websocket)
            if not self.active_listeners[session_id]:
                del self.active_listeners[session_id]
        print(f"🔌 Listener left session: {session_id}")

    async def broadcast_to_session(self, session_id: str, message: dict):
        if session_id in self.active_listeners:
            dead_sockets = []
            for connection in self.active_listeners[session_id]:
                try:
                    await safe_send(connection, message)
                except Exception:
                    dead_sockets.append(connection)
            for dead in dead_sockets:
                self.disconnect_listener(dead, session_id)

manager = ConnectionManager()


@app.websocket("/ws/listen/{session_id}")
async def websocket_listen(websocket: WebSocket, session_id: str):
    await manager.connect_listener(websocket, session_id)
    try:
        while True:
            # Keep the connection alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_listener(websocket, session_id)
    except Exception as e:
        print(f"Listener error: {e}")
        manager.disconnect_listener(websocket, session_id)


@app.websocket("/ws/stt/{session_id}")
async def websocket_stt(
    websocket: WebSocket,
    session_id: str,
    provider: str = None,
    openai_key: str = None,
    deepgram_key: str = None,
):
    await websocket.accept()

    audio_queue = asyncio.Queue()
    is_connected = True
    
    # Store ORIGINAL transcripts for context, not cleaned versions
    raw_transcript_history = ""
    
    async def receive_audio():
        nonlocal is_connected
        try:
            while True:
                data = await websocket.receive_bytes()
                await audio_queue.put(data)
        except WebSocketDisconnect:
            print(f"🔌 Sender disconnected from session {session_id}")
        except Exception as e:
            print(f"  Receive error: {e}")
        finally:
            is_connected = False
            await audio_queue.put(None)

    active_provider = provider or os.getenv("STT_PROVIDER", "openai").lower()
    stt_provider_instance = get_stt_provider(
        active_provider,
        openai_key=openai_key,
        deepgram_key=deepgram_key,
    )

    async def handler_callback(raw_text: str):
        nonlocal raw_transcript_history
        if not raw_text:
            return

        print(f"  Raw transcript [{session_id}]: {raw_text}")

        # Update context with RAW transcript, not cleaned
        raw_transcript_history = (raw_transcript_history + " " + raw_text)[-2000:]

        import uuid
        segment_id = str(uuid.uuid4())

        msg_raw = {
            "type": "transcript_raw",
            "id": segment_id,
            "text": raw_text
        }

        # Send raw text to front-end sender
        await safe_send(websocket, msg_raw)

        # Broadcast to any active listeners
        await manager.broadcast_to_session(session_id, msg_raw)

        # Define background task for cleaning
        async def clean_and_send(text_to_clean: str, history: str, sid: str):
            try:
                cleaned_val = await llm_cleaning(history, text_to_clean)
                print(f"  Cleaned transcript [{session_id}]: {cleaned_val}")
                if cleaned_val == "[SILENCE]":
                    cleaned_val = text_to_clean
                
                # Post-processing to fix punctuation artifacts
                if cleaned_val and cleaned_val != "[SILENCE]":
                    cleaned_val = cleaned_val.replace(". and", ", and")
                    cleaned_val = cleaned_val.replace(". And", ", and")
                    cleaned_val = cleaned_val.replace(" .", ".")
                    cleaned_val = cleaned_val.replace(" ,", ",")
                
                msg_cleaned = {
                    "type": "transcript_cleaned",
                    "id": sid,
                    "text": cleaned_val
                }
                
                # Send to sender
                await safe_send(websocket, msg_cleaned)
                # Broadcast to listener
                await manager.broadcast_to_session(session_id, msg_cleaned)
            except Exception as e:
                print(f"  Error during LLM clean background task: {e}")

        # Kick off background cleaning task (does not block websocket)
        asyncio.create_task(clean_and_send(raw_text, raw_transcript_history, segment_id))

    async def run_provider():
        try:
            await stt_provider_instance.process_audio_stream(audio_queue, handler_callback)
        except Exception as e:
            print(f"  Provider error: {e}")

    # Create tasks for receiving and processing
    receive_task = asyncio.create_task(receive_audio())
    send_task = asyncio.create_task(run_provider())

    try:
        # Wait for either task to complete
        await asyncio.wait(
            [receive_task, send_task],
            return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        print(f"  Cleaning up WebSocket tasks for session {session_id}")

        # Cancel both tasks
        receive_task.cancel()
        send_task.cancel()

        # Wait for cancellation to complete
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  Receive task error during cleanup: {e}")

        try:
            await send_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  Send task error during cleanup: {e}")

        # Close WebSocket if still open
        try:
            if websocket.application_state != WebSocketState.DISCONNECTED and websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.close()
        except RuntimeError:
            pass
        except Exception as e:
            print(f"  Error during websocket close: {e}")

        print("  WebSocket safely closed")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
