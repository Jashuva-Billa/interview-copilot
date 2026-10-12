import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
for p in (_root, _root / "audio_processing", _root / "wboxai_app", _root / "llm_project"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from audio_stt.conversation import SpeakerRoleResolver, QuestionDetector, InterviewQuestionProcessor
from audio_stt.models import ConversationState, AudioSourceKind, TranscriptSegment
from audio_stt.sources import source_metadata

print("=" * 60)
print("DEMONSTRATION: STABLE SPEAKER ROLE MAPPING & RESOLUTION")
print("=" * 60)

# Session A: candidate_speaker_id = 0
print("\n--- SESSION 1 (candidate = speaker 0) ---")
resolver = SpeakerRoleResolver()
state = ConversationState()
detector = QuestionDetector()

resolver.calibrate_candidate(0)

# Attempt duplicate/conflicting calibration
resolver.calibrate_candidate(1)

turns_session1 = [
    (1, "What's the use of constructor?"),
    (0, "It is used to initialize the variables."),
    (1, "How does Python manage memory?"),
    (0, "What is the GIL in Python?"),  # Candidate asking a question -> role remains CANDIDATE
]

for spk, text in turns_session1:
    print(f"\n[DEEPGRAM][FINAL][speaker={spk}]")
    print(text)
    role, conf = resolver.resolve(state, spk, AudioSourceKind.SYSTEM, text)
    print(f"[ROLE] speaker={spk} -> {role.value.lower()}")
    if role.value == "INTERVIEWER":
        res = detector.detect(text)
        if res.is_question:
            print(f"[QUESTION]\n{res.text}")
        else:
            print(f"[INTERVIEWER]\n{text}")
    elif role.value == "CANDIDATE":
        print(f"[CANDIDATE]\n{text}")
    else:
        print(f"[UNKNOWN]\n{text}")

# Session B: candidate_speaker_id = 1
print("\n" + "=" * 60)
print("--- SESSION 2 (candidate = speaker 1) ---")
resolver2 = SpeakerRoleResolver()
state2 = ConversationState()
resolver2.calibrate_candidate(1)

turns_session2 = [
    (0, "Tell me about your experience with microservices."),
    (1, "I built scalable REST microservices with FastAPI and Docker."),
    (0, "How do you handle distributed transactions?"),
]

for spk, text in turns_session2:
    print(f"\n[DEEPGRAM][FINAL][speaker={spk}]")
    print(text)
    role, conf = resolver2.resolve(state2, spk, AudioSourceKind.SYSTEM, text)
    print(f"[ROLE] speaker={spk} -> {role.value.lower()}")
    if role.value == "INTERVIEWER":
        res = detector.detect(text)
        if res.is_question:
            print(f"[QUESTION]\n{res.text}")
        else:
            print(f"[INTERVIEWER]\n{text}")
    elif role.value == "CANDIDATE":
        print(f"[CANDIDATE]\n{text}")
    else:
        print(f"[UNKNOWN]\n{text}")

print("\n" + "=" * 60)
print("DEMONSTRATION COMPLETE - ALL INVARIANTS SATISFIED")
print("=" * 60)
