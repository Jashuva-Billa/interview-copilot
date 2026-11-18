"""Distinguish billing exhaustion from transient rate limiting."""


class CreditsExhausted(RuntimeError):
    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"{provider.capitalize()} credits exhausted. Update the API key or add credits.")


def openai_credits_exhausted(error: Exception) -> bool:
    return getattr(error, "code", None) in ("insufficient_quota", "billing_hard_limit_reached")


def check_http_credits(provider: str, status: int, message: str) -> None:
    text = message.casefold()
    if provider == "claude" and status in (400, 402) and "credit balance" in text:
        raise CreditsExhausted(provider)
    if provider == "gemini" and status == 429 and ("billing" in text or "spend limit" in text) and ("exhausted" in text or "limit: 0" in text):
        raise CreditsExhausted(provider)
