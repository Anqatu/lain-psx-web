# lain-psx-web

An unofficial WebAssembly browser port of **serial experiments lain** for PlayStation, based on **lain-psx-decompiled**. Built from native C/C++ code using **Emscripten and WebGL 2**, it runs the ported game logic through a PlayStation SDK compatibility layer, not a PS1 emulator.

Based on [Y0oshi/lain-psx-decompiled](https://github.com/Y0oshi/lain-psx-decompiled) and [PsyCross](https://github.com/OpenDriver2/PsyCross). This repository contains the files needed for the browser build, rather than the full desktop client or matching-decompilation toolchain. ROMs and save files are not included.

> [!IMPORTANT]
> **ROMs are not included.** You must provide your own disc images of both original PlayStation discs to play.
>
> **This is an unofficial project.** It is not affiliated with or endorsed by the game's original developers, publisher, or rights holders.

## Features

- **English, Japanese, and Korean UI**, with English as the default and a language selector in the top-right corner. This changes the browser interface, not the game dialogue or subtitles.
- **Two-disc support** through HTTP Range requests, with automatic disc switching as the game changes sites.
- **Private server configuration** for ROM paths, listen host, port, browser URL, and optional HTTPS.
- **4:3 display**, output resolutions from 640 x 480 to 1920 x 1440, internal scaling, sharp/smooth output filtering, optional texture filtering, and 60 Hz frame interpolation.
- **Configurable keyboard controls**, optional gamepad support, and volume settings. No on-screen controller is included.
- **Threaded WebAssembly** using pthread workers and SharedArrayBuffer. Normal remote access requires trusted HTTPS and cross-origin isolation; localhost HTTP is supported.
- **Pointer Lock and fullscreen** as separate controls. Click the game screen to lock the mouse, press Esc to release it, and the lock hint disappears after three seconds.
- **Persistent saves** using IndexedDB. Game save operations wait for browser storage to finish before reporting success.
- **128 KiB memory-card Import / Export**, including before starting the game. Raw `.mcd` and `.mcr` imports are supported; exports use `memcard1.mcd`.
- Saved display, audio, key-binding, language, and settings-panel preferences.

Desktop-only features such as Lua mods, subtitle/dub packs, and the native launcher are not included.

## Build

### Requirements

- **Emscripten 6.0.11**
- **Python 3.10 or newer**
- **CMake 3.20 or newer**
- **Ninja** and **Git** for the setup instructions below
- Internet access for the initial SDK and SDL2 downloads

SDL2 **2.32.10** is supplied by the Emscripten port. No system SDL2/OpenAL development packages, PsyQ SDK, Docker, ROMs, or npm dependencies are required to build. The project Python scripts use only the standard library.

### Windows

Install Python, CMake, Ninja, and Git, and make sure they are on `PATH`. CMake and Ninja can optionally be installed with:

```powershell
py -m pip install --user cmake ninja
```

If installed this way, add the Python user Scripts directory to `PATH`.

Open PowerShell in the project root. The following commands install the SDK in a sibling `emsdk` folder and return to the project before building:

```powershell
git clone https://github.com/emscripten-core/emsdk.git ..\emsdk
Push-Location ..\emsdk
.\emsdk.bat install 6.0.11
.\emsdk.bat activate 6.0.11
. .\emsdk_env.ps1

Pop-Location
$env:PYTHONUTF8 = "1"
python port\web\build_web.py
```

If PowerShell does not allow the environment script, open Command Prompt in the project root after installing and activating the SDK, then run:

```bat
call "..\emsdk\emsdk_env.bat"
set PYTHONUTF8=1
python port\web\build_web.py
```

### Linux / macOS

Install Python, CMake, Ninja, and Git using your system's package manager. From the project root, run:

```sh
project_root="$PWD"
git clone https://github.com/emscripten-core/emsdk.git ../emsdk
cd ../emsdk
./emsdk install 6.0.11
./emsdk activate 6.0.11
. ./emsdk_env.sh

cd "$project_root"
python3 port/web/build_web.py
```

Reactivate the SDK environment whenever you open a new terminal. On systems where Python is named `python3`, use that command in the remaining examples as well.

### Build output

Run `python port/web/build_web.py` from the project root for subsequent builds. It:

1. Validates and embeds the three UI translations and a build ID into the HTML shell.
2. Configures CMake through `emcmake` and builds with Ninja.
3. Writes the browser files to **`dist/web/`** and intermediate files to **`build/web/`**.
4. Includes this README, `LICENSE`, `thirdparty/` license notices, the corresponding MPL-covered sources, and a public server configuration example in the output.
5. Generates **`run_web.py`** in the project root.

The build does not start a server, browser, or game. Use this script rather than passing the unprocessed `shell.html` directly to CMake. Do not delete `port/game/generated/` or `port/game/PORT_TYPES.md`: they are build inputs, not disposable caches.

### Static checks

After building, use Node.js from the SDK environment:

```sh
python port/web/check_source.py
node port/web/check_static.cjs
node --check dist/web/index.js
```

These checks validate source hashes, Python/JavaScript syntax, UI references, translations, license files, matching MPL sources, and the Wasm structure without running the application. The source-hash check compares against the copied snapshot; intentional later edits may require updating its recorded exceptions.

Builds are checked on Windows with Emscripten 6.0.11, Python 3.14.4, CMake 4.4, and Ninja. Linux/macOS builds have not been tested. Some inherited compiler warnings and Emscripten's pthread/memory-growth warning remain. Static checks verify shared Wasm memory and the pthread proxies for asynchronous disc reads and save completion, but are not a substitute for testing saves, audio, and input in a browser.

## Server configuration

Copy `server.config.example.json` to **`server.config.json`** in the project root and edit it. Only the example belongs in Git; your private configuration and `certs/` are ignored and are not copied into Web builds.

```json
{
  "host": "127.0.0.1",
  "port": 8000,
  "roms": {
    "disc1": "rom/disk1.bin",
    "disc2": "rom/disk2.bin"
  },
  "tls": null,
  "public_url": null
}
```

| Setting | Meaning |
| --- | --- |
| `host` | Listen IP address or hostname, without a scheme or port. Defaults to loopback. `0.0.0.0` listens on all IPv4 interfaces; `::` listens on IPv6. |
| `port` | Listen port, from 1 to 65535. The launcher uses this port when opening the browser. |
| `roms.disc1` / `roms.disc2` | Paths to your two raw BIN images. Names are unrestricted when configured explicitly. Relative paths are resolved from the configuration file's folder. **CUE files are not required in this mode.** |
| `tls` | `null` for HTTP, or an object containing `certfile` and `keyfile` paths to enable HTTPS. Relative paths are resolved from the configuration file's folder. |
| `public_url` | Optional browser-facing origin, such as `https://lain.example.test:8443/`, for a specific hostname or reverse proxy. It changes the launch URL, not DNS, TLS, or the listening socket. No credentials, query, fragment, or subpath. |

Configured ROMs must be nonempty, single-track raw 2352-byte BIN images. This does not add ISO, CHD, or multi-track support. The server rejects an invalid config rather than silently selecting other ROMs.

Both launch commands below read the same config. To use a configuration elsewhere, pass `--config path/to/server.config.json`. CLI options override valid config values; omitted config values use defaults. `--root`, `--rom-dir`, `--disc1`, `--disc2`, `--certfile`, and `--keyfile` CLI paths are relative to the terminal's working directory. An explicit `--rom-dir` selects automatic detection instead of configured ROM paths.

The existing `port/web/config.json` is different: it contains **public browser ROM URLs**, not local filenames or server settings. Normally it should stay unchanged. Local ROM paths and TLS keys are never sent to the browser through it.

### Without a server config

Automatic detection remains available when `server.config.json` is absent. Place your own disc dumps in a `rom` folder in the project root. Use these filenames for direct BIN detection:

```text
rom/
  disk1.bin
  disk2.bin
```

Optional `disk1.cue` and `disk2.cue` files can identify the corresponding BIN files; keep each pair consistent. `disc1` / `disc2` naming is also recognized. The build does not include, create, or download ROMs or CUE files.

## Run locally

From the project root, start the included server:

```sh
python port/web/serve.py
```

Open the **Browser URL** printed by the server and select **Play**. With the default settings it is **http://127.0.0.1:8000/**. To import a save first, select **Import save**, wait for it to finish, then start the game and choose **Load** in its menu.

To start the server and open the browser automatically:

```sh
python run_web.py
```

The launcher forwards its command-line options to the server and opens the effective configured URL only after the server binds successfully. For example:

```sh
python run_web.py --config server.config.json --port 8080
```

For ROMs stored elsewhere, specify the paths explicitly:

```sh
python port/web/serve.py --root dist/web --disc1 "path/to/disk1.bin" --disc2 "path/to/disk2.bin"
```

For a standalone Web folder, run its `serve.py` with `--root . --config path/to/server.config.json`, or explicit `--disc1` / `--disc2` paths. The option names are unchanged; they accept any valid BIN filename.

Use the included server rather than `python -m http.server`, because the application requires HTTP Range support and COOP/COEP headers. Cross-origin isolation is required by this pthread build. Press **Ctrl+C** in the terminal to stop it.

### LAN and remote access

The Web build uses **pthread workers and SharedArrayBuffer**, with separate game, CD, and VBlank threads. The browser main thread handles WebGL, network requests, and persistent storage. The former experimental single-threaded Asyncify build is no longer used.

For normal access, open the page through **trusted HTTPS** with COOP/COEP headers. Localhost and loopback HTTP are browser exceptions and need no flags. An ordinary LAN HTTP origin is not a secure context and cannot run this build without a browser-specific development exception.

`0.0.0.0` and `::` are bind addresses, not client destinations. A client device's `localhost` refers to that device itself. `public_url` is optional and only changes the URL opened by the launcher; it does not configure networking or DNS.

Audio is prepared and resumed during Play; select the game screen again if the browser has suspended it. Performance and audio timing depend on the device and network. WebGL 2, WebAssembly threads, shared memory and storage support are required. No virtual D-pad or on-screen controller buttons are provided.

### HTTPS

Prepare a PEM certificate and an unencrypted private key. The certificate's **SAN must match the hostname or IP you open**, and each client must trust its issuing authority. For local development you can use a trusted local CA; a certificate-warning bypass is not a reliable substitute. This project does not generate or install certificates for you.

Example HTTPS configuration (replace the example hostname with one that resolves to your server):

```json
{
  "host": "0.0.0.0",
  "port": 8443,
  "roms": {
    "disc1": "rom/disk1.bin",
    "disc2": "rom/disk2.bin"
  },
  "tls": {
    "certfile": "certs/server.pem",
    "keyfile": "certs/server-key.pem"
  },
  "public_url": "https://lain.example.test:8443/"
}
```

Run `python run_web.py`. For access from another device, allow the listen port through the firewall and open the configured hostname on that device. `0.0.0.0` and `::` are bind addresses, not browser URLs; set `public_url` when using a specific certificate hostname.

Alternatively, keep the Python server on loopback behind a trusted HTTPS reverse proxy. Preserve HTTP Range requests, 206 responses, and the server's headers:

```text
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

The proxy must also preserve HTTP Range requests and 206 responses. Serve this app at the origin root, not under a subpath or inside an iframe. Do not strip the `sources/` or `thirdparty/` directories when deploying.

### Private HTTP testing with Chromium

For a development machine you control, Chrome may expose
`chrome://flags/#unsafely-treat-insecure-origin-as-secure` (Edge has the corresponding
`edge://flags/#unsafely-treat-insecure-origin-as-secure` page). In **Insecure origins treated as secure**,
enter your exact HTTP origin, including the port, enable the flag and restart the browser.
Use only your own test origin and restore the setting afterward. This does not encrypt
traffic, does not replace COOP/COEP, and is not available in every browser or on every device.
The application does not modify your browser settings or private server config.

