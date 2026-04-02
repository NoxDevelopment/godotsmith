#!/usr/bin/env python3
"""Freesound.org client — search and download 500K+ free CC sound effects.

Requires FREESOUND_API_KEY env var. Get one free at: https://freesound.org/apiv2/apply/

Subcommands:
  search     Search for sounds by query
  download   Download a sound preview (MP3) by ID
  batch      Search and download top N results

Output: JSON to stdout.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

API_BASE = "https://freesound.org/apiv2"


def get_api_key() -> str:
    key = os.environ.get("FREESOUND_API_KEY", "")
    if not key:
        # Check config file
        config_file = Path(__file__).parent.parent.parent.parent.parent / "launcher_config.json"
        if config_file.exists():
            cfg = json.loads(config_file.read_text())
            key = cfg.get("freesound_api_key", "")
    return key


def search_sounds(query: str, filter_str: str = "", page_size: int = 15, page: int = 1) -> dict:
    """Search Freesound for sounds matching query."""
    key = get_api_key()
    if not key:
        return {"error": "No FREESOUND_API_KEY set. Get one at https://freesound.org/apiv2/apply/"}

    params = {
        "query": query,
        "token": key,
        "fields": "id,name,description,tags,duration,avg_rating,num_ratings,previews,license,username",
        "page_size": page_size,
        "page": page,
    }
    if filter_str:
        params["filter"] = filter_str

    try:
        r = requests.get(f"{API_BASE}/search/text/", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_sound(sound_id: int) -> dict:
    """Get full details of a specific sound."""
    key = get_api_key()
    if not key:
        return {"error": "No FREESOUND_API_KEY"}
    try:
        r = requests.get(f"{API_BASE}/sounds/{sound_id}/", params={
            "token": key,
            "fields": "id,name,description,tags,duration,avg_rating,num_ratings,previews,license,username,filesize,samplerate,bitrate,channels,type",
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def download_preview(sound_id: int, output_path: Path, quality: str = "hq") -> bool:
    """Download the MP3 preview of a sound (no OAuth needed, just token)."""
    key = get_api_key()
    if not key:
        return False

    # First get the sound info to find preview URL
    info = get_sound(sound_id)
    if "error" in info:
        return False

    previews = info.get("previews", {})
    url = previews.get(f"preview-{quality}-mp3") or previews.get("preview-lq-mp3") or previews.get("preview-hq-ogg")
    if not url:
        return False

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(r.content)
        return True
    except Exception:
        return False


def cmd_search(args):
    results = search_sounds(args.query, args.filter, args.limit, args.page)
    if "error" in results:
        print(json.dumps(results))
        sys.exit(1)

    sounds = results.get("results", [])
    output = {
        "count": results.get("count", 0),
        "sounds": [{
            "id": s["id"],
            "name": s["name"],
            "description": s.get("description", "")[:200],
            "duration": round(s.get("duration", 0), 1),
            "rating": s.get("avg_rating", 0),
            "tags": s.get("tags", [])[:8],
            "license": s.get("license", ""),
            "author": s.get("username", ""),
            "preview_url": s.get("previews", {}).get("preview-hq-mp3", ""),
        } for s in sounds],
    }
    print(json.dumps(output))


def cmd_download(args):
    output = Path(args.output)
    print(f"Downloading sound {args.id}...", file=sys.stderr)
    if download_preview(args.id, output, args.quality):
        print(json.dumps({"ok": True, "path": str(output), "sound_id": args.id}))
    else:
        print(json.dumps({"ok": False, "error": "Download failed"}))
        sys.exit(1)


def cmd_batch(args):
    results = search_sounds(args.query, args.filter, args.limit)
    if "error" in results:
        print(json.dumps(results))
        sys.exit(1)

    sounds = results.get("results", [])
    output_dir = Path(args.output_dir)
    downloaded = []

    for s in sounds[:args.limit]:
        name = s["name"].replace(" ", "_").replace("/", "_")[:40]
        out = output_dir / f"{name}_{s['id']}.mp3"
        print(f"  Downloading: {s['name']}...", file=sys.stderr)
        if download_preview(s["id"], out):
            downloaded.append({"name": s["name"], "id": s["id"], "path": str(out)})

    print(json.dumps({"ok": True, "downloaded": len(downloaded), "files": downloaded}))


def main():
    parser = argparse.ArgumentParser(description="Freesound.org — search and download free sound effects")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="Search for sounds")
    p.add_argument("query", help="Search query (e.g., 'sword clash')")
    p.add_argument("--filter", default="", help="Filter string (e.g., 'duration:[0 TO 5]')")
    p.add_argument("--limit", type=int, default=15, help="Results per page")
    p.add_argument("--page", type=int, default=1)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("download", help="Download a sound preview")
    p.add_argument("id", type=int, help="Freesound sound ID")
    p.add_argument("-o", "--output", required=True, help="Output file path")
    p.add_argument("--quality", default="hq", choices=["hq", "lq"])
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("batch", help="Search and download top results")
    p.add_argument("query", help="Search query")
    p.add_argument("-o", "--output-dir", required=True, help="Output directory")
    p.add_argument("--filter", default="")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
