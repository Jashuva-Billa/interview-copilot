import os
import sys
import time
import subprocess
from pathlib import Path

# Paths to watch
ROOT = Path(__file__).resolve().parent
WATCH_EXTENSIONS = {".py", ".spec"}
EXCLUDE_DIRS = {"venv", "build", "dist", ".git", "__pycache__"}

def get_max_mtime():
    max_mtime = 0.0
    for path in ROOT.glob("**/*"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in WATCH_EXTENSIONS:
            # Skip watch_build.py itself to prevent rebuild loops when watching this script
            if path.name == "watch_build.py":
                continue
            try:
                mtime = path.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
            except Exception:
                pass
    return max_mtime

def rebuild():
    print("\n" + "="*65)
    print(f"[{time.strftime('%H:%M:%S')}] Code change detected! Rebuilding wboxai.exe...")
    print("="*65)
    
    # 1. Build main application
    print("Step 1: Building wboxai.exe...")
    pyinstaller_path = ROOT / "venv" / "Scripts" / "pyinstaller.exe"
    if not pyinstaller_path.is_file():
        pyinstaller_path = Path("pyinstaller")
        
    try:
        subprocess.run([str(pyinstaller_path), "--clean", "main.spec"], check=True)
        print("wboxai.exe built successfully!")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: wboxai.exe build failed: {e}")
        return False

    # 2. Copy wboxai.exe to Desktop
    print("\nStep 2: Copying wboxai.exe to Desktop...")
    src_exe = ROOT / "dist" / "wboxai.exe"
    dst_exe = Path(os.environ["USERPROFILE"]) / "Desktop" / "wboxai.exe"
    
    try:
        if src_exe.is_file():
            import shutil
            shutil.copy2(src_exe, dst_exe)
            print(f"wboxai.exe successfully copied to Desktop!")
        else:
            print("ERROR: wboxai.exe not found in dist/")
            return False
    except Exception as e:
        print(f"ERROR: Failed to copy wboxai.exe to Desktop: {e}")
        return False
        
    print("\n" + "="*65)
    print(f"[{time.strftime('%H:%M:%S')}] Rebuild completed successfully! Watching for changes...")
    print("="*65)
    return True

def main():
    print("Starting WboxAI Auto-Rebuilder Watcher...")
    print(f"Watching directory: {ROOT}")
    print(f"Watching extensions: {WATCH_EXTENSIONS}")
    print(f"Excluding directories: {EXCLUDE_DIRS}")
    print("Press Ctrl+C to stop.\n")
    
    last_mtime = get_max_mtime()
    print("Initial scan complete. Watching for changes...")
    
    while True:
        try:
            time.sleep(2.0)
            current_mtime = get_max_mtime()
            if current_mtime > last_mtime:
                # Give a short delay for file writing to finish (debouncing)
                time.sleep(0.5)
                success = rebuild()
                # Update mtime after rebuild finishes to ignore mtime shifts during compiler execution
                last_mtime = get_max_mtime()
        except KeyboardInterrupt:
            print("\nStopping watcher. Goodbye!")
            sys.exit(0)
        except Exception as e:
            print(f"Watcher error: {e}")
            time.sleep(5.0)

if __name__ == "__main__":
    main()
