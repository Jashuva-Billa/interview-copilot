from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap paths before importing packages
_root = Path(__file__).resolve().parents[2]
for _p in (_root, _root / "wboxai_app", _root / "audio_processing", _root / "llm_project"):
    _p_str = str(_p.resolve())
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

import unittest
from llm_project.response_parser import parse_structured_response, parse_vision_response
from screen_capture import capture_screen_jpeg


class TestMultiFileCodingSupport(unittest.TestCase):
    def test_multi_file_code_parsing(self):
        raw_llm_response = """===APPROACH===
- Building a modular RAG pipeline using Python and vector stores.
- Separated into config, embeddings, retriever, and main pipeline modules.

===COMPLEXITY===
Time: O(N log K) — vector search
Space: O(N * D) — vector index memory

===CODE===
```python
# === FILE: src/config.py ===
class RAGConfig:
    EMBEDDING_MODEL = "text-embedding-3-small"
    VECTOR_DIM = 1536

# === FILE: src/retriever.py ===
from src.config import RAGConfig

class VectorRetriever:
    def __init__(self, index):
        self.index = index

    def query(self, text: str, top_k: int = 5):
        return self.index.search(text, k=top_k)
```

===EDGE_CASES===
- Empty vector index query return empty list.
- High dimension embedding mismatch handling.
"""

        parsed = parse_structured_response(raw_llm_response, is_coding=True)

        self.assertTrue(parsed.is_coding)
        self.assertIn("RAG pipeline", parsed.approach)
        self.assertIn("# === FILE: src/config.py ===", parsed.code)
        self.assertIn("# === FILE: src/retriever.py ===", parsed.code)
        self.assertIn("class VectorRetriever:", parsed.code)
        self.assertIn("Complexity:", parsed.approach)

    def test_uncropped_screen_capture_mode(self):
        from unittest.mock import patch
        from PIL import Image

        dummy_img = Image.new("RGB", (1920, 1080), color="blue")
        with patch("screen_capture._grab_desktop", return_value=dummy_img):
            jpeg_cropped = capture_screen_jpeg(max_width=640, crop=True)
            jpeg_uncropped = capture_screen_jpeg(max_width=640, crop=False)

            self.assertIsInstance(jpeg_cropped, bytes)
            self.assertIsInstance(jpeg_uncropped, bytes)
            self.assertGreater(len(jpeg_cropped), 0)
            self.assertGreater(len(jpeg_uncropped), 0)


if __name__ == "__main__":
    unittest.main()