The page checks secure context, cross-origin isolation, shared memory, workers and Wasm support **before loading the runtime**. Missing prerequisites, script-load failures, startup exceptions and timeouts are displayed instead of remaining indefinitely on “Loading WebAssembly…”. No single-threaded fallback is included.

### Default controls

| PlayStation action | Keyboard |
| --- | --- |
| D-pad | Arrow keys |
| Circle / Confirm | V |
| Cross / Back | C |
| Square | X |
| Triangle / Menu | Z |
| L1 / L2 / L3 | Left Shift / Left Ctrl / `[` |
| R1 / R2 / R3 | Right Shift / Right Ctrl / `]` |
| Start / Select | Enter / Space |
| Release mouse lock | Esc |

Key bindings can be changed in **Settings**. Esc is reserved for releasing input. Pointer Lock hides and captures the cursor; it does not add mouse-based gameplay or override OS-reserved shortcuts.

### Browser and save notes

- Requires **WebGL 2, WebAssembly threads, SharedArrayBuffer, Web Workers, and IndexedDB**, with secure context and cross-origin isolation.
- Pointer Lock, fullscreen, Keyboard Lock, and gamepad availability depend on the browser and permissions. Input controls do not bypass the runtime's connection requirements.
- Wait for **Saved in browser** before reloading. Export backups before clearing site data or changing browsers.
- Saves are tied to the browser and origin. `localhost` and `127.0.0.1`, different ports, and HTTP/HTTPS are separate storage locations.
- The server is for **private/local use**, binds to loopback by default, and has no authentication. TLS encrypts traffic but does not authorize users; exposing the listener publicly also exposes the ROM endpoints. The loaded private config and configured certificate/key paths are excluded from file serving.
- Do not upload ROMs, save files, or HAR captures containing ROM responses to GitHub or a public host. This repository does not include a public ROM server; use the private server described above.
- `build/`, `dist/`, ROMs, saves, and captures are excluded by `.gitignore`. That exclusion does not apply when manually zipping the entire folder.

