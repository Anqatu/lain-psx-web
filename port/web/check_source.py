#!/usr/bin/env python3
"""Statically check the source package and build inputs without running the app."""
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
manifest = json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
changed = {
    'port/web/build_web.py', 'port/web/serve.py', 'port/web/run_local.py',
    'port/psx/UPSTREAM.txt', 'port/game/FORKED_FROM.txt',
    'thirdparty/musl-file-NOTICES.txt', 'thirdparty/Emscripten-file-NOTICES.txt',
    'thirdparty/libcxx-extra-NOTICES.txt', 'thirdparty/SDL2-extra-NOTICES.txt',
    'port/web/shell.html', 'port/web/translations.json', 'port/web/pre.js', 'port/web/library.js',
    'port/src/web_main.c', 'port/psx/src/lain_mcrd/lain_mcrd.c',
    'port/psx/src/gpu/font.h', 'port/psx/src/psx/LIBGPU.C', 'port/psx/src/gte/PsyX_GTE.cpp',
    'port/psx/src/psx/LIBGTE.C', 'port/game/80013138.c',
    'port/psx/src/PsyX_main.cpp', 'port/psx/src/psx/LIBETC.C',
    'port/psx/include/PsyX/PsyX_public.h', 'port/psx/include/lain_xa.h',
    'port/psx/src/lain_xa/cd_drive.c', 'port/psx/src/lain_press/lain_stream.c',
    'port/psx/src/render/PsyX_render.cpp', 'port/psx/src/pad/PsyX_pad.cpp'
}
for relative, entry in manifest['files'].items():
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f'Copied source file is missing: {relative}')
    if relative not in changed and hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise SystemExit(f'Unrecorded change to the source snapshot: {relative}')

for name in ('README.md', 'LICENSE', '.gitignore', 'port/CMakeLists.txt', 'port/psx/CMakeLists.txt',
             'server.config.example.json', 'thirdparty/MPL-2.0.txt', 'thirdparty/TOMB5-LICENSE.txt',
             'thirdparty/MAME-GTE-LICENSE.txt', 'thirdparty/PSn00bSDK-NOTICE.txt'):
    if not (ROOT / name).is_file():
        raise SystemExit(f'Required file is missing: {name}')

# Build/dist are local outputs; inspect only the publishable source package here.
forbidden = {'.bin', '.cue', '.iso', '.chd', '.img', '.har', '.pcap', '.pcapng',
             '.mcd', '.mcr', '.sav', '.srm', '.ico', '.png', '.jpg', '.ogg', '.mp4',
             '.wasm', '.exe', '.dll', '.zip', '.7z', '.key', '.pem'}
source_files = []
for path in ROOT.rglob('*'):
    relative = path.relative_to(ROOT)
    if relative.parts[0] in {'build', 'dist', '.git', '.venv', 'rom', 'certs'} or path.name == 'server.config.json':
        continue
    if path.is_symlink():
        raise SystemExit(f'Unexpected symbolic link: {relative}')
    if not path.is_file():
        continue
    if path.suffix.lower() in forbidden or path.name.startswith('.env'):
        raise SystemExit(f'Excluded distribution file is present: {relative}')
    if '__pycache__' not in relative.parts:
        source_files.append(path)
    if path.suffix == '.py':
        ast.parse(path.read_text(encoding='utf-8'), filename=str(relative))

for name in ('port/psx/src/gpu/font.h', 'port/psx/src/psx/LIBGPU.C'):
    text = (ROOT / name).read_text(encoding='utf-8')
    if 'This Source Code Form is subject to the terms of the Mozilla Public' not in text:
        raise SystemExit(f'MPL notice is missing: {name}')
for name in ('port/psx/src/gpu/font.h', 'port/psx/src/psx/LIBGPU.C', 'port/psx/src/gte/PsyX_GTE.cpp'):
    text = (ROOT / name).read_text(encoding='utf-8')
    # License-only patches must leave the original executable statements unchanged.
    original_body = text[text.index('*/') + 2:].lstrip('\r\n')
    original_body = original_body.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8')
    original_lf = original_body.replace(b'\r\n', b'\n')
    variants = (original_body, original_body.removesuffix(b'\r\n'), original_lf, original_lf.removesuffix(b'\n'))
    if manifest['files'][name]['sha256'] not in {hashlib.sha256(value).hexdigest() for value in variants}:
        raise SystemExit(f'License-only change altered the source body: {name}')

for path in source_files:
    if path.suffix.lower() not in {'.c', '.cpp', '.h', '.py', '.js', '.cjs', '.html'} and path.name not in {'CMakeLists.txt', '.gitignore'}:
        continue
    text = path.read_text(encoding='utf-8')
    comments = re.findall(r'/\*[\s\S]*?\*/|//[^\n]*|<!--[\s\S]*?-->', text) if path.suffix.lower() not in {'.py', '.txt'} and path.name != '.gitignore' else []
    if path.suffix == '.py' or path.name in {'CMakeLists.txt', '.gitignore'}:
        comments += re.findall(r'^\s*#[^\n]*|"""[\s\S]*?"""', text, re.M)
    if any(re.search(r'[\u3040-\u30ff\u3400-\u9fff]', comment) for comment in comments):
        raise SystemExit(f'Non-English Japanese comment: {path.relative_to(ROOT)}')

sample = json.loads((ROOT / 'server.config.example.json').read_text(encoding='utf-8'))
if sample != {'host': '127.0.0.1', 'port': 8000, 'roms': {'disc1': 'rom/disk1.bin', 'disc2': 'rom/disk2.bin'}, 'tls': None, 'public_url': None}:
    raise SystemExit('Unexpected public server configuration sample')

for relative in ('port/external', 'port/client/lain_icon.h', 'port/client/app_icon.c',
                 'port/psx/src/gte/half_float.cpp', 'port/psx/include/PsyX/common/half_float.h',
                 'port/psx/src/render/glad.c', 'port/psx/src/audio/PsyX_SPUAL.cpp'):
    if (ROOT / relative).exists():
        raise SystemExit(f'Excluded source is still present: {relative}')

translations = json.loads((ROOT / 'port/web/translations.json').read_text(encoding='utf-8'))
for language in ('en', 'ja', 'ko'):
    if translations[language].keys() != translations['en'].keys():
        raise SystemExit(f'Translation keys do not match: {language}')
    for key, value in translations[language].items():
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f'Empty translation: {language}/{key}')
        if sorted(re.findall(r'\{\w+\}', value)) != sorted(re.findall(r'\{\w+\}', translations['en'][key])):
            raise SystemExit(f'Translation placeholders do not match: {language}/{key}')

for doc in ROOT.glob('*.md'):
    for link in re.findall(r'\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
        if re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', link) or link.startswith('#'):
            continue
        relative = link.split('#', 1)[0]
        if relative and not (doc.parent / relative).exists():
            raise SystemExit(f'Broken documentation link: {doc.name}: {link}')

print(f'Source files: {len(source_files)} / snapshot hashes, Python syntax, and documentation links OK')
print(f'Translations: {len(translations["en"])} keys per language / all 3 languages and placeholders match')
print('No excluded filenames/extensions found (not a rights guarantee for embedded data)')
print('No browser, server, game, or Wasm was executed')
