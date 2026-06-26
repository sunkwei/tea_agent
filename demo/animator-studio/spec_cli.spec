# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for animator-studio CLI.
Usage: pyinstaller <full-path>/spec_cli.spec --clean --noconfirm
"""
import sys, os
from pathlib import Path

block_cipher = None

# 硬编码项目路径（或者从 sys.argv[0] 推导）
HERE = Path(r'C:\Users\Hetin\work\git\tea_agent\demo\animator-studio')

a = Analysis(
    [str(HERE / 'src' / 'cli.py')],
    pathex=[str(HERE)],
    binaries=[],
    datas=[
        (str(HERE.parent / 'animator' / 'templates'), 'animator/templates'),
    ],
    hiddenimports=[
        'src.config',
        'src.core.generator',
        'src.core.recorder',
        'src.core.script_engine',
        'src.core.llm_client',
        'src.core.llm_prompts',
        'src.core.animation_dsl',
        'animator',
        'yaml',
        'httpx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='animator-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
