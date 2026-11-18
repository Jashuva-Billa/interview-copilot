# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

root = Path(SPECPATH).resolve().parent

mac = sys.platform == "darwin"
a = Analysis(
    [str(root / "app/run_app.py")],
    pathex=[str(root / entry) for entry in ("wboxai_app", "llm_project", "app", "app/core", "app/monitoring", ".")],
    binaries=[(os.environ["COPILOT_MAC_AUDIO_HELPER"], ".")] if mac else [],
    datas=[(str(root / "wboxai_app/logo.png"), "wboxai_app")],
    hiddenimports=["app.credentials", "audio_processing.live_deepgram", "wboxai_app.win_ocr"],
    excludes=["PyQt6.QtQuick", "PyQt6.QtQml", "tkinter", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if mac:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Interview Copilot", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="Interview Copilot")
    app = BUNDLE(
        coll,
        name="Interview Copilot.app",
        bundle_identifier="com.interviewcopilot.desktop",
        info_plist={
            "LSMinimumSystemVersion": "14.0",
            "NSMicrophoneUsageDescription": "Transcribe your spoken interview answers.",
            "NSScreenCaptureUsageDescription": "Capture interviewer audio and assessment screenshots.",
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas,
        name="Interview-Copilot",
        icon=str(root / "wboxai_app/logo.ico"),
        console=False,
        upx=False,
    )