## Source and licensing

This Web-only package keeps the game C sources, PsyCross/Lain compatibility layer, ISO loader, and browser frontend. Local changes include the Emscripten pthread build, HTTP Range reader, browser save persistence, keyboard/gamepad input handling, multilingual UI, server config/HTTPS, and license/source packaging. Desktop-only libraries, OpenAL, glad, PGXP half-float code, and game-derived desktop icons are excluded. `SOURCE_MANIFEST.json` records the copied snapshot; its top-level upstream revision is unknown. PsyCross is based on commit `e56e4cde1c2b8a15e0d4e38b26cdd9202e0d17e6`; the game-source note `82fd288` is not the revision of the whole package.

The original project [MIT License](LICENSE) is retained, but it is **not a blanket license for every file**. Keep the applicable source notices and all bundled license texts with redistributed source and browser builds; credit links do not replace them.

| Component / scope | License and notice |
| --- | --- |
| Original Lain port contributions | [MIT](LICENSE), Copyright (c) 2026 Y0oshi |
| PsyCross contributions | [MIT](thirdparty/PsyCross-LICENSE.txt), Copyright (c) 2020 REDRIVER2 Project |
| TOMB5-derived portions | [MIT](thirdparty/TOMB5-LICENSE.txt), Copyright (c) 2017 Gh0stBlade & zdimension |
| smf-derived portions of `PsyX_GTE.cpp` | [BSD-3-Clause](thirdparty/MAME-GTE-LICENSE.txt), Copyright 2003-2013 smf; identified in MAME's GTE implementation |
| `font.h` and `LIBGPU.C`, containing PSn00bSDK-derived font support | [MPL 2.0](thirdparty/MPL-2.0.txt) as combined source files; [origin and modifications](thirdparty/PSn00bSDK-NOTICE.txt) |
| Emscripten runtime | [MIT option and retained notices](thirdparty/Emscripten-LICENSE.txt), including Node.js-derived portions |
| SDL2 / yuv2rgb | [zlib](thirdparty/SDL2-LICENSE.txt) / [BSD-3-Clause](thirdparty/SDL2-yuv2rgb-LICENSE.txt) |
| musl | [MIT and individual notices](thirdparty/musl-COPYRIGHT.txt); additional notices are bundled |
| LLVM runtime components | Apache-2.0 with LLVM exceptions and accompanying notices in `thirdparty/` |

