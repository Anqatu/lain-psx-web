#!/usr/bin/env python3
import argparse
import hashlib
import ipaddress
import json
import mimetypes
import re
import socket
import ssl
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Handler(SimpleHTTPRequestHandler):
    server_version = "LainWeb/1.0"

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "Accept-Ranges, Content-Range, ETag")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.end_headers()

    def mapped_path(self):
        try:
            path = unquote(urlsplit(self.path).path)
            # Reject Windows path aliases and alternate data streams on every platform.
            if any(character in path for character in ("\\", ":", "\x00")):
                return None
            if any(part.rstrip(" .").lower() == "server.config.json" for part in path.split("/")):
                return None
            if path == "/rom/disc1.bin":
                candidate = self.server.discs[0]
            elif path == "/rom/disc2.bin":
                candidate = self.server.discs[1]
            else:
                relative = path.lstrip("/") or "index.html"
                candidate = (self.server.web_root / relative).resolve()
                candidate.relative_to(self.server.web_root)
            if candidate.name.rstrip(" .").lower() == "server.config.json":
                return None
            for private in self.server.private_paths:
                # samefile also catches hard links and filesystem-specific aliases.
                if candidate == private or (private.is_file() and candidate.samefile(private)):
                    return None
            return candidate
        except (OSError, RuntimeError, ValueError):
            return None

    def do_GET(self):
        self.send_file(False)

    def do_HEAD(self):
        self.send_file(True)

    def send_file(self, head_only):
        path = self.mapped_path()
        if not path or not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        header = self.headers.get("Range")
        if header:
            try:
                unit, value = header.split("=", 1)
                if unit.strip() != "bytes" or "," in value:
                    raise ValueError
                first, last = value.split("-", 1)
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                else:
                    length = int(last)
                    start = max(0, size - length)
                    end = size - 1
                if start < 0 or end < start or start >= size:
                    raise ValueError
                end = min(end, size - 1)
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = end - start + 1
        mime = {
            ".wasm": "application/wasm",
            ".js": "text/javascript",
            ".c": "text/plain",
            ".h": "text/plain",
        }.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        etag = hashlib.sha1(f"{path}:{size}:{path.stat().st_mtime_ns}".encode()).hexdigest()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Cache-Control", "no-store")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main():
    parser = argparse.ArgumentParser(description="Serve Lain Native Web over HTTP or HTTPS with ROM Range support")
    script = Path(__file__).resolve()
    # Recognize source and generated layouts without depending on installed ROMs.
    if script.parent.name == "web" and script.parent.parent.name in ("port", "dist"):
        project = script.parents[2]
        default_root = project / "dist" / "web"
    else:
        project = default_root = script.parent
    parser.add_argument("--config", type=Path, help="Private JSON config; defaults to optional project/server.config.json")
    parser.add_argument("--root", type=Path, help="Static web root (relative to the working directory)")
    parser.add_argument("--rom-dir", type=Path, help="Auto-detect ROMs here instead of config ROMs (relative to the working directory)")
    parser.add_argument("--disc1", type=Path, help="Disc 1 raw BIN (relative to the working directory)")
    parser.add_argument("--disc2", type=Path, help="Disc 2 raw BIN (relative to the working directory)")
    parser.add_argument("--host", help="Listen address: IPv4, unbracketed IPv6, or hostname (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Listen port, 1-65535 (default: 8000)")
    parser.add_argument("--certfile", type=Path, help="TLS PEM certificate (relative to the working directory)")
    parser.add_argument("--keyfile", type=Path, help="TLS PEM private key (relative to the working directory)")
    parser.add_argument("--public-url", help="Browser-facing HTTP(S) origin, optionally ending in /; no subpaths")
    parser.add_argument("--open-browser", action="store_true", help="Open the effective browser URL after binding successfully")
    args = parser.parse_args()

    def validate_host(value, label):
        if not isinstance(value, str) or not value or any(character.isspace() for character in value):
            raise ValueError(f"{label} must be an IP address or hostname without whitespace")
        if "%" not in value:
            try:
                return str(ipaddress.ip_address(value))
            except ValueError:
                pass
        hostname = value[:-1] if value.endswith(".") else value
        if (len(hostname) > 253 or re.fullmatch(r"[0-9.]+", hostname)
                or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                           for part in hostname.split("."))):
            raise ValueError(f"{label} must be an IP address or hostname, not a URL, path, or host:port")
        return value

    def validate_port(value, label):
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError(f"{label} must be an integer between 1 and 65535")
        return value

    def validate_public_url(value):
        if (not isinstance(value, str) or not value
                or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
                or any(character in value for character in ("\\", "?", "#"))):
            raise ValueError("public_url must be an HTTP(S) origin without whitespace, query, or fragment")
        parts = urlsplit(value)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.path not in ("", "/")
                or not re.fullmatch(r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]+)?", parts.netloc)):
            raise ValueError("public_url must be an HTTP(S) origin without credentials or subpaths")
        validate_host(parts.hostname, "public_url host")
        if parts.port is not None:
            validate_port(parts.port, "public_url port")
        return f"{parts.scheme}://{parts.netloc}/"

    def is_loopback(host):
        hostname = host.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def config_path(value, label, base):
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError(f"{label} must be a nonempty filesystem path")
        return (base / value).resolve()

    def find_disc(number, rom_dir):
        if not rom_dir.is_dir():
            raise ValueError(f"ROM directory does not exist: {rom_dir}; set roms in the config or use --disc1/--disc2")
        marker = re.compile(rf"dis[ck][ _-]*{number}\b", re.IGNORECASE)
        for cue in sorted(rom_dir.glob("*.cue")):
            if not marker.search(cue.stem):
                continue
            for line in cue.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                match = re.match(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY\s*$', line, re.IGNORECASE)
                if match:
                    image = cue.parent / (match.group(1) or match.group(2))
                    if image.is_file():
                        return image.resolve()
        matches = [path for path in sorted(rom_dir.glob("*.bin")) if marker.search(path.stem)]
        if len(matches) == 1:
            return matches[0].resolve()
        raise ValueError(f"Could not uniquely find disk{number}.bin / disk{number}.cue in {rom_dir}; use --disc{number}")

    try:
        config_file = (args.config if args.config is not None else project / "server.config.json").resolve()
        config = {}
        try:
            config_text = config_file.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            if args.config is not None:
                raise ValueError(f"Config file does not exist: {config_file}") from None
        except (OSError, UnicodeError) as error:
            raise ValueError(f"Cannot read config {config_file}: {error}") from None
        else:
            try:
                config = json.loads(config_text)
            except ValueError as error:
                raise ValueError(f"Invalid JSON in {config_file}: {error}") from None
        if not isinstance(config, dict):
            raise ValueError(f"Config must be a JSON object: {config_file}")
        unknown = set(config) - {"host", "port", "roms", "tls", "public_url"}
        if unknown:
            raise ValueError(f"Unknown config keys: {', '.join(sorted(unknown))}")

        host = validate_host(config.get("host", "127.0.0.1"), "host")
        port = validate_port(config.get("port", 8000), "port")
        if args.host is not None:
            host = validate_host(args.host, "--host")
        if args.port is not None:
            port = validate_port(args.port, "--port")

        roms = {}
        if "roms" in config:
            if not isinstance(config["roms"], dict) or set(config["roms"]) != {"disc1", "disc2"}:
                raise ValueError("roms must contain exactly disc1 and disc2 filesystem paths")
            roms = {key: config_path(value, f"roms.{key}", config_file.parent)
                    for key, value in config["roms"].items()}

        tls = config.get("tls")
        tls_paths = {}
        if tls is not None:
            if not isinstance(tls, dict) or set(tls) != {"certfile", "keyfile"}:
                raise ValueError("tls must be null or contain exactly certfile and keyfile filesystem paths")
            tls_paths = {key: config_path(value, f"tls.{key}", config_file.parent)
                         for key, value in tls.items()}
        certfile = args.certfile.resolve() if args.certfile is not None else tls_paths.get("certfile")
        keyfile = args.keyfile.resolve() if args.keyfile is not None else tls_paths.get("keyfile")
        if (certfile is None) != (keyfile is None):
            raise ValueError("TLS requires both certfile and keyfile; set both in the config or on the CLI")
        context = None
        if certfile is not None:
            for label, path in (("certfile", certfile), ("keyfile", keyfile)):
                if not path.is_file():
                    raise ValueError(f"TLS {label} is not a file: {path}")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            try:
                # Supplying a password prevents interactive prompts for encrypted keys.
                context.load_cert_chain(str(certfile), str(keyfile), password="")
            except (OSError, ValueError) as error:
                raise ValueError(f"Cannot load TLS certificate/key (an unencrypted PEM key is required): {error}") from None

        public_url = config.get("public_url")
        if public_url is not None:
            public_url = validate_public_url(public_url)
        if args.public_url is not None:
            public_url = validate_public_url(args.public_url)

        root = (args.root if args.root is not None else default_root).resolve()
        if not root.is_dir():
            raise ValueError(f"Web root is not a directory: {root}; build the project first or set --root")
        if not (root / "index.html").is_file():
            raise ValueError(f"Web root has no index.html: {root}; build the project first or set --root to dist/web")
        rom_dir = (args.rom_dir if args.rom_dir is not None else project / "rom").resolve()
        discs = []
        for number, explicit in ((1, args.disc1), (2, args.disc2)):
            if explicit is not None:
                disc = explicit.resolve()
            elif args.rom_dir is not None or not roms:
                disc = find_disc(number, rom_dir)
            else:
                disc = roms[f"disc{number}"]
            if not disc.is_file():
                raise ValueError(f"Disc {number} is not a file: {disc}")
            size = disc.stat().st_size
            if size <= 0 or size % 2352:
                raise ValueError(f"Disc {number} requires a nonempty raw 2352-byte BIN: {disc}")
            discs.append(disc)

        # Protect configured files even when CLI overrides them or --root exposes the project.
        private_paths = {config_file, (project / "server.config.json").resolve(), *tls_paths.values()}
        private_paths.update(path for path in (certfile, keyfile) if path is not None)
        family, _, _, _, address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]

        class Server(ThreadingHTTPServer):
            address_family = family

            def get_request(self):
                connection, client_address = super().get_request()
                connection.settimeout(15)
                return connection, client_address

            def process_request_thread(self, request, client_address):
                if context is not None:
                    try:
                        request.do_handshake()
                    except OSError:
                        self.shutdown_request(request)
                        return
                super().process_request_thread(request, client_address)

        # Manual binding inside the context ensures all startup failures close the socket.
        with Server(address, Handler, bind_and_activate=False) as server:
            server.web_root = root
            server.discs = discs
            server.private_paths = private_paths
            scheme = "https" if context is not None else "http"
            try:
                server.server_bind()
                server.server_activate()
                if context is not None:
                    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
            except OSError as error:
                raise ValueError(f"Cannot start {scheme.upper()} listener on {host}:{port}: {error}") from None
            actual_port = server.server_address[1]
            browser_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
            authority = f"[{browser_host}]" if ":" in browser_host else browser_host
            browser_url = public_url or f"{scheme}://{authority}:{actual_port}/"
            listen_host = f"[{host}]" if ":" in host else host
            print(f"Disc 1: {discs[0]}")
            print(f"Disc 2: {discs[1]}")
            print(f"Listening: {scheme}://{listen_host}:{actual_port}/")
            print(f"Browser URL: {browser_url}", flush=True)
            if context is None and not is_loopback(host):
                print("WARNING: Direct LAN HTTP needs a browser development exception for this pthread build. "
                      "Use trusted HTTPS for normal access; preserve COOP/COEP through any proxy.", file=sys.stderr, flush=True)
                print("WARNING: This server has no authentication. Anyone who can reach it can request the ROMs.",
                      file=sys.stderr, flush=True)
            browser_parts = urlsplit(browser_url)
            if browser_parts.scheme == "http" and not is_loopback(browser_parts.hostname):
                print("WARNING: The browser URL is non-local HTTP. Configure the exact origin in Chromium's "
                      "insecure-origin development flag for private testing, or use an HTTPS URL.", file=sys.stderr, flush=True)
            if context is not None:
                print("HTTPS clients must trust the certificate and its SAN must match the browser URL host.", flush=True)
            if args.open_browser:
                def open_browser():
                    try:
                        if not webbrowser.open(browser_url):
                            print("WARNING: Could not open a browser; open the Browser URL manually.", file=sys.stderr)
                    except (OSError, webbrowser.Error) as error:
                        print(f"WARNING: Could not open a browser: {error}", file=sys.stderr)
                # Some browser launchers block until the browser exits; keep serving independently.
                threading.Thread(target=open_browser, daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
