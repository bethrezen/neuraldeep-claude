from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from . import catalog, integration
from .config import DEFAULT_ROOT
from .transport import UpstreamError

def main(argv=None):
    # Windows pipes may otherwise inherit a legacy code page and fail on model
    # labels (Russian text and the wallet badge). MCP already uses UTF-8 too.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Portable NeuralDeep integration for Claude Code")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    models = sub.add_parser("models")
    models.add_argument("action", choices=["update", "list", "show"], default="list", nargs="?")
    models.add_argument("model", nargs="?")
    settings = sub.add_parser("prepare")
    settings.add_argument("--model", default=integration.DEFAULT_MODEL)
    settings.add_argument("--port", type=int, default=None)
    install = sub.add_parser("install")
    install.add_argument("--bin-dir", type=Path)
    install.add_argument("--activate", action="store_true", help="Apply main Claude config, backup current settings")
    activate = sub.add_parser("activate")
    activate.add_argument("--port", type=int, default=None)
    gateway = sub.add_parser("gateway")
    gateway.add_argument("--port", type=int, default=None)
    start = sub.add_parser("start")
    start.add_argument("--port", type=int, default=None)
    restart = sub.add_parser("restart")
    restart.add_argument("--port", type=int, default=None)
    launch = sub.add_parser("launch")
    launch.add_argument("--model", default=integration.DEFAULT_MODEL)
    launch.add_argument("--port", type=int, default=None)
    launch.add_argument("--cached", action="store_true")
    launch.add_argument("claude_args", nargs=argparse.REMAINDER)
    native = sub.add_parser("native", help="Pass arguments to the original Claude CLI")
    native.add_argument("claude_args", nargs=argparse.REMAINDER)
    services = sub.add_parser("services")
    services.add_argument("service_args", nargs=argparse.REMAINDER)
    desktop = sub.add_parser("desktop")
    desktop.add_argument("action", choices=["prepare", "activate", "launch"], default="prepare", nargs="?")
    desktop.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    supplied_port = getattr(args, "port", None)
    port = integration.active_port(root) if supplied_port is None else supplied_port
    if not 1 <= port <= 65535:
        parser.error("Gateway port must be between 1 and 65535")
    try:
        if args.command == "models":
            cat = catalog.refresh(root) if args.action == "update" else catalog.load(root)
            if args.action == "show":
                if not args.model:
                    raise ValueError("models show requires a model ID")
                print(json.dumps(catalog.resolve(cat, args.model), ensure_ascii=False, indent=2))
            else:
                for row in catalog.picker(cat):
                    print(row["model"] + "\t" + row["label"] + "\t" + row["description"])
                print(f"\nRefreshed {cat['refreshed_at']}; {len(cat['models'])} billing-specific chat models")
            if args.action == "update":
                integration.prepare(root, port=port)
                if (root / ".local/activation.json").exists():
                    integration.activate(root, port)
                if (root / ".local/desktop-activation.json").exists():
                    from .desktop import activate as activate_desktop
                    activate_desktop(root, port)
        elif args.command == "prepare":
            print(integration.prepare(root, args.model, port))
        elif args.command == "install":
            catalog.refresh(root)
            from .services import service_state
            if service_state(root).get("browser"):
                from .local_browser import install as install_browser
                print("Browser:", json.dumps(install_browser(root), ensure_ascii=False, default=str))
            print("Settings:", integration.prepare(root, port=port))
            from .desktop import prepare as prepare_desktop
            print("Desktop:", json.dumps(prepare_desktop(root, port), ensure_ascii=False, default=str))
            print("Launcher:", integration.install(root, args.bin_dir))
            from .skills import install_skills
            print("Skills:", json.dumps(install_skills(root), ensure_ascii=False, default=str))
            if args.activate:
                integration.ensure_gateway(root, port)
                from .desktop import activate as activate_desktop
                print(json.dumps({"cli": integration.activate(root, port), "desktop": activate_desktop(root, port)}, ensure_ascii=False, indent=2, default=str))
        elif args.command == "activate":
            integration.ensure_gateway(root, port)
            from .desktop import activate as activate_desktop
            print(json.dumps({"cli": integration.activate(root, port), "desktop": activate_desktop(root, port)}, ensure_ascii=False, indent=2, default=str))
        elif args.command == "gateway":
            from .gateway import serve
            serve(root, port)
        elif args.command == "start":
            integration.ensure_gateway(root, port)
            print(f"Gateway ready at http://127.0.0.1:{port}")
        elif args.command == "restart":
            integration.restart_gateway(root, port)
            print(f"Gateway restarted at http://127.0.0.1:{port}")
        elif args.command == "launch":
            return integration.launch(root, args.claude_args[1:] if args.claude_args[:1] == ["--"] else args.claude_args, args.model, port, not args.cached)
        elif args.command == "native":
            return integration.launch_native(root, args.claude_args[1:] if args.claude_args[:1] == ["--"] else args.claude_args, port)
        elif args.command == "services":
            from .services import main as service_main
            result = service_main(["--root", str(root)] + args.service_args)
            # Regenerate CLI MCP config after toggles. Live disabling also works.
            if args.service_args and args.service_args[0] in ("enable", "disable"):
                if args.service_args[0] == "enable" and any(name in ("browser", "all") for name in args.service_args[1:]):
                    from .local_browser import install as install_browser
                    install_browser(root)
                integration.prepare(root, port=port)
                integration.sync_mcp(root)
                from .desktop import sync_services
                sync_services(root)
            return result or 0
        elif args.command == "desktop":
            from .desktop import prepare, launch, activate
            if args.action == "launch":
                integration.ensure_gateway(root, port)
                print(json.dumps(launch(root, port), ensure_ascii=False, indent=2, default=str))
                return 0
            print(json.dumps((activate if args.action == "activate" else prepare)(root, port), ensure_ascii=False, indent=2, default=str))
        return 0
    except (ValueError, RuntimeError, OSError, UpstreamError) as exc:
        print("Error:", str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
