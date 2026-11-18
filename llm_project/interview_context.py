"""Select complete prior exchanges for the current interview question."""

import re

_WORD = re.compile(r"[\w+#]+")
_STOP_WORDS = set(
    "about also and are can could did do does for from have how into is it me of on "
    "or should tell that the their them this to use used was were what when where "
    "which why will with would you your".split()
)
_FOLLOW_UP = re.compile(
    r"^(?:and\b|what about\b|how about\b|why\b(?!\s+\w+\s+\w+)|"
    r"go deeper\b|elaborate\b|give (?:me )?an example\b)"
    r"|\b(?:that approach|this approach|the same|in your example|"
    r"did you do (?:it|that)|does (?:it|that) work)\b",
    re.IGNORECASE,
)

_PROBE = re.compile(
    r"\b(?:exact(?:ly)?|step.by.step|under the hood|internally|in detail|"
    r"implementation|parameters?|payload|schema|config(?:uration)?|thresholds?|"
    r"retr(?:y|ies)|timeouts?|fallbacks?|edge cases?|(?:validate|verify|measure)|"
    r"how did you (?:build|implement|handle|test|deploy|store|configure|choose))\b",
    re.IGNORECASE,
)
_SHORT_PROBE = re.compile(
    r"^(?:(?:what (?:about|were|are) )?(?:the )?(?:parameters?|payload|schema|"
    r"configuration|thresholds?|fallbacks?|retr(?:y|ies)|timeouts?|"
    r"latency|cost|trade.off[s]?|inputs?|outputs?)|"
    r"what (?:exact |specific )?(?:parameters?|headers?|fields?|payload|settings?) "
    r"did you (?:send|use|pass|set)|"
    r"(?:and )?then what|what happens next|how (?:exactly|so)|"
    r"how did you (?:implement|test|validate|measure) (?:it|this|that))[?.!]*$",
    re.IGNORECASE,
)


def is_implementation_probe(question: str) -> bool:
    return bool(_PROBE.search(question) or _SHORT_PROBE.fullmatch(question.strip()))


def _terms(text: str) -> set[str]:
    return set(_WORD.findall(text.casefold())) - _STOP_WORDS


def select_interview_history(question: str, conversation: list[dict]) -> list[dict]:
    """Keep recent follow-up context and retrieve older exchanges with shared terms."""
    if not conversation:
        return []
    exchanges = [
        conversation[index:index + 2]
        for index in range(max(0, len(conversation) - 48), len(conversation) - 1)
        if conversation[index]["role"] == "user"
        and conversation[index + 1]["role"] == "assistant"
    ]
    terms = _terms(question)
    selected = set()
    if _FOLLOW_UP.search(question.strip()) or _SHORT_PROBE.fullmatch(question.strip()):
        selected.update(range(max(0, len(exchanges) - 2), len(exchanges)))
    ranked = []
    for index, (user, answer) in enumerate(exchanges):
        question_overlap = len(terms & _terms(user["content"]))
        answer_overlap = len(terms & _terms(answer["content"][:2500]))
        if question_overlap or answer_overlap >= 2:
            ranked.append((question_overlap * 3 + answer_overlap, index))
    for _, index in sorted(ranked, reverse=True):
        if len(selected) >= 3:
            break
        selected.add(index)
    return [
        {"role": turn["role"], "content": turn["content"][:2200]}
        for index in sorted(selected)
        for turn in exchanges[index]
    ]
