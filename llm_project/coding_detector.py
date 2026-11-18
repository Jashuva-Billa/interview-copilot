"""Detect LeetCode / CoderPad / HackerRank style coding questions."""

import re

CODING_KEYWORDS = (
    r"\b(write\s+a\s+function|write\s+code|coding|leetcode|"
    r"hackerrank|coderpad|codility|white[\s-]?box|problem\s+statement|"
    r"pair\s+program|"
    r"time\s+complexity|space\s+complexity|big\s*o|binary\s+search|"
    r"dynamic\s+programming|\bdp\b|recursion|iterate|array|linked\s+list|"
    r"binary\s+tree|graph|hash\s*map|stack|queue|heap|sort|substring|"
    r"subarray|palindrome|two\s+pointers|sliding\s+window|dfs|bfs|"
    r"memoization|topological|parentheses|anagram|permutation|"
    r"fibonacci|reverse\s+the|find\s+the\s+index|return\s+an\s+array|"
    r"given\s+an\s+array|given\s+a\s+string|integer\s+array|"
    r"constraints?\s*:|examples?\s*:|input:\s*|output:\s*|"
    r"run\s+test\s+cases|submit\s+this|pass\s+#\s*implement)\b"
)

# Transcript / OCR hints
_CODING_SIGNATURE_RE = re.compile(
    r"\bdef\s+\w+\s*\(|=>\s*str|->\s*\w+|pass\s*#\s*implement|"
    r"problem\s+statement|write\s+(the\s+)?function",
    re.IGNORECASE,
)

_PATTERN = re.compile(CODING_KEYWORDS, re.IGNORECASE)
_CONCEPTUAL = re.compile(
    r"^(?:what (?:is|are)\b|why\b|how (?:does|do|would|can|should|could)\b|explain\b|describe\b|compare\b)",
    re.IGNORECASE,
)
_PAST_IMPLEMENTATION = re.compile(
    r"\b(?:how|why|where|when|what)\b[^?.!]*\b(?:did you|did your team|have you|"
    r"you implemented|you built)\b",
    re.IGNORECASE,
)
_IMPLEMENTATION = re.compile(
    r"\b(?:write (?:a|an|the|some) (?:function|program|solution|code|script)"
    r"|write code|code up|solve (?:this|the) (?:problem|challenge))\b",
    re.IGNORECASE,
)


def is_coding_question(text: str, force: bool = False) -> bool:
    if force:
        return True
    if _PAST_IMPLEMENTATION.search(text):
        return False
    if _CODING_SIGNATURE_RE.search(text) or _IMPLEMENTATION.search(text):
        return True
    if _CONCEPTUAL.match(text.strip()):
        return False
    if re.match(r"^(?:(?:can|could|would) you )?implement\b", text.strip(), re.I):
        return True
    if len(text.split()) < 3:
        return False
    if _PATTERN.search(text):
        return True
    # "write X in python" / "solve this problem"
    if re.search(
        r"\b(solve|code\s+up|program)\b.{0,40}\b(problem|question|this)\b",
        text,
        re.I,
    ):
        return True
    return False