The MPL applies to the two combined files, **not an MPL-or-MIT choice**. Existing MIT notices are retained for the pre-existing MIT portions. Other separate project files are not relabeled as MPL merely because they link with those files.

### Corresponding MPL source

The modified source used for the build is available as [LIBGPU.C](port/psx/src/psx/LIBGPU.C) and [font.h](port/psx/src/gpu/font.h). Every Web build also bundles byte-for-byte copies under `sources/port/psx/src/`, and the browser footer links directly to them. The embedded font array is additionally emitted as `sources/port/psx/src/gpu/dbugfont.tim` for editing. The licenses are included alongside the covered source and in `thirdparty/`.

Recipients can obtain these files without a ROM, account, or payment. Keep the complete `sources/` and `thirdparty/` folders available at the same location as the distributed JS/Wasm. When changing covered code, rebuild and distribute the updated source with the new executable. An unmodified upstream link alone is not the corresponding source of this modified build.

The notice collection includes some SDK portions removed during linking. Restoring these notices did not change the GPU/GTE executable statements or the font bytes.

**Remaining provenance questions:** the original-game-derived C code's redistribution rights remain unverified. Font code/data has been traced to the stated PSn00bSDK revision, but the artwork's earlier origin is not independently established. The origins of some legacy SDK declarations, GTE register structures/tables, and the Freeverb-style reverb also remain unverified. These license corrections do not settle those separate questions or establish a GPL violation.

