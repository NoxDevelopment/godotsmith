#!/usr/bin/env python3
"""Godotsmith Bridge Client — talk to a running Godot game.

Usage:
  python bridge_client.py ping
  python bridge_client.py tree [--full]
  python bridge_client.py screenshot [--path user://shot.png]
  python bridge_client.py info <node_path>
  python bridge_client.py set <node_path> <property> <json_value>
  python bridge_client.py call <node_path> <method> [json_args...]
  python bridge_client.py input <action> [--release]
  python bridge_client.py mouse <x> <y> [--button 1] [--release]
  python bridge_client.py fps
  python bridge_client.py errors
  python bridge_client.py eval "<gdscript expr>"
  python bridge_client.py ui-map                -- dump every visible Control
  python bridge_client.py audit                 -- spatial scene audit
  python bridge_client.py quit

Requires the godotsmith_bridge addon autoloaded in the running Godot project.
Listens on 127.0.0.1:6007.
"""
import argparse
import json
import socket
import sys
from typing import Any

HOST = "127.0.0.1"
PORT = 6007
TIMEOUT = 5.0


def send(verb: str, **kwargs) -> dict[str, Any]:
    req = {"verb": verb, **kwargs}
    with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as sock:
        sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    line = data.split(b"\n", 1)[0].decode("utf-8")
    return json.loads(line)


def main():
    p = argparse.ArgumentParser(description="Godotsmith runtime bridge client")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping")
    t = sub.add_parser("tree"); t.add_argument("--full", action="store_true")
    s = sub.add_parser("screenshot"); s.add_argument("--path", default="user://bridge_shot.png")
    i = sub.add_parser("info"); i.add_argument("path")
    setp = sub.add_parser("set"); setp.add_argument("path"); setp.add_argument("property"); setp.add_argument("value")
    cm = sub.add_parser("call"); cm.add_argument("path"); cm.add_argument("method"); cm.add_argument("args", nargs="*")
    inp = sub.add_parser("input"); inp.add_argument("action"); inp.add_argument("--release", action="store_true")
    ms = sub.add_parser("mouse"); ms.add_argument("x", type=float); ms.add_argument("y", type=float)
    ms.add_argument("--button", type=int, default=1); ms.add_argument("--release", action="store_true")
    sub.add_parser("fps")
    sub.add_parser("errors")
    ev = sub.add_parser("eval"); ev.add_argument("expr")
    sub.add_parser("ui-map")
    sub.add_parser("audit")
    sub.add_parser("quit")

    args = p.parse_args()

    try:
        if args.cmd == "ping":            r = send("ping")
        elif args.cmd == "tree":          r = send("scene_tree", detail="full" if args.full else "brief")
        elif args.cmd == "screenshot":    r = send("screenshot", path=args.path)
        elif args.cmd == "info":          r = send("node_info", path=args.path)
        elif args.cmd == "set":           r = send("set_property", path=args.path, property=args.property, value=json.loads(args.value))
        elif args.cmd == "call":
            parsed_args = [json.loads(a) for a in args.args]
            r = send("call_method", path=args.path, method=args.method, args=parsed_args)
        elif args.cmd == "input":         r = send("input", action=args.action, pressed=not args.release)
        elif args.cmd == "mouse":         r = send("mouse", pos=[args.x, args.y], button=args.button, pressed=not args.release)
        elif args.cmd == "fps":           r = send("fps")
        elif args.cmd == "errors":        r = send("errors")
        elif args.cmd == "eval":          r = send("eval", expr=args.expr)
        elif args.cmd == "ui-map":        r = send("ui_map")
        elif args.cmd == "audit":         r = send("spatial_audit")
        elif args.cmd == "quit":          r = send("quit")
    except (ConnectionRefusedError, socket.timeout) as e:
        print(json.dumps({"ok": False, "error": f"bridge not reachable on {HOST}:{PORT}: {e}"}))
        sys.exit(1)

    print(json.dumps(r, indent=2))
    sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
