from functools import lru_cache
from pathlib import Path
import sys

from pypdf import PdfReader


@lru_cache(maxsize=1)
def load_pdf_contexts() -> str:
    """Extract optional PDF context from the application data or source project."""
    if getattr(sys, "frozen", False):
        import config

        root = Path(config.env_file_path()).parent
        folders = (root,)
    else:
        root = Path(__file__).resolve().parents[1]
        folders = (root, root / "wboxai_app")

    paths = sorted({path.resolve() for folder in folders for path in folder.glob("*.pdf")})
    documents = []
    for path in paths:
        try:
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if text:
                documents.append(f"=== DOCUMENT: {path.name} ===\n{text}")
        except Exception as exc:
            print(f"[PDF Loader] Error reading PDF {path.name}: {exc}")
    return "\n\n".join(documents)