*serial experiments lain* belongs to its respective rights holders. This project is unofficial and is not affiliated with or endorsed by them.

## Credits

- **[Y0oshi](https://github.com/Y0oshi/lain-psx-decompiled)** — original decompilation, native port, and Lain-specific compatibility code.
- **[REDRIVER2 Project / OpenDriver2 / PsyCross](https://github.com/OpenDriver2/PsyCross)**, **[SoapyMan](https://github.com/SoapyMan)**, and **[Gh0stBlade](https://github.com/Gh0stBlade)** — PlayStation compatibility framework and its foundations.
- **[Gh0stBlade & zdimension / TOMB5](https://github.com/TOMB5/TOMB5)** — inherited emulator and SDK compatibility code.
- **[Lameguy64 / Meido-Tek Productions / PSn00bSDK](https://github.com/Lameguy64/PSn00bSDK)** — GPU font and TIM support under MPL 2.0.
- **[smf / MAME](https://github.com/mamedev/mame/blob/mame0187/src/devices/cpu/psx/gte.cpp)** — GTE implementation portions under BSD-3-Clause.
- **[Emscripten authors](https://github.com/emscripten-core/emscripten)** — WebAssembly toolchain and browser runtime.
- **[Sam Lantinga and SDL contributors](https://github.com/libsdl-org/SDL)** — SDL2.
- **[Rich Felker and musl contributors](https://musl.libc.org/)** — C runtime and math library.
- **[LLVM contributors](https://github.com/llvm/llvm-project)** — compiler-rt, libc++, libc++abi, and related runtime components.
- **[Joyent and Node.js contributors](https://github.com/nodejs/node)** — path-handling code used by Emscripten.
- **[Adrien Descamps](https://github.com/descampsa/yuv2rgb)** — yuv2rgb components in SDL2.
- **[Python](https://github.com/python/cpython)**, **[CMake](https://github.com/Kitware/CMake)**, and **[Ninja](https://github.com/ninja-build/ninja)** contributors — build and local-server tools.
