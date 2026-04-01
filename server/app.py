"""Godotsmith IDE — Web-based game development IDE with AI orchestration.

Supports: Godot 4.6, Unity, Unreal Engine
Asset pipeline: ComfyUI (local), Gemini (cloud), procedural audio
AI: Claude Code with auto-approve

Run: python server/app.py
Access: http://localhost:7777 (or any device on LAN)
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import uvicorn
import requests

# --- Paths ---
SERVER_DIR = Path(__file__).parent
GODOTSMITH_DIR = SERVER_DIR.parent
CONFIG_FILE = GODOTSMITH_DIR / "launcher_config.json"
PROJECTS_FILE = GODOTSMITH_DIR / "projects.json"
SKILLS_DIR = GODOTSMITH_DIR / ".claude" / "skills"
GAME_CLAUDE_MD = GODOTSMITH_DIR / "game_claude.md"
TEMPLATES_DIR = GODOTSMITH_DIR / "game_templates"

DEFAULT_CONFIG = {
    "projects_root": "C:/code/ai",
    "comfyui_path": "C:/code/ai/localllm_poc/ComfyUI",
    "comfyui_port": 8188,
    "godot_exe": "godot",
    "unity_exe": "",
    "unreal_exe": "",
    "kokoro_port": 8880,
    "auto_approve": True,
    "claude_model": "opus",
    "host": "0.0.0.0",
    "port": 7777,
}

# --- Config ---
def load_config() -> dict:
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

# --- Projects ---
def load_projects() -> list[dict]:
    if PROJECTS_FILE.exists():
        return json.loads(PROJECTS_FILE.read_text())
    return []

def save_projects(projects: list[dict]):
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))

def scan_projects(root: str, force_rescan: bool = False) -> list[dict]:
    """Auto-discover game projects. Filters to only show projects under root."""
    projects = load_projects()

    # Filter out projects not under the current root
    root_norm = str(Path(root).resolve()).replace("\\", "/").lower()
    projects = [p for p in projects if p["path"].replace("\\", "/").lower().startswith(root_norm)]

    if force_rescan:
        # Clear and rebuild from disk
        projects = []

    existing_paths = {p["path"] for p in projects}
    root_path = Path(root)
    if not root_path.exists():
        return projects

    for d in root_path.iterdir():
        if not d.is_dir() or str(d) in existing_paths:
            continue
        has_skills = (d / ".claude" / "skills").exists()
        has_godot = (d / "project.godot").exists()
        has_unity = (d / "Assets").exists() and (d / "ProjectSettings").exists()
        has_unreal = (d / "Source").exists() and any(d.glob("*.uproject"))

        if not (has_skills or has_godot or has_unity or has_unreal):
            continue

        name = d.name.replace("-", " ").replace("_", " ").title()
        engine = "godot"
        if has_unity:
            engine = "unity"
        elif has_unreal:
            engine = "unreal"

        # Try to read name from project file
        pf = d / "project.godot"
        if pf.exists():
            for line in pf.read_text(errors="ignore").splitlines():
                if line.startswith("config/name="):
                    name = line.split("=", 1)[1].strip().strip('"')
                    break

        projects.append({
            "name": name, "path": str(d), "engine": engine,
            "genre": "", "concept": "",
            "created": datetime.fromtimestamp(d.stat().st_ctime).isoformat(),
            "last_opened": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
        })

    save_projects(projects)
    return projects

# --- Service checks ---
def check_service(port: int) -> bool:
    try:
        r = requests.get(f"http://localhost:{port}/system_stats", timeout=2)
        return r.status_code == 200
    except Exception:
        try:
            r = requests.get(f"http://localhost:{port}/", timeout=2)
            return True
        except Exception:
            return False

# --- Game Templates ---
GAME_TEMPLATES = {
    "platformer_2d": {
        "name": "2D Platformer",
        "description": "Side-scrolling platformer with jump physics, enemies, and collectibles",
        "engines": ["godot", "unity", "unreal"],
        "genre": "2D Platformer",
        "mechanics": "- Side-scrolling movement with momentum\n- Jump with variable height\n- Enemy stomping\n- Collectible items\n- Level progression",
        "style": "16-bit pixel art",
    },
    "topdown_rpg": {
        "name": "Top-Down RPG",
        "description": "Classic top-down RPG with turn-based combat, NPCs, and quests",
        "engines": ["godot", "unity"],
        "genre": "Top-Down RPG",
        "mechanics": "- Top-down overworld movement\n- Turn-based combat system\n- NPC dialogue\n- Inventory system\n- Quest tracking\n- Experience and leveling",
        "style": "16-bit pixel art, SNES era",
    },
    "arcade_shooter": {
        "name": "Arcade Shooter",
        "description": "Fast-paced top-down or side-scrolling shooter with waves of enemies",
        "engines": ["godot", "unity", "unreal"],
        "genre": "Arcade Shooter",
        "mechanics": "- Ship/character movement\n- Shooting with multiple weapon types\n- Enemy waves with patterns\n- Power-ups and upgrades\n- Boss fights\n- Score system",
        "style": "Neon retro pixel art",
    },
    "puzzle": {
        "name": "Puzzle Game",
        "description": "Logic-based puzzle game with grid mechanics",
        "engines": ["godot", "unity"],
        "genre": "Puzzle",
        "mechanics": "- Grid-based gameplay\n- Match/swap/slide mechanics\n- Increasing difficulty\n- Star rating per level\n- Hint system",
        "style": "Clean minimalist pixel art",
    },
    "survival": {
        "name": "Survival Crafting",
        "description": "Gather resources, craft tools, build shelter, survive",
        "engines": ["godot", "unity", "unreal"],
        "genre": "Survival",
        "mechanics": "- Resource gathering\n- Crafting system\n- Day/night cycle\n- Hunger/thirst/health\n- Base building\n- Enemy threats at night",
        "style": "Stylized low-poly or pixel art",
    },
    "roguelike": {
        "name": "Roguelike",
        "description": "Procedurally generated dungeon crawler with permadeath",
        "engines": ["godot", "unity"],
        "genre": "Roguelike",
        "mechanics": "- Procedural dungeon generation\n- Turn-based or real-time combat\n- Permadeath with meta-progression\n- Random item/weapon drops\n- Multiple character classes",
        "style": "Dark pixel art",
    },
    "racing": {
        "name": "Racing Game",
        "description": "Top-down or 3D racing with drifting and power-ups",
        "engines": ["godot", "unity", "unreal"],
        "genre": "Racing",
        "mechanics": "- Vehicle physics with drift\n- Multiple tracks\n- Power-ups/weapons\n- AI opponents\n- Time trials and championships",
        "style": "Stylized 3D or pixel art",
    },
    "tower_defense": {
        "name": "Tower Defense",
        "description": "Place towers to defend against waves of enemies",
        "engines": ["godot", "unity"],
        "genre": "Tower Defense",
        "mechanics": "- Grid-based tower placement\n- Multiple tower types\n- Enemy waves with paths\n- Upgrade system\n- Economy management\n- Boss waves",
        "style": "Colorful pixel art",
    },
}

# --- FastAPI App ---
app = FastAPI(title="Godotsmith IDE")
app.mount("/static", StaticFiles(directory=str(SERVER_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(SERVER_DIR / "templates"))

# Active processes
active_processes: dict = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --- API: Projects ---

@app.get("/api/projects")
async def get_projects():
    cfg = load_config()
    projects = scan_projects(cfg["projects_root"])
    return projects


@app.get("/api/project/{path:path}")
async def get_project_detail(path: str):
    """Get full project details: design doc, plan status, assets."""
    p = Path(path)
    detail = {"path": str(p), "exists": p.exists()}

    # Game prompt / design doc
    for doc_name in ["GAME_PROMPT.md", "PLAN.md", "STRUCTURE.md", "ASSETS.md", "MEMORY.md"]:
        doc_path = p / doc_name
        if doc_path.exists():
            detail[doc_name.replace(".", "_").lower()] = doc_path.read_text(errors="ignore")

    # Parse PLAN.md for task statuses
    plan_path = p / "PLAN.md"
    if plan_path.exists():
        tasks = []
        current_task = None
        for line in plan_path.read_text(errors="ignore").splitlines():
            if line.startswith("## ") and ". " in line:
                if current_task:
                    tasks.append(current_task)
                current_task = {"title": line[3:], "status": "pending", "details": []}
            elif current_task and "**Status:**" in line:
                status = line.split("**Status:**")[1].strip()
                current_task["status"] = status
            elif current_task:
                current_task["details"].append(line)
        if current_task:
            tasks.append(current_task)
        detail["tasks"] = tasks

    # List assets
    assets = {"images": [], "audio": [], "models": []}
    img_dir = p / "assets" / "img"
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.png")):
            assets["images"].append({"name": f.name, "path": str(f), "size": f.stat().st_size})
    audio_dir = p / "assets" / "audio"
    if audio_dir.exists():
        for f in sorted(audio_dir.iterdir()):
            if f.suffix in (".wav", ".mp3", ".ogg"):
                assets["audio"].append({"name": f.name, "path": str(f), "size": f.stat().st_size})
    glb_dir = p / "assets" / "glb"
    if glb_dir.exists():
        for f in sorted(glb_dir.glob("*.glb")):
            assets["models"].append({"name": f.name, "path": str(f), "size": f.stat().st_size})
    detail["assets"] = assets

    # Screenshots
    ss_dir = p / "screenshots"
    if ss_dir.exists():
        screenshots = []
        for f in sorted(ss_dir.rglob("*.png")):
            screenshots.append({"name": f.name, "path": str(f), "folder": f.parent.name})
        detail["screenshots"] = screenshots

    return detail


@app.get("/api/asset/{path:path}")
async def serve_asset(path: str):
    """Serve an asset file (image, audio, etc.)."""
    p = Path(path)
    if p.exists():
        return FileResponse(p)
    return JSONResponse({"error": "Not found"}, status_code=404)


# --- API: Create Project ---

@app.post("/api/projects/create")
async def create_project(request: Request):
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Name required"}, status_code=400)

    cfg = load_config()
    engine = data.get("engine", "godot")
    folder = name.lower().replace(" ", "-")
    for ch in "!@#$%^&*()+=[]{}|\\:;<>,?/~`'\"":
        folder = folder.replace(ch, "")
    target = Path(cfg["projects_root"]) / folder

    # Publish skills
    publish_project(target, engine, cfg)

    # Build prompt
    genre = data.get("genre", "")
    prompt_parts = [f'Make a {genre} game called "{name}".']
    for key in ["concept", "style", "mechanics", "player", "goal", "enemies", "special"]:
        val = data.get(key, "").strip()
        if val:
            prompt_parts.append(f"\n**{key.capitalize()}:** {val}")
    prompt_parts.append("\n**Budget:** local only (use ComfyUI)")
    prompt = "\n".join(prompt_parts)
    (target / "GAME_PROMPT.md").write_text(prompt)

    # Register
    projects = load_projects()
    projects.insert(0, {
        "name": name, "path": str(target), "engine": engine,
        "genre": genre, "concept": data.get("concept", ""),
        "created": datetime.now().isoformat(),
        "last_opened": datetime.now().isoformat(),
    })
    save_projects(projects)

    return {"ok": True, "path": str(target), "prompt": prompt}


def publish_project(target: Path, engine: str, cfg: dict):
    """Copy skills and set up project for the given engine."""
    target.mkdir(parents=True, exist_ok=True)

    if engine == "godot":
        skills_target = target / ".claude" / "skills"
        skills_target.mkdir(parents=True, exist_ok=True)
        for skill_name in ["godotsmith", "godot-task"]:
            src = SKILLS_DIR / skill_name
            dst = skills_target / skill_name
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
        if GAME_CLAUDE_MD.exists():
            shutil.copy2(GAME_CLAUDE_MD, target / "CLAUDE.md")

    # .gitignore
    gi = target / ".gitignore"
    if not gi.exists():
        gi.write_text(".claude\nCLAUDE.md\nassets\nscreenshots\n.godot\n*.import\nLibrary\nTemp\nObj\n")

    # Git init
    if not (target / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(target), capture_output=True)

    # Auto-approve settings
    if cfg.get("auto_approve", False) and engine == "godot":
        settings_dir = target / ".claude"
        settings_dir.mkdir(exist_ok=True)
        (settings_dir / "settings.json").write_text(json.dumps({
            "permissions": {"allow": [
                "Bash(*)", "Read(*)", "Write(*)", "Edit(*)",
                "Glob(*)", "Grep(*)", "WebFetch(*)", "WebSearch(*)",
            ]}
        }, indent=2))


# --- API: Services ---

@app.get("/api/services")
async def get_services():
    cfg = load_config()
    services = {
        "comfyui": {
            "online": check_service(cfg["comfyui_port"]),
            "port": cfg["comfyui_port"],
            "path": cfg["comfyui_path"],
        },
        "kokoro": {
            "online": check_service(cfg["kokoro_port"]),
            "port": cfg["kokoro_port"],
        },
        "godot": {"version": "", "available": False},
        "unity": {"available": bool(cfg.get("unity_exe"))},
        "unreal": {"available": bool(cfg.get("unreal_exe"))},
    }
    try:
        r = subprocess.run([cfg["godot_exe"], "--version"], capture_output=True, text=True, timeout=5)
        services["godot"]["version"] = r.stdout.strip().split("\n")[0]
        services["godot"]["available"] = True
    except Exception:
        pass
    return services


@app.post("/api/services/{name}/start")
async def start_service(name: str):
    cfg = load_config()
    if name == "comfyui":
        main_py = Path(cfg["comfyui_path"]) / "main.py"
        if not main_py.exists():
            return JSONResponse({"error": "ComfyUI not found"}, status_code=404)
        proc = subprocess.Popen(
            [sys.executable, str(main_py), "--listen", "0.0.0.0", "--port", str(cfg["comfyui_port"])],
            cwd=cfg["comfyui_path"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        active_processes["comfyui"] = proc
        return {"ok": True, "pid": proc.pid}
    return JSONResponse({"error": "Unknown service"}, status_code=400)


@app.post("/api/services/{name}/stop")
async def stop_service(name: str):
    if name in active_processes:
        active_processes[name].terminate()
        del active_processes[name]
        return {"ok": True}
    return JSONResponse({"error": "Not managed by us"}, status_code=400)


# --- API: Asset Regeneration ---

# --- API: Project Actions ---

@app.post("/api/project/capture")
async def capture_screenshot(request: Request):
    """Capture a screenshot from the running Godot project."""
    data = await request.json()
    path = data.get("path", "")
    cfg = load_config()
    pf = Path(path) / "project.godot"
    if not pf.exists():
        return JSONResponse({"error": "No project.godot"}, status_code=400)

    ss_dir = Path(path) / "screenshots" / "ide_capture"
    ss_dir.mkdir(parents=True, exist_ok=True)
    (Path(path) / "screenshots" / ".gdignore").touch()

    result = subprocess.run(
        [cfg["godot_exe"], "--rendering-method", "forward_plus",
         "--write-movie", str(ss_dir / "frame.png"),
         "--fixed-fps", "2", "--quit-after", "4", "--path", path],
        capture_output=True, text=True, timeout=30,
    )
    # Find the latest frame
    frames = sorted(ss_dir.glob("frame*.png"))
    if frames:
        return {"ok": True, "screenshot": str(frames[-1])}
    return {"ok": False, "error": result.stderr[:500] if result.stderr else "No frames captured"}


@app.get("/api/project/git-log/{path:path}")
async def get_git_log(path: str):
    """Get recent git history for a project."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--no-decorate", "-20"],
            cwd=path, capture_output=True, text=True, timeout=10,
        )
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        commits = []
        for line in lines:
            parts = line.split(" ", 1)
            commits.append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})
        return {"commits": commits}
    except Exception as e:
        return {"commits": [], "error": str(e)}


