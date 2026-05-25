# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path

block_cipher = None

project_root = os.path.abspath('.')
backend_dir = os.path.join(project_root, 'backend')
web_dir = os.path.join(project_root, 'web')

a = Analysis(
    [os.path.join(project_root, 'run_web.py')],
    pathex=[project_root, backend_dir],
    binaries=[],
    datas=[
        (web_dir, 'web'),
        (backend_dir, 'backend'),
        (os.path.join(project_root, '.env'), '.') if os.path.exists(os.path.join(project_root, '.env')) else (os.path.join(project_root, '.env.example'), '.env'),
    ],
    hiddenimports=[
        'flask',
        'flask_cors',
        'groq',
        'pytesseract',
        'PIL',
        'PIL.Image',
        'PIL.ImageEnhance',
        'PIL.ImageFilter',
        'cv2',
        'numpy',
        'pdf2image',
        'pdf2image.pdf2image',
        'dotenv',
        'python_dotenv',
        'engineio',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.middleware',
        'jinja2',
        'click',
        'itsdangerous',
        'markupsafe',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='smart_drafting_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='smart_drafting_backend',
)
