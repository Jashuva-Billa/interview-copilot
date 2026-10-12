# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=['.', 'wboxai_app', 'audio_processing', 'llm_project'],
    binaries=[],
    datas=[('wboxai_app/logo.png', 'wboxai_app')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6.QtQuick',
        'PyQt6.QtQml',
        'PyQt6.QtPositioning',
        'PyQt6.QtOpenGL',
        'PyQt6.QtQuickWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'tkinter',
        'unittest',
        'IPython',
        'jedi',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='wboxai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='wboxai_app/logo.ico',
)

