#!/usr/bin/env python3
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

PORT = Path(__file__).resolve().parents[1]
ROOT = PORT.parent
BUILD = ROOT / "build" / "web"
DIST = ROOT / "dist" / "web"
NOTICES = ("LICENSE", "README.md")
MPL_SOURCES = ("port/psx/src/gpu/font.h", "port/psx/src/psx/LIBGPU.C")
SOURCE_NOTICES = ("LICENSE", "port/psx/LICENSE", "thirdparty/MPL-2.0.txt",
                  "thirdparty/PSn00bSDK-NOTICE.txt", "thirdparty/TOMB5-LICENSE.txt")

# Keep notices and matching MPL-covered source available with every executable build.
for name in (*NOTICES, *MPL_SOURCES, *SOURCE_NOTICES, "thirdparty/MAME-GTE-LICENSE.txt",
             "server.config.example.json"):
    if not (ROOT / name).is_file():
        raise SystemExit(f"Required distribution document is missing: {name}")

shell = (PORT / "web" / "shell.html").read_text(encoding="utf-8")
translations = json.loads((PORT / "web" / "translations.json").read_text(encoding="utf-8"))
keys = translations["en"].keys()
for language in ("en", "ja", "ko"):
    if translations[language].keys() != keys:
        raise SystemExit(f"Translation keys do not match: {language}")
    for key in keys:
        value = translations[language][key]
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"Translation is empty: {language}/{key}")
        if sorted(re.findall(r"\{\w+\}", value)) != sorted(re.findall(r"\{\w+\}", translations["en"][key])):
            raise SystemExit(f"Translation placeholders do not match: {language}/{key}")
# Embed translations so the first render needs no additional fetch or loading race.
translation_json = json.dumps(translations, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
shell = shell.replace("__LAIN_TRANSLATIONS__", translation_json)
generated_shell = BUILD / "shell.html"
build_id = str(time.time_ns())

BUILD.mkdir(parents=True, exist_ok=True)
generated_shell.write_text(shell.replace("__LAIN_BUILD_ID__", build_id), encoding="utf-8")

# Snapshot the covered source before compilation; refuse mismatched output if it changes.
covered_source = {name: (ROOT / name).read_bytes() for name in MPL_SOURCES}
subprocess.run([
    "emcmake", "cmake", "-S", str(PORT), "-B", str(BUILD), "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=Release", f"-DLAIN_WEB_SHELL={generated_shell}",
], check=True)
subprocess.run(["cmake", "--build", str(BUILD), "--target", "lain_web"], check=True)
for name, content in covered_source.items():
    if (ROOT / name).read_bytes() != content:
        raise SystemExit(f"Source changed during the build; rebuild before distributing: {name}")

DIST.mkdir(parents=True, exist_ok=True)
for pattern in ("index.html", "index.js", "index.wasm", "index.worker.js"):
    source = BUILD / pattern
    if source.exists():
        shutil.copy2(source, DIST / source.name)
index = DIST / "index.html"
html = index.read_text(encoding="utf-8")
html = re.sub(r"src=(['\"]?)index\.js\1", f'src="index.js?v={build_id}"', html)
index.write_text(html, encoding="utf-8")
shutil.copy2(PORT / "web" / "config.json", DIST / "config.json")
shutil.copy2(PORT / "web" / "serve.py", DIST / "serve.py")
shutil.copy2(PORT / "web" / "run_local.py", ROOT / "run_web.py")
shutil.copy2(ROOT / "server.config.example.json", DIST / "server.config.example.json")
for name in NOTICES:
    shutil.copy2(ROOT / name, DIST / name)
shutil.copytree(ROOT / "thirdparty", DIST / "thirdparty", dirs_exist_ok=True)
for name in (*MPL_SOURCES, *SOURCE_NOTICES):
    destination = DIST / "sources" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if name in covered_source:
        destination.write_bytes(covered_source[name])
    else:
        shutil.copy2(ROOT / name, destination)
# Preserve an editable TIM representation of the existing upstream font array.
font_source = covered_source[MPL_SOURCES[0]].decode("utf-8")
font_array = re.search(r"unsigned char dbugfont\[\]\s*=\s*\{([^}]+)\}", font_source)
assert font_array is not None, "Debug font array is missing from the covered source"
font_bytes = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", font_array[1]))
if len(font_bytes) != 2112:
    raise SystemExit("Unexpected debug font size; review the corresponding source package")
(DIST / "sources/port/psx/src/gpu/dbugfont.tim").write_bytes(font_bytes)
# Only the distribution copy needs links into its bundled source directory.
readme = (ROOT / "README.md").read_text(encoding="utf-8")
for name in MPL_SOURCES:
    readme = readme.replace(f"]({name})", f"](sources/{name})")
(DIST / "README.md").write_text(readme, encoding="utf-8")
print(DIST)
