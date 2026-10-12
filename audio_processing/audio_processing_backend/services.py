import io
import asyncio
from openai import OpenAI
from fastapi import WebSocket
from dotenv import load_dotenv
import httpx

from audio_processing_backend.prompt import SYSTEM_PROMPT
from difflib import SequenceMatcher
import os
try:
    import openai_service
except ImportError:
    import sys
    from types import ModuleType
    openai_service = ModuleType("openai_service")
    openai_service._use_local_fallback_directly = False

# Load environment variables from .env file
load_dotenv()

_client: OpenAI | None = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        key = os.getenv("OPEN_AI_KEY") or os.getenv("OPENAI_API_KEY")
        _client = OpenAI(api_key=key)
    return _client

async def llm_cleaning(context: str, current_text: str) -> str:
    """Clean transcript using LLM with context"""
    return current_text
    # prompt = SYSTEM_PROMPT.format(
    #     recent_transcript=context if context else "(no prior context)",
    #     incoming_text=current_text
    # )
    # 
    # try:
    #     if getattr(openai_service, "_use_local_fallback_directly", False):
    #         raise Exception("insufficient_quota (cached)")
    # 
    #     response = await asyncio.to_thread(
    #         _get_client().chat.completions.create,
    #         model="gpt-4o-mini",
    #         messages=[{"role": "user", "content": prompt}],
    #         max_tokens=100,
    #         temperature=0.0,  # Temperature 0.0 for deterministic transcript correction
    #         timeout=8
    #     )
    # except Exception as exc:
    #     err_str = str(exc).lower()
    #     if "quota" in err_str or "limit" in err_str or "429" in err_str or "insufficient" in err_str:
    #         try:
    #             openai_service._use_local_fallback_directly = True
    #         except Exception:
    #             pass
    #         print(f"[services] OpenAI quota limit hit. Falling back to local Ollama for transcription cleaning...", flush=True)
    #         try:
    #             fallback_model = "qwen3:8b"
    #             try:
    #                 r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)
    #                 if r.status_code == 200:
    #                     models = [m["name"] for m in r.json().get("models", [])]
    #                     qwen_models = [m for m in models if "qwen" in m]
    #                     if qwen_models:
    #                         preferred = ["qwen3:8b", "qwen3:14b", "qwen3:30b", "qwen3", "qwen2.5:7b", "qwen2.5:14b", "qwen2.5:3b", "qwen2.5"]
    #                         found = False
    #                         for pref in preferred:
    #                             if pref in qwen_models:
    #                                 fallback_model = pref
    #                                 found = True
    #                                 break
    #                         if not found:
    #                             fallback_model = qwen_models[0]
    #             except Exception:
    #                 pass
    # 
    #             print(f"[services] Using local Ollama model: '{fallback_model}'", flush=True)
    #             local_client = OpenAI(
    #                 base_url="http://127.0.0.1:11434/v1",
    #                 api_key="ollama",
    #             )
    #             response = await asyncio.to_thread(
    #                 local_client.chat.completions.create,
    #                 model=fallback_model,
    #                 messages=[{"role": "user", "content": prompt}],
    #                 max_tokens=100,
    #                 temperature=0.0,
    #                 timeout=8
    #             )
    #         except Exception as local_exc:
    #             print(f"[services] Local fallback to Ollama failed: {local_exc}, using original", flush=True)
    #             return current_text
    #     else:
    #         print(f"  LLM error: {exc}, using original")
    #         return current_text
    # 
    # if not response or not response.choices:
    #     print("   Empty LLM response, using original")
    #     return current_text

    cleaned = response.choices[0].message.content
    if cleaned:
        cleaned = cleaned.strip()
        
        # If the model returned [SILENCE], allow it to propagate
        if cleaned == "[SILENCE]":
            return cleaned
        
        # Normalize for similarity checking
        str1 = " ".join(current_text.lower().split())
        str2 = " ".join(cleaned.lower().split())
        
        if str1:
            ratio = SequenceMatcher(None, str1, str2).ratio()
            
            # Dynamic threshold: more permissive for short phrases
            # and stricter for longer phrases
            threshold = 0.5 if len(str1) < 15 else 0.7
            
            if ratio < threshold:
                print(f"⚠️ Similarity/drift check failed (ratio: {ratio:.2f}, threshold: {threshold}). Falling back to raw transcript: '{current_text}' (GPT output: '{cleaned}')")
                return current_text
        
        return cleaned
    return current_text
