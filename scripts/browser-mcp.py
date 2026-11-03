#!/usr/bin/env python3
"""Portable entry point for the integration's independent Playwright MCP."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from neuraldeep_claude import local_browser


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("action", choices=("install", "status", "config", "launch"), default="launch", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.action == "launch":
            return local_browser.launch(args.root)
        result = (local_browser.install if args.action == "install" else local_browser.status if args.action == "status" else local_browser.mcp_command)(args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print("Portable browser:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
