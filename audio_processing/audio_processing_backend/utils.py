from starlette.websockets import WebSocketState
import asyncio
from audio_processing_backend.prompt import HALLUCINATION_PHRASES

def is_hallucination(text: str) -> bool:
    """Filter out Whisper hallucinations on silence"""
    cleaned = text.strip().lower().rstrip(".,!?").strip()
    
    # Empty or very short
    if len(cleaned) < 3:
        return True
    
    # Exact match against known hallucinations
    if cleaned in HALLUCINATION_PHRASES:
        return True
    
    # Repetitive pattern (e.g. "you you you")
    words = cleaned.split()
    if len(words) > 1 and len(set(words)) == 1:
        return True
    
    return False

def is_valid_webm(data: bytes) -> bool:
    """Check if data starts with valid WebM/EBML header"""
    return len(data) >= 4 and data[:4] == b'\x1a\x45\xdf\xa3'

def is_valid_audio(data: bytes) -> bool:
    """Check if data starts with valid WebM/EBML or RIFF/WAV header"""
    if len(data) < 4:
        return False
    is_webm = data[:4] == b'\x1a\x45\xdf\xa3'
    is_wav = data[:4] == b'RIFF'
    return is_webm or is_wav

async def safe_send(ws, data):
    """Safely send JSON data to WebSocket"""
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_json(data)
    except RuntimeError:
        print("   Send failed: connection already closed")
    except Exception as e:
        print(f"   Send error: {e}")
