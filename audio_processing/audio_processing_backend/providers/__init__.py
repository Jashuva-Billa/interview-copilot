import os
from .open_ai import OpenAIProvider
from .deepgram import DeepgramProvider

def get_stt_provider(provider_name_override: str = None, openai_key: str = None, deepgram_key: str = None):
    provider_name = (provider_name_override or os.getenv("STT_PROVIDER", "openai")).lower()
    if provider_name == "deepgram":
        return DeepgramProvider(api_key=deepgram_key)
    return OpenAIProvider(api_key=openai_key)