@app.get("/api/project/errors/{path:path}")
async def check_project_errors(path: str):
    """Run Godot headless to check for compile errors."""
    cfg = load_config()
    pf = Path(path) / "project.godot"
    if not pf.exists():
        return {"errors": [], "status": "no_project"}
    try:
        result = subprocess.run(
            [cfg["godot_exe"], "--headless", "--quit", "--path", path],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        errors = []
        for line in output.splitlines():
            line_lower = line.lower()
            if "error" in line_lower and ("parse" in line_lower or "script" in line_lower or "compile" in line_lower):
                if "rid" not in line_lower and "leaked" not in line_lower:
                    errors.append(line.strip())
        return {"errors": errors, "status": "clean" if not errors else "errors"}
    except subprocess.TimeoutExpired:
        return {"errors": ["Godot timed out"], "status": "timeout"}
    except Exception as e:
        return {"errors": [str(e)], "status": "error"}


@app.post("/api/project/build-scenes")
async def build_scenes(request: Request):
    """Run scene builder scripts."""
    data = await request.json()
    path = data.get("path", "")
    cfg = load_config()
    builder = Path(path) / "scenes" / "build_all.gd"
    if not builder.exists():
        return {"ok": False, "error": "No scenes/build_all.gd found"}
    try:
        result = subprocess.run(
            [cfg["godot_exe"], "--headless", "--script", str(builder), "--path", path],
            capture_output=True, text=True, timeout=60,
        )
        return {"ok": True, "output": result.stdout, "errors": result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/project/update-task")
async def update_plan_task(request: Request):
    """Update a task status in PLAN.md."""
    data = await request.json()
    path = data.get("path", "")
    task_title = data.get("title", "")
    new_status = data.get("status", "")
    plan_path = Path(path) / "PLAN.md"
    if not plan_path.exists():
        return {"ok": False, "error": "No PLAN.md"}

    content = plan_path.read_text()
    # Find the task and update status
    lines = content.splitlines()
    updated = False
    for i, line in enumerate(lines):
        if task_title and task_title in line and line.startswith("## "):
            # Find the status line after this
            for j in range(i + 1, min(i + 10, len(lines))):
                if "**Status:**" in lines[j]:
                    lines[j] = f"- **Status:** {new_status}"
                    updated = True
                    break
            break
    if updated:
        plan_path.write_text("\n".join(lines))
    return {"ok": updated}


@app.post("/api/regenerate-asset")
async def regenerate_asset(request: Request):
    data = await request.json()
    project_path = data.get("project_path", "")
    asset_type = data.get("type", "image")  # image, audio, sprite
    prompt = data.get("prompt", "")
    output_name = data.get("output_name", "")

    if not project_path or not prompt or not output_name:
        return JSONResponse({"error": "Missing fields"}, status_code=400)

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    output_path = Path(project_path) / "assets" / "img" / output_name

    if asset_type == "image":
        result = subprocess.run(
            [sys.executable, str(tools_dir / "asset_gen.py"), "image",
             "--prompt", prompt, "--backend", "comfyui", "-o", str(output_path)],
            capture_output=True, text=True, cwd=project_path,
        )
        return {"ok": result.returncode == 0, "output": result.stdout, "error": result.stderr}
    elif asset_type == "audio":
        output_path = Path(project_path) / "assets" / "audio" / output_name
        sfx_type = data.get("sfx_type", "hit")
        result = subprocess.run(
            [sys.executable, str(tools_dir / "audio_gen.py"), "sfx",
             "--type", sfx_type, "-o", str(output_path)],
            capture_output=True, text=True, cwd=project_path,
        )
        return {"ok": result.returncode == 0, "output": result.stdout, "error": result.stderr}

    return JSONResponse({"error": "Unknown type"}, status_code=400)


from asset_catalog import get_catalog, search_catalog

# --- API: Curated Asset Catalog ---

@app.get("/api/catalog")
async def catalog_all():
    return get_catalog()

@app.get("/api/catalog/search")
async def catalog_search(q: str = "", category: str = ""):
    return search_catalog(query=q, category=category)

@app.post("/api/catalog/install")
async def catalog_install(request: Request):
    """Download and install a curated catalog asset into a project."""
    data = await request.json()
    asset_id = data.get("asset_id", "")
    project_path = data.get("project_path", "")

    catalog = get_catalog()
    asset = None
    for a in catalog["assets"]:
        if a["id"] == asset_id:
            asset = a
            break
    if not asset:
        return JSONResponse({"error": "Asset not found"}, status_code=404)

    download_url = asset.get("download_url", "")
    if not download_url:
        return JSONResponse({"error": "No download URL"}, status_code=400)

    # For GitHub zips — download and extract
    if "github.com" in download_url and download_url.endswith(".zip"):
        import tempfile, zipfile
        try:
            r = requests.get(download_url, timeout=60, stream=True)
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                for chunk in r.iter_content(8192):
                    tmp.write(chunk)
                tmp_path = tmp.name

            target = Path(project_path) / "addons" / asset["id"].replace("-", "_")
            target.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(tmp_path) as zf:
                names = zf.namelist()
                prefix = names[0].split("/")[0] + "/" if names and "/" in names[0] else ""
                count = 0
                for member in names:
                    if member.endswith("/"):
                        continue
                    rel = member[len(prefix):] if member.startswith(prefix) else member
                    if not rel:
                        continue
                    out = target / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(out, "wb") as dst:
                        dst.write(src.read())
                    count += 1

            os.unlink(tmp_path)
            return {"ok": True, "asset": asset["name"], "installed_to": str(target), "files": count}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # For Kenney zips — direct download
    if "kenney.nl" in download_url and download_url.endswith(".zip"):
        import tempfile, zipfile
        try:
            r = requests.get(download_url, timeout=60, stream=True)
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                for chunk in r.iter_content(8192):
                    tmp.write(chunk)
                tmp_path = tmp.name

            target = Path(project_path) / "assets" / "imported" / asset["id"].replace("-", "_")
            target.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(tmp_path) as zf:
                zf.extractall(target)

            os.unlink(tmp_path)
            count = sum(1 for _ in target.rglob("*") if _.is_file())
            return {"ok": True, "asset": asset["name"], "installed_to": str(target), "files": count}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # For itch.io — can't auto-download, provide URL
    return {"ok": False, "manual": True, "url": download_url,
            "message": f"Open {download_url} in your browser to download (itch.io requires manual download)"}


# --- API: Templates (built-in) ---

@app.get("/api/templates")
async def get_templates():
    return GAME_TEMPLATES


# --- API: Godot Asset Library Browser ---

ASSET_LIB_API = "https://godotengine.org/asset-library/api"

@app.get("/api/asset-library/search")
async def search_asset_library(
    q: str = "",
    category: int = 0,
    godot_version: str = "4.6",
    sort: str = "updated",
    page: int = 0,
    asset_type: str = "any",
):
    """Search the official Godot Asset Library."""
    params = {"sort": sort, "page": str(page)}
    if q:
        params["filter"] = q
    if category > 0:
        params["category"] = str(category)
    if godot_version:
        params["godot_version"] = godot_version
    if asset_type and asset_type != "any":
        params["type"] = asset_type
    try:
        r = requests.get(f"{ASSET_LIB_API}/asset", params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data
    except Exception as e:
        return {"error": str(e), "result": []}


@app.get("/api/asset-library/asset/{asset_id}")
async def get_asset_detail(asset_id: int):
    """Get full details of a single asset from the Godot Asset Library."""
    try:
        r = requests.get(f"{ASSET_LIB_API}/asset/{asset_id}", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/asset-library/categories")
async def get_asset_categories():
    """Get available categories."""
    try:
        r = requests.get(f"{ASSET_LIB_API}/configure", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/asset-library/install")
async def install_asset(request: Request):
    """Download and install an asset into a project."""
    data = await request.json()
    asset_id = data.get("asset_id")
    project_path = data.get("project_path", "")
    install_as = data.get("install_as", "addon")  # addon or template

    if not asset_id or not project_path:
        return JSONResponse({"error": "asset_id and project_path required"}, status_code=400)

    # Get asset details
    try:
        r = requests.get(f"{ASSET_LIB_API}/asset/{asset_id}", timeout=10)
        r.raise_for_status()
        asset = r.json()
    except Exception as e:
        return JSONResponse({"error": f"Failed to get asset: {e}"}, status_code=500)

    download_url = asset.get("download_url", "")
    if not download_url:
        return JSONResponse({"error": "No download URL for this asset"}, status_code=400)

    # Download the zip
    import tempfile, zipfile
    try:
        r = requests.get(download_url, timeout=60, stream=True)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            for chunk in r.iter_content(8192):
                tmp.write(chunk)
            tmp_path = tmp.name

        # Extract to project
        target = Path(project_path)
        if install_as == "addon":
            extract_to = target / "addons" / asset.get("title", "asset").lower().replace(" ", "_")
        else:
            extract_to = target

        extract_to.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(tmp_path) as zf:
            # GitHub zips have a root folder — strip it
            names = zf.namelist()
            prefix = ""
            if names and "/" in names[0]:
                prefix = names[0].split("/")[0] + "/"

            for member in names:
                if member.endswith("/"):
                    continue
                # Strip the GitHub root folder prefix
                rel_path = member[len(prefix):] if member.startswith(prefix) else member
                if not rel_path:
                    continue
                out_path = extract_to / rel_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(out_path, "wb") as dst:
                    dst.write(src.read())

        os.unlink(tmp_path)

        return {
            "ok": True,
            "asset": asset.get("title", ""),
            "installed_to": str(extract_to),
            "files": len([n for n in names if not n.endswith("/")]),
        }

    except Exception as e:
        return JSONResponse({"error": f"Install failed: {e}"}, status_code=500)


# --- API: Settings ---

@app.get("/api/settings")
async def get_settings():
    return load_config()

@app.post("/api/settings")
async def update_settings(request: Request):
    data = await request.json()
    cfg = load_config()
    old_root = cfg.get("projects_root", "")
    cfg.update(data)
    save_config(cfg)
    # If projects root changed, rescan
    if cfg.get("projects_root", "") != old_root:
        scan_projects(cfg["projects_root"], force_rescan=True)
    return {"ok": True}


# --- API: Launch ---

@app.post("/api/launch/{action}")
async def launch_action(action: str, request: Request):
    data = await request.json()
    path = data.get("path", "")
    cfg = load_config()

    if action == "claude":
        cmd = ["cmd", "/c", "start", "cmd", "/k", f"cd /d {path} && claude"]
        if cfg.get("auto_approve"):
            cmd = ["cmd", "/c", "start", "cmd", "/k",
                   f"cd /d {path} && claude --dangerously-skip-permissions"]
        subprocess.Popen(cmd, shell=False)
        return {"ok": True}

    elif action == "godot-editor":
        subprocess.Popen([cfg["godot_exe"], "--editor", "--path", path])
        return {"ok": True}

    elif action == "godot-run":
        subprocess.Popen([cfg["godot_exe"], "--path", path])
        return {"ok": True}

    elif action == "folder":
        os.startfile(path)
        return {"ok": True}

    return JSONResponse({"error": "Unknown action"}, status_code=400)


# --- WebSocket: Live Console ---

@app.websocket("/ws/console")
async def console_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        # Receive initial config (project path, command)
        init = await websocket.receive_json()
        path = init.get("path", ".")
        command = init.get("command", "claude")
        cfg = load_config()

        cmd = [command]
        if command == "claude" and cfg.get("auto_approve"):
            cmd.append("--dangerously-skip-permissions")

        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def read_output():
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await websocket.send_json({"type": "output", "data": line.decode(errors="replace")})
            await websocket.send_json({"type": "exit", "code": proc.returncode})

        output_task = asyncio.create_task(read_output())

        # Read input from websocket
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "input":
                proc.stdin.write((msg["data"] + "\n").encode())
                await proc.stdin.drain()
            elif msg.get("type") == "stop":
                proc.terminate()
                break

        output_task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except Exception:
            pass


# --- Helpers ---

def _get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


# --- Run ---

if __name__ == "__main__":
    cfg = load_config()
    save_config(cfg)
    print(f"\n  Godotsmith IDE")
    print(f"  http://localhost:{cfg['port']}")
    print(f"  http://{_get_local_ip()}:{cfg['port']}  (LAN)\n")
    uvicorn.run(app, host=cfg["host"], port=cfg["port"])
