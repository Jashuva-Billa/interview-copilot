import sys
import subprocess
from pathlib import Path

def load_pdf_contexts() -> str:
    """Finds all PDF files in project directories, extracts text, and returns formatted contents."""
    # Try importing pypdf
    try:
        import pypdf
    except ImportError:
        print("[PDF Loader] pypdf not installed. Attempting to install dynamically...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pypdf"], check=True)
            import pypdf
        except Exception as e:
            print(f"[PDF Loader] Failed to install pypdf: {e}")
            return "(Failed to load PDF documents: pypdf library is missing and could not be installed)"

    project_root = Path(__file__).resolve().parent.parent
    pdf_texts = []
    
    # Scan project root and wboxai_app directories
    dirs_to_scan = [project_root, project_root / "wboxai_app"]
    pdf_paths = []
    for d in dirs_to_scan:
        if d.is_dir():
            pdf_paths.extend(d.glob("*.pdf"))

    # Deduplicate
    unique_paths = list({p.resolve() for p in pdf_paths})

    if not unique_paths:
        return ""

    print(f"[PDF Loader] Found {len(unique_paths)} PDF(s) to process.")
    for path in unique_paths:
        try:
            reader = pypdf.PdfReader(path)
            text = ""
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
            if text.strip():
                pdf_texts.append(f"=== DOCUMENT: {path.name} ===\n{text.strip()}")
                print(f"[PDF Loader] Successfully loaded text from {path.name}")
        except Exception as e:
            print(f"[PDF Loader] Error reading PDF {path.name}: {e}")

    if pdf_texts:
        return "\n\n".join(pdf_texts)
    return ""
