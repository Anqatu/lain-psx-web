#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path


def main():
    # The build also copies this launcher to run_web.py at the project root.
    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent.parent if script_dir.name == "web" and script_dir.parent.name == "port" else script_dir
    serve = root / "dist" / "web" / "serve.py"
    if not serve.is_file() or not (serve.parent / "index.html").is_file():
        raise SystemExit("Build the project first: python port/web/build_web.py")

    # Preserve the caller's working directory for all forwarded relative paths.
    command = [sys.executable, str(serve), "--open-browser", *sys.argv[1:]]
    try:
        return subprocess.run(command, check=False).returncode
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        raise SystemExit(f"Could not start the server: {error}") from None


if __name__ == "__main__":
    raise SystemExit(main())
