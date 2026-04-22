"""Godotsmith IDE — Web-based game development IDE with AI orchestration.

Supports: Godot 4.6, Unity, Unreal Engine
Asset pipeline: ComfyUI (local), Gemini (cloud), procedural audio
AI: Claude Code with auto-approve

Run: python server/app.py
Access: http://localhost:7777 (or any device on LAN)
"""

import asyncio
import json
import math
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
TUTORIALS_DIR = GODOTSMITH_DIR / "memory" / "tutorials"
TUTORIAL_JOBS: dict = {}  # job_id -> {"status": "running|done|error", "message": str, "path": str}

# Import pixel art toolkit functions for fast in-process calls (must be before STYLE_INTERVIEW_QUESTIONS)
sys.path.insert(0, str(SKILLS_DIR / "godotsmith" / "tools"))
try:
    from pixel_art_toolkit import (
        pixelize, reduce_palette, repair_pixel_grid, detect_pixel_size,
        make_spritesheet, extract_frames, save_gif, make_gif, PALETTES as PIXEL_PALETTES,
    )
    PIXEL_TOOLKIT_AVAILABLE = True
except ImportError:
    PIXEL_TOOLKIT_AVAILABLE = False
    PIXEL_PALETTES = {}

from asset_catalog import get_catalog, search_catalog
from pixel_art_presets import (
    PIXEL_STYLE_PRESETS, LORA_TRIGGERS, PIXEL_RESOLUTIONS, ZIT_PIXEL_LORAS,
    PIXEL_LORA_VARIANTS, ANIMATION_PRESETS, TILESET_PRESETS, EXTRA_PALETTES,
    UPSCALE_FACTORS, FRAME_DURATION_OPTIONS, OUTPUT_FORMATS,
)

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

    # Style profile
    style_path = p / STYLE_PROFILE_FILENAME
    if style_path.exists():
        detail["style_profile"] = json.loads(style_path.read_text(encoding="utf-8"))

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

    # List assets (fast — no stat calls unless needed)
    assets = {"images": [], "audio": [], "models": []}
    img_dir = p / "assets" / "img"
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.png")):
            assets["images"].append({"name": f.name, "path": str(f), "size": 0})
    audio_dir = p / "assets" / "audio"
    if audio_dir.exists():
        for f in sorted(audio_dir.iterdir()):
            if f.suffix in (".wav", ".mp3", ".ogg"):
                assets["audio"].append({"name": f.name, "path": str(f), "size": 0})
    glb_dir = p / "assets" / "glb"
    if glb_dir.exists():
        for f in sorted(glb_dir.glob("*.glb")):
            assets["models"].append({"name": f.name, "path": str(f), "size": 0})
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
        "style": data.get("style", ""),
        "created": datetime.now().isoformat(),
        "last_opened": datetime.now().isoformat(),
    })
    save_projects(projects)

    # Initialize style profile if style was provided
    style_text = data.get("style", "").strip()
    if style_text:
        profile = dict(DEFAULT_STYLE_PROFILE)
        profile["art_direction"] = style_text
        profile = _compile_style_profile(profile)
        save_style_profile(str(target), profile)

    return {"ok": True, "path": str(target), "prompt": prompt,
            "style_profile_initialized": bool(style_text)}


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
        "orpheus": {
            "online": check_service(5005),
            "port": 5005,
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


# =============================================================================
# Project Creative Identity — unified style profile for ALL content generation
#
# This is the creative bible for the project. Every generation endpoint — visual,
# audio, text, animation — reads from this profile to maintain consistency.
# =============================================================================

STYLE_PROFILE_FILENAME = "STYLE_PROFILE.json"

# The interview is organized into sections so the UI can present them as tabs/steps
STYLE_INTERVIEW_QUESTIONS = [
    # ---- Section 1: Visual Art ----
    {
        "id": "art_direction",
        "section": "visual",
        "question": "Describe the overall art style (e.g., '16-bit SNES RPG with warm colors', 'dark horror pixel art', 'clean minimalist vector').",
        "required": True,
        "field": "art_direction",
    },
    {
        "id": "era_console",
        "section": "visual",
        "question": "Which retro console/era should this evoke?",
        "required": False,
        "field": "era_console",
        "options": ["gameboy", "nes", "snes", "gba", "genesis", "c64", "modern_hd", "none"],
    },
    {
        "id": "palette",
        "section": "visual",
        "question": "Preferred color palette?",
        "required": False,
        "field": "palette",
        "options": list(PIXEL_PALETTES.keys()) if PIXEL_TOOLKIT_AVAILABLE else [],
    },
    {
        "id": "resolution",
        "section": "visual",
        "question": "Target sprite resolution in pixels?",
        "required": False,
        "field": "resolution",
        "options": PIXEL_RESOLUTIONS,
    },
    {
        "id": "perspective",
        "section": "visual",
        "question": "Primary camera perspective?",
        "required": False,
        "field": "perspective",
        "options": ["side-scroll", "top-down", "isometric", "first-person", "mixed"],
    },
    {
        "id": "color_mood",
        "section": "visual",
        "question": "Color mood / atmosphere?",
        "required": False,
        "field": "color_mood",
        "options": ["warm", "cool", "dark", "vibrant", "pastel", "neon", "muted", "monochrome"],
    },
    {
        "id": "outline_style",
        "section": "visual",
        "question": "Outline style for sprites?",
        "required": False,
        "field": "outline_style",
        "options": ["none", "thin-black", "thick-black", "colored", "sel-out", "anti-aliased"],
    },
    {
        "id": "shading_style",
        "section": "visual",
        "question": "Shading approach?",
        "required": False,
        "field": "shading_style",
        "options": ["flat", "cel-shaded", "dithered", "soft-gradient", "pillow-shaded", "hue-shifted"],
    },
    {
        "id": "reference_images",
        "section": "visual",
        "question": "Reference images — file paths or URLs that capture the visual style you want.",
        "required": False,
        "field": "reference_images",
    },
    {
        "id": "visual_notes",
        "section": "visual",
        "question": "Any other visual notes? (e.g., 'dithering preferred', 'sub-pixel animation', 'no anti-aliasing')",
        "required": False,
        "field": "visual_notes",
    },

    # ---- Section 2: Tone & Maturity ----
    {
        "id": "tone",
        "section": "tone",
        "question": "Overall tone of the game?",
        "required": True,
        "field": "tone",
        "options": [
            "lighthearted", "comedic", "satirical", "whimsical",
            "serious", "dramatic", "melancholic", "bittersweet",
            "dark", "gritty", "horror", "psychological",
            "epic", "heroic", "adventurous", "mysterious",
            "cozy", "wholesome", "nostalgic", "dreamlike",
        ],
    },
    {
        "id": "maturity",
        "section": "tone",
        "question": "Content maturity rating?",
        "required": True,
        "field": "maturity",
        "options": ["E-everyone", "E10-everyone10+", "T-teen", "M-mature"],
        "descriptions": {
            "E-everyone": "No violence, no scary content, no suggestive themes. Suitable for all ages.",
            "E10-everyone10+": "Mild fantasy violence, mild humor, minimal scary moments. Ages 10+.",
            "T-teen": "Moderate violence, blood, mild language, suggestive themes, some horror elements. Ages 13+.",
            "M-mature": "Intense violence, gore, strong language, mature themes, horror. Ages 17+.",
        },
    },
    {
        "id": "humor_level",
        "section": "tone",
        "question": "How much humor?",
        "required": False,
        "field": "humor_level",
        "options": ["none", "subtle", "moderate", "heavy", "parody"],
    },
    {
        "id": "humor_style",
        "section": "tone",
        "question": "If humor is present, what kind?",
        "required": False,
        "field": "humor_style",
        "options": ["wordplay", "slapstick", "dry-wit", "absurdist", "self-aware", "dark-humor", "puns", "pop-culture"],
    },
    {
        "id": "emotional_range",
        "section": "tone",
        "question": "What emotional range should the game cover?",
        "required": False,
        "field": "emotional_range",
        "options": ["narrow-upbeat", "narrow-dark", "moderate", "wide-full-spectrum"],
    },
    {
        "id": "themes",
        "section": "tone",
        "question": "Core themes the game explores? (comma-separated, e.g., 'friendship, loss, redemption, identity')",
        "required": False,
        "field": "themes",
    },
    {
        "id": "content_boundaries",
        "section": "tone",
        "question": "Hard content boundaries — things to NEVER include? (e.g., 'no real-world politics', 'no animal harm', 'no jump scares')",
        "required": False,
        "field": "content_boundaries",
    },

    # ---- Section 3: Writing & Dialogue ----
    {
        "id": "writing_style",
        "section": "writing",
        "question": "Writing style / voice?",
        "required": False,
        "field": "writing_style",
        "options": [
            "terse-minimal", "poetic-flowery", "punchy-action", "literary",
            "conversational-casual", "formal-archaic", "noir-hardboiled",
            "fairy-tale", "journalistic-dry", "stream-of-consciousness",
        ],
    },
    {
        "id": "vocabulary_level",
        "section": "writing",
        "question": "Vocabulary complexity?",
        "required": False,
        "field": "vocabulary_level",
        "options": ["simple-child", "accessible", "moderate", "advanced-literary"],
    },
    {
        "id": "dialogue_style",
        "section": "writing",
        "question": "How should characters speak?",
        "required": False,
        "field": "dialogue_style",
        "options": [
            "naturalistic", "stylized-dramatic", "quippy-snappy", "formal",
            "dialect-heavy", "minimalist-silent-protag", "fully-voiced-expressive",
        ],
    },
    {
        "id": "narrator_presence",
        "section": "writing",
        "question": "Is there a narrator? What kind?",
        "required": False,
        "field": "narrator_presence",
        "options": ["none", "omniscient-third", "unreliable", "first-person-character",
                    "second-person-you", "dry-observer", "dramatic-storyteller"],
    },
    {
        "id": "text_density",
        "section": "writing",
        "question": "How text-heavy is the game?",
        "required": False,
        "field": "text_density",
        "options": ["minimal-show-dont-tell", "moderate-balanced", "heavy-story-driven", "visual-novel-level"],
    },
    {
        "id": "naming_convention",
        "section": "writing",
        "question": "Naming style for characters, places, items? (e.g., 'Japanese RPG names', 'Anglo-fantasy', 'sci-fi codenames', 'pun-based', 'descriptive')",
        "required": False,
        "field": "naming_convention",
    },
    {
        "id": "ui_text_style",
        "section": "writing",
        "question": "UI/menu text tone? (e.g., 'functional-clean', 'in-character-diegetic', 'humorous', 'retro-arcade')",
        "required": False,
        "field": "ui_text_style",
        "options": ["functional-clean", "in-character-diegetic", "humorous", "retro-arcade", "minimalist-icons"],
    },
    {
        "id": "writing_references",
        "section": "writing",
        "question": "Games/shows/books whose writing style you want to channel? (e.g., 'Undertale', 'Disco Elysium', 'Zelda', 'Adventure Time')",
        "required": False,
        "field": "writing_references",
    },

    # ---- Section 4: Audio & Music ----
    {
        "id": "music_style",
        "section": "audio",
        "question": "Music style?",
        "required": False,
        "field": "music_style",
        "options": [
            "chiptune-8bit", "chiptune-16bit", "orchestral", "synth-wave",
            "lo-fi-chill", "ambient-atmospheric", "rock-metal", "jazz",
            "folk-acoustic", "electronic-edm", "classical", "silence-minimal",
        ],
    },
    {
        "id": "music_mood_default",
        "section": "audio",
        "question": "Default musical mood?",
        "required": False,
        "field": "music_mood_default",
        "options": ["epic", "sad", "tense", "happy", "dark", "neutral", "mysterious", "peaceful"],
    },
    {
        "id": "sfx_style",
        "section": "audio",
        "question": "Sound effects style?",
        "required": False,
        "field": "sfx_style",
        "options": ["retro-beeps", "crisp-modern", "crunchy-lofi", "realistic", "exaggerated-cartoon", "minimal"],
    },
    {
        "id": "voice_style",
        "section": "audio",
        "question": "Character voice approach?",
        "required": False,
        "field": "voice_style",
        "options": [
            "no-voice", "grunts-only", "gibberish-simlish", "partial-voiced",
            "fully-voiced", "text-to-speech-retro",
        ],
    },
    {
        "id": "voice_default_emotion",
        "section": "audio",
        "question": "Default voice emotion/delivery for TTS?",
        "required": False,
        "field": "voice_default_emotion",
        "options": ["cheerful", "friendly", "narrator", "excited", "sad", "terrified", "whispering", "neutral"],
    },
    {
        "id": "audio_notes",
        "section": "audio",
        "question": "Any other audio notes? (e.g., 'no voice acting', 'leitmotifs per character', 'dynamic music layers')",
        "required": False,
        "field": "audio_notes",
    },

    # ---- Section 5: World & Character Design ----
    {
        "id": "world_setting",
        "section": "world",
        "question": "World setting? (e.g., 'medieval fantasy', 'post-apocalyptic', 'modern day', 'alien planet', 'dreamscape')",
        "required": False,
        "field": "world_setting",
    },
    {
        "id": "world_tone",
        "section": "world",
        "question": "How does the world feel?",
        "required": False,
        "field": "world_tone",
        "options": ["lived-in-realistic", "stylized-exaggerated", "sparse-lonely",
                    "dense-bustling", "decaying-ruined", "magical-wonder", "oppressive-claustrophobic"],
    },
    {
        "id": "character_proportions",
        "section": "world",
        "question": "Character body proportions?",
        "required": False,
        "field": "character_proportions",
        "options": ["realistic", "chibi-2head", "chibi-3head", "stylized-4head",
                    "heroic-8head", "lanky-exaggerated", "squat-stout"],
    },
    {
        "id": "character_design_philosophy",
        "section": "world",
        "question": "Character design approach?",
        "required": False,
        "field": "character_design_philosophy",
        "options": ["silhouette-first", "color-coded", "uniform-with-variations",
                    "wildly-diverse", "minimalist", "detailed-ornate"],
    },
    {
        "id": "enemy_design",
        "section": "world",
        "question": "Enemy/monster visual approach?",
        "required": False,
        "field": "enemy_design",
        "options": ["cute-approachable", "menacing-scary", "abstract-geometric",
                    "corrupted-organic", "mechanical", "palette-swap-variants"],
    },
    {
        "id": "cultural_influences",
        "section": "world",
        "question": "Cultural or regional influences? (e.g., 'Japanese', 'Norse', 'Mesoamerican', 'steampunk Victorian', 'none specific')",
        "required": False,
        "field": "cultural_influences",
    },

    # ---- Section 6: UI / UX Feel ----
    {
        "id": "ui_style",
        "section": "ui",
        "question": "UI visual style?",
        "required": False,
        "field": "ui_style",
        "options": ["retro-bordered", "clean-modern", "ornate-fantasy", "diegetic-in-world",
                    "minimal-hud", "skeuomorphic", "flat-material"],
    },
    {
        "id": "font_style",
        "section": "ui",
        "question": "Font / text rendering style?",
        "required": False,
        "field": "font_style",
        "options": ["pixel-bitmap", "clean-sans", "handwritten", "serif-formal",
                    "monospace-terminal", "custom-thematic"],
    },
    {
        "id": "transition_style",
        "section": "ui",
        "question": "Scene transition style?",
        "required": False,
        "field": "transition_style",
        "options": ["hard-cut", "fade-to-black", "wipe", "pixel-dissolve",
                    "iris-circle", "slide", "custom-thematic"],
    },
    {
        "id": "screen_shake",
        "section": "ui",
        "question": "Juice / screen effects level?",
        "required": False,
        "field": "screen_shake",
        "options": ["none-clean", "subtle", "moderate", "heavy-juicy", "over-the-top"],
    },
]

DEFAULT_STYLE_PROFILE = {
    # -- Visual --
    "art_direction": "",
    "era_console": "",
    "palette": "",
    "resolution": 64,
    "perspective": "",
    "color_mood": "",
    "outline_style": "",
    "shading_style": "",
    "reference_images": [],
    "visual_notes": "",

    # -- Tone & Maturity --
    "tone": "",
    "maturity": "",
    "humor_level": "none",
    "humor_style": "",
    "emotional_range": "",
    "themes": "",
    "content_boundaries": "",

    # -- Writing & Dialogue --
    "writing_style": "",
    "vocabulary_level": "",
    "dialogue_style": "",
    "narrator_presence": "none",
    "text_density": "",
    "naming_convention": "",
    "ui_text_style": "",
    "writing_references": "",

    # -- Audio --
    "music_style": "",
    "music_mood_default": "",
    "sfx_style": "",
    "voice_style": "no-voice",
    "voice_default_emotion": "neutral",
    "audio_notes": "",

    # -- World & Characters --
    "world_setting": "",
    "world_tone": "",
    "character_proportions": "",
    "character_design_philosophy": "",
    "enemy_design": "",
    "cultural_influences": "",

    # -- UI/UX --
    "ui_style": "",
    "font_style": "",
    "transition_style": "",
    "screen_shake": "",

    # -- Derived/computed (filled by _compile_style_profile) --
    "prompt_prefix": "",
    "negative_extra": "",
    "suggested_lora": "sprite_64",
    "suggested_checkpoint": "",
    "suggested_style_preset": "",
    "writing_guide": "",
    "audio_guide": "",
    "character_guide": "",
}


def _get_style_profile_path(project_path: str) -> Path:
    return Path(project_path) / STYLE_PROFILE_FILENAME


def load_style_profile(project_path: str) -> dict:
    """Load the project's style profile, or return defaults."""
    p = _get_style_profile_path(project_path)
    if p.exists():
        return {**DEFAULT_STYLE_PROFILE, **json.loads(p.read_text(encoding="utf-8"))}
    return dict(DEFAULT_STYLE_PROFILE)


def save_style_profile(project_path: str, profile: dict):
    """Save the project's style profile."""
    p = _get_style_profile_path(project_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")


def _compile_style_profile(profile: dict) -> dict:
    """From user answers, derive prompt_prefix, writing_guide, audio_guide, etc.

    This is the central compilation step that turns human-readable style choices
    into machine-usable directives for every generation pipeline.
    """

    # ===== VISUAL PROMPT COMPILATION =====
    vis_parts = []
    neg_parts = []

    if profile.get("art_direction"):
        vis_parts.append(profile["art_direction"] + ",")

    # Era/console → visual prompt tags + defaults
    era = profile.get("era_console", "")
    era_map = {
        "gameboy": ("Game Boy style, 4 shades of green, DMG palette,", "colorful, modern", "sprite_32", "gameboy"),
        "nes": ("NES 8-bit style, limited palette, Famicom,", "modern, HD, 16-bit", "sprite_32", "nes"),
        "snes": ("SNES 16-bit style, rich colors, Super Nintendo,", "8-bit, modern, 3D", "sprite_64", "endesga32"),
        "gba": ("GBA style, vibrant handheld graphics,", "modern, HD, 3D", "sprite_64", "endesga32"),
        "genesis": ("Sega Genesis style, blast processing, 16-bit,", "8-bit, modern, 3D", "sprite_64", "endesga32"),
        "c64": ("Commodore 64 style, multicolor bitmap,", "modern, HD, many colors", "sprite_32", "c64"),
        "modern_hd": ("high detail pixel art, modern HD pixel art,", "low resolution, 8-bit", "sprite_64", "endesga64"),
    }
    if era in era_map:
        tag, neg, lora, pal = era_map[era]
        vis_parts.append(tag)
        neg_parts.append(neg)
        if not profile.get("suggested_lora"):
            profile["suggested_lora"] = lora
        if not profile.get("palette"):
            profile["palette"] = pal

    # Perspective
    persp = profile.get("perspective", "")
    persp_map = {
        "side-scroll": "side view, side-scrolling,",
        "top-down": "top-down view, overhead, birds eye,",
        "isometric": "isometric view, 3/4 perspective, dimetric,",
        "first-person": "first person view,",
    }
    if persp in persp_map:
        vis_parts.append(persp_map[persp])

    # Color mood
    mood = profile.get("color_mood", "")
    mood_map = {
        "warm": "warm colors, golden tones,",
        "cool": "cool colors, blue tones,",
        "dark": "dark atmosphere, low-key lighting, shadows,",
        "vibrant": "vibrant saturated colors, bold,",
        "pastel": "pastel colors, soft tones,",
        "neon": "neon glow, cyberpunk colors, electric,",
        "muted": "muted desaturated colors, earthy tones,",
        "monochrome": "monochrome, single color palette,",
    }
    if mood in mood_map:
        vis_parts.append(mood_map[mood])

    # Outline style
    outline = profile.get("outline_style", "")
    outline_map = {
        "thin-black": "thin black outlines,",
        "thick-black": "thick black outlines, bold linework,",
        "colored": "colored outlines, selective outlining,",
        "sel-out": "sel-out pixel art, darker edge pixels,",
        "none": "no outlines, clean pixel clusters,",
    }
    if outline in outline_map:
        vis_parts.append(outline_map[outline])

    # Shading
    shading = profile.get("shading_style", "")
    shading_map = {
        "flat": "flat shading, no gradients,",
        "cel-shaded": "cel-shaded, hard shadow edges,",
        "dithered": "dithered shading, ordered dither pattern,",
        "soft-gradient": "soft gradient shading,",
        "pillow-shaded": "pillow shading,",
        "hue-shifted": "hue-shifted shadows, colored shadows,",
    }
    if shading in shading_map:
        vis_parts.append(shading_map[shading])

    # Visual notes
    if profile.get("visual_notes"):
        vis_parts.append(profile["visual_notes"] + ",")

    profile["prompt_prefix"] = " ".join(vis_parts)
    profile["negative_extra"] = ", ".join(neg_parts)

    # Match to closest built-in style preset
    if profile.get("art_direction"):
        ad_lower = profile["art_direction"].lower()
        best_match = ""
        for key, preset in PIXEL_STYLE_PRESETS.items():
            if key in ad_lower or preset.get("name", "").lower() in ad_lower:
                best_match = key
                break
        profile["suggested_style_preset"] = best_match

    # ===== WRITING GUIDE COMPILATION =====
    writing_parts = []
    tone = profile.get("tone", "")
    maturity = profile.get("maturity", "")
    writing_style = profile.get("writing_style", "")
    vocab = profile.get("vocabulary_level", "")
    dialogue = profile.get("dialogue_style", "")
    narrator = profile.get("narrator_presence", "")
    humor = profile.get("humor_level", "")
    humor_style = profile.get("humor_style", "")
    themes = profile.get("themes", "")
    boundaries = profile.get("content_boundaries", "")
    naming = profile.get("naming_convention", "")
    ui_text = profile.get("ui_text_style", "")
    text_density = profile.get("text_density", "")
    writing_refs = profile.get("writing_references", "")

    if tone:
        writing_parts.append(f"TONE: {tone}.")
    if maturity:
        maturity_desc = {
            "E-everyone": "Keep all content suitable for children. No violence, scary content, or suggestive themes.",
            "E10-everyone10+": "Mild fantasy violence OK. Avoid anything scary, gory, or suggestive.",
            "T-teen": "Moderate violence and mild language OK. Can include some darker themes, mild horror, mild suggestive humor.",
            "M-mature": "Intense violence, strong language, and mature themes are acceptable. Horror, gore, and complex dark themes allowed.",
        }
        writing_parts.append(f"MATURITY: {maturity}. {maturity_desc.get(maturity, '')}")
    if writing_style:
        writing_parts.append(f"WRITING VOICE: {writing_style.replace('-', ' ')}.")
    if vocab:
        writing_parts.append(f"VOCABULARY: {vocab.replace('-', ' ')} level.")
    if dialogue:
        writing_parts.append(f"DIALOGUE STYLE: {dialogue.replace('-', ' ')}.")
    if narrator and narrator != "none":
        writing_parts.append(f"NARRATOR: {narrator.replace('-', ' ')}.")
    if text_density:
        writing_parts.append(f"TEXT DENSITY: {text_density.replace('-', ' ')}.")
    if humor and humor != "none":
        humor_desc = f"HUMOR: {humor} amount"
        if humor_style:
            humor_desc += f", {humor_style.replace('-', ' ')} style"
        writing_parts.append(humor_desc + ".")
    if themes:
        writing_parts.append(f"THEMES: {themes}.")
    if boundaries:
        writing_parts.append(f"NEVER INCLUDE: {boundaries}.")
    if naming:
        writing_parts.append(f"NAMING STYLE: {naming}.")
    if ui_text:
        writing_parts.append(f"UI TEXT: {ui_text.replace('-', ' ')}.")
    if writing_refs:
        writing_parts.append(f"REFERENCE WORKS: Channel the tone/style of {writing_refs}.")

    profile["writing_guide"] = " ".join(writing_parts)

    # ===== AUDIO GUIDE COMPILATION =====
    audio_parts = []
    music = profile.get("music_style", "")
    music_mood = profile.get("music_mood_default", "")
    sfx = profile.get("sfx_style", "")
    voice = profile.get("voice_style", "")
    voice_emotion = profile.get("voice_default_emotion", "")
    audio_notes = profile.get("audio_notes", "")

    if music:
        audio_parts.append(f"MUSIC: {music.replace('-', ' ')}.")
    if music_mood:
        audio_parts.append(f"DEFAULT MOOD: {music_mood}.")
    if sfx:
        audio_parts.append(f"SFX: {sfx.replace('-', ' ')}.")
    if voice and voice != "no-voice":
        audio_parts.append(f"VOICE: {voice.replace('-', ' ')}.")
    if voice_emotion and voice_emotion != "neutral":
        audio_parts.append(f"DEFAULT VOICE EMOTION: {voice_emotion}.")
    if audio_notes:
        audio_parts.append(f"NOTES: {audio_notes}.")

    profile["audio_guide"] = " ".join(audio_parts)

    # ===== CHARACTER GUIDE COMPILATION =====
    char_parts = []
    world = profile.get("world_setting", "")
    world_tone = profile.get("world_tone", "")
    proportions = profile.get("character_proportions", "")
    char_design = profile.get("character_design_philosophy", "")
    enemy = profile.get("enemy_design", "")
    cultural = profile.get("cultural_influences", "")

    if world:
        char_parts.append(f"SETTING: {world}.")
    if world_tone:
        char_parts.append(f"WORLD FEEL: {world_tone.replace('-', ' ')}.")
    if proportions:
        char_parts.append(f"PROPORTIONS: {proportions.replace('-', ' ')}.")
    if char_design:
        char_parts.append(f"DESIGN APPROACH: {char_design.replace('-', ' ')}.")
    if enemy:
        char_parts.append(f"ENEMIES: {enemy.replace('-', ' ')}.")
    if cultural:
        char_parts.append(f"CULTURAL INFLUENCES: {cultural}.")

    profile["character_guide"] = " ".join(char_parts)

    return profile


# ---- Style Profile API endpoints ----

@app.get("/api/pixel-studio/style-profile/questions")
async def style_profile_questions():
    """Return the style interview questions grouped by section."""
    by_section = {}
    for q in STYLE_INTERVIEW_QUESTIONS:
        sec = q.get("section", "general")
        by_section.setdefault(sec, []).append(q)
    section_labels = {
        "visual": "Visual Art & Pixel Style",
        "tone": "Tone, Maturity & Themes",
        "writing": "Writing & Dialogue",
        "audio": "Audio & Music",
        "world": "World & Character Design",
        "ui": "UI / UX Feel",
    }
    return {
        "sections": [
            {"id": sec, "label": section_labels.get(sec, sec), "questions": qs}
            for sec, qs in by_section.items()
        ],
        "all_questions": STYLE_INTERVIEW_QUESTIONS,
    }


@app.get("/api/pixel-studio/style-profile/{project_path:path}")
async def get_style_profile(project_path: str):
    """Get the current style profile for a project."""
    profile = load_style_profile(project_path)
    return {"ok": True, "profile": profile, "has_profile": _get_style_profile_path(project_path).exists()}


@app.post("/api/pixel-studio/style-profile/{project_path:path}")
async def set_style_profile(project_path: str, request: Request):
    """Set or update the style profile for a project. Accepts partial updates."""
    data = await request.json()
    existing = load_style_profile(project_path)

    # Merge new answers into existing profile
    for key, val in data.items():
        if key in DEFAULT_STYLE_PROFILE:
            existing[key] = val

    # Compile derived fields
    existing = _compile_style_profile(existing)
    save_style_profile(project_path, existing)
    return {"ok": True, "profile": existing}


@app.get("/api/pixel-studio/style-profile/guides/{project_path:path}")
async def get_style_guides(project_path: str):
    """Return the compiled creative guides for injection into LLM prompts.

    Returns separate guides for:
    - visual: prompt_prefix + negative for image generation
    - writing: tone, maturity, dialogue rules for text/script generation
    - audio: music, SFX, voice direction for audio generation
    - character: world, proportions, design approach for character creation
    - full_brief: everything combined as a single block for general-purpose LLM context
    """
    profile = load_style_profile(project_path)
    if not profile.get("writing_guide") and profile.get("tone"):
        profile = _compile_style_profile(profile)
        save_style_profile(project_path, profile)

    full_brief_parts = []
    if profile.get("prompt_prefix"):
        full_brief_parts.append(f"## Visual Direction\n{profile['prompt_prefix']}")
    if profile.get("writing_guide"):
        full_brief_parts.append(f"## Writing Direction\n{profile['writing_guide']}")
    if profile.get("audio_guide"):
        full_brief_parts.append(f"## Audio Direction\n{profile['audio_guide']}")
    if profile.get("character_guide"):
        full_brief_parts.append(f"## Character & World Direction\n{profile['character_guide']}")

    return {
        "ok": True,
        "visual": {
            "prompt_prefix": profile.get("prompt_prefix", ""),
            "negative_extra": profile.get("negative_extra", ""),
            "palette": profile.get("palette", ""),
            "resolution": profile.get("resolution", 64),
            "suggested_lora": profile.get("suggested_lora", ""),
        },
        "writing": profile.get("writing_guide", ""),
        "audio": profile.get("audio_guide", ""),
        "character": profile.get("character_guide", ""),
        "full_brief": "\n\n".join(full_brief_parts),
        "maturity": profile.get("maturity", ""),
        "content_boundaries": profile.get("content_boundaries", ""),
    }


@app.post("/api/pixel-studio/style-profile/from-reference")
async def style_profile_from_reference(request: Request):
    """Analyze a reference image to build a style profile. Uses Gemini Flash for analysis."""
    data = await request.json()
    image_path = data.get("image_path", "")
    project_path = data.get("project_path", "")

    if not image_path or not Path(image_path).exists():
        return JSONResponse({"error": "image_path required"}, status_code=400)

    # Use Gemini to analyze the reference image
    google_key = os.environ.get("GOOGLE_API_KEY", "")
    if not google_key:
        return JSONResponse({"error": "GOOGLE_API_KEY not set for image analysis"}, status_code=500)

    import base64, httpx
    img_bytes = Path(image_path).read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode()
    mime = "image/png" if image_path.endswith(".png") else "image/jpeg"

    analysis_prompt = (
        "Analyze this pixel art / game art image and describe:\n"
        "1. art_direction: Overall art style in one sentence\n"
        "2. era_console: Which retro console era it resembles (gameboy/nes/snes/gba/genesis/c64/modern_hd/none)\n"
        "3. palette: Closest named palette (pico8/gameboy/nes/sweetie16/endesga32/endesga64/aap64/c64/1bit)\n"
        "4. resolution: Estimated pixel size (16/32/48/64/96/128/256)\n"
        "5. perspective: Camera perspective (side-scroll/top-down/isometric/first-person)\n"
        "6. color_mood: Color mood (warm/cool/dark/vibrant/pastel/neon/muted/monochrome)\n"
        "7. special_notes: Notable style traits (outlines, dithering, etc.)\n\n"
        "Return ONLY valid JSON with these exact keys. No markdown, no explanation."
    )

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={google_key}",
                json={"contents": [{"parts": [
                    {"inline_data": {"mime_type": mime, "data": img_b64}},
                    {"text": analysis_prompt},
                ]}]},
                timeout=30,
            )
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Strip markdown code fences if present
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                analysis = json.loads(text)

                # Save as profile if project_path given
                if project_path:
                    existing = load_style_profile(project_path)
                    for k, v in analysis.items():
                        if k in DEFAULT_STYLE_PROFILE and v:
                            existing[k] = v
                    # Add reference image
                    refs = existing.get("reference_images", [])
                    if image_path not in refs:
                        refs.append(image_path)
                    existing["reference_images"] = refs
                    existing = _compile_style_profile(existing)
                    save_style_profile(project_path, existing)
                    return {"ok": True, "analysis": analysis, "profile": existing}

                return {"ok": True, "analysis": analysis}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "Analysis failed"}


# --- API: Pixel Art Studio (RetroDiffusion-style local pipeline) ---

# ---- Helpers ----

def _build_pixel_prompt(prompt: str, style: str = "", lora_type: str = "",
                        tiling: bool = False, extra_tags: str = "",
                        project_path: str = "") -> tuple[str, str]:
    """Assemble full prompt + negative from project style profile, style preset,
    LoRA triggers, and user prompt. Project style profile takes priority."""
    parts = []
    neg_parts = ["worst quality, low quality, blurry, deformed, watermark, text, signature"]

    # 1. Project style profile (highest priority for consistency)
    if project_path:
        profile = load_style_profile(project_path)
        if profile.get("prompt_prefix"):
            parts.append(profile["prompt_prefix"])
        if profile.get("negative_extra"):
            neg_parts.append(profile["negative_extra"])

    # 2. Style preset (only if no project profile, or as override)
    if style and style in PIXEL_STYLE_PRESETS:
        preset = PIXEL_STYLE_PRESETS[style]
        parts.append(preset["prompt_prefix"])
        neg_parts.append(preset.get("negative_extra", ""))
    else:
        # Check custom styles
        custom = _load_custom_styles()
        if style and style in custom:
            cs = custom[style]
            parts.append(cs.get("prompt_prefix", ""))
            neg_parts.append(cs.get("negative_extra", ""))

    trigger = LORA_TRIGGERS.get(lora_type, "")
    if trigger:
        parts.append(trigger)
    if tiling:
        parts.append("seamless tileable pattern, repeating texture,")
    if extra_tags:
        parts.append(extra_tags)
    parts.append(prompt)
    return " ".join(p for p in parts if p), ", ".join(n for n in neg_parts if n)


def _resolve_gen_dims(resolution: int) -> tuple[int, int]:
    """Pick generation dimensions — generate high, pixelize down."""
    gen = max(512, resolution * 8)
    gen = min(gen, 1024)
    return gen, gen


async def _comfyui_generate(workflow: dict, output_path: Path, timeout: int = 120) -> Path:
    """Queue workflow, poll, download first output image."""
    from comfyui_client import queue_prompt, poll_completion, get_output_images, download_image
    pid = queue_prompt(workflow)
    result = poll_completion(pid, timeout=timeout)
    imgs = get_output_images(result)
    if not imgs:
        raise RuntimeError("ComfyUI returned no images")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_image(imgs[0], output_path)
    return output_path


async def _comfyui_generate_all(workflow: dict, timeout: int = 120) -> list[dict]:
    """Queue workflow, poll, return all output image infos."""
    from comfyui_client import queue_prompt, poll_completion, get_output_images
    pid = queue_prompt(workflow)
    result = poll_completion(pid, timeout=timeout)
    return get_output_images(result)


def _post_process(output_path: Path, resolution: int, palette: str = "",
                  repair: bool = True, remove_bg: bool = True,
                  gen_width: int = 1024) -> dict:
    """Post-processing pipeline: pixelize → repair → palettize → rembg."""
    warnings = []
    if not PIXEL_TOOLKIT_AVAILABLE:
        return {"warnings": ["Pixel toolkit not available, skipping post-processing"]}
    try:
        from PIL import Image as PILImage
        img = PILImage.open(output_path).convert("RGBA")

        if resolution < gen_width:
            img = pixelize(img, target_size=resolution, num_colors=0, palette_name=palette)

        if repair and resolution <= 128:
            img = repair_pixel_grid(img, 1)

        if palette and resolution >= gen_width:
            img = reduce_palette(img, palette_name=palette)

        if remove_bg:
            temp = output_path.with_stem(output_path.stem + "_pre_rembg")
            img.save(temp)
            tools_dir = SKILLS_DIR / "godotsmith" / "tools"
            rembg_result = subprocess.run(
                [sys.executable, str(tools_dir / "rembg_matting.py"), str(temp), "-o", str(output_path)],
                capture_output=True, text=True, timeout=120,
            )
            temp.unlink(missing_ok=True)
            if rembg_result.returncode == 0:
                img = PILImage.open(output_path).convert("RGBA")
            else:
                warnings.append(f"rembg failed: {rembg_result.stderr[:200]}")

        img.save(output_path)
    except Exception as e:
        warnings.append(f"Post-processing partial: {e}")
    return {"warnings": warnings}


async def _expand_prompt(prompt: str) -> str:
    """Use Gemini Flash to expand a terse prompt into a detailed pixel art description."""
    try:
        google_key = os.environ.get("GOOGLE_API_KEY", "")
        if not google_key:
            return prompt
        import httpx
        expansion_prompt = (
            "You are a pixel art prompt expander. Given a short description, expand it into a "
            "detailed prompt for generating pixel art. Keep it under 100 words. Focus on visual "
            "details: colors, shading, pose, perspective, background. Do NOT add quotes. "
            f"Input: {prompt}\nExpanded:"
        )
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={google_key}",
                json={"contents": [{"parts": [{"text": expansion_prompt}]}]},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                expanded = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return expanded
    except Exception:
        pass
    return prompt


# ---- Info endpoints ----

@app.get("/api/pixel-studio/presets")
async def pixel_presets():
    """List all style presets, grouped by tier."""
    by_tier = {"pro": {}, "fast": {}, "plus": {}}
    for k, v in PIXEL_STYLE_PRESETS.items():
        tier = v.get("tier", "fast")
        by_tier.setdefault(tier, {})[k] = v
    custom = _load_custom_styles()
    return {"presets": by_tier, "custom": custom}


@app.get("/api/pixel-studio/animations")
async def pixel_animation_presets():
    """List all animation presets."""
    return ANIMATION_PRESETS


@app.get("/api/pixel-studio/tilesets")
async def pixel_tileset_presets():
    """List all tileset presets."""
    return TILESET_PRESETS


@app.get("/api/pixel-studio/palettes")
async def pixel_palettes():
    """List all palettes with hex colors."""
    if PIXEL_TOOLKIT_AVAILABLE:
        return {name: [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in colors]
                for name, colors in PIXEL_PALETTES.items()}
    return {}


@app.get("/api/pixel-studio/loras")
async def pixel_loras():
    """List available LoRAs from ComfyUI, filtered for pixel art."""
    cfg = load_config()
    if check_service(cfg["comfyui_port"]):
        try:
            from comfyui_client import list_loras
            available = list_loras()
            pixel_loras = [l for l in available if any(k in l.lower() for k in
                          ["pixel", "sprite", "2d", "retro", "elusarca", "newpixel"])]
            return {"all": available, "pixel": pixel_loras, "zit": ZIT_PIXEL_LORAS}
        except Exception:
            pass
    return {"all": [], "pixel": [], "zit": ZIT_PIXEL_LORAS}


@app.get("/api/pixel-studio/models")
async def pixel_models():
    """List available checkpoints, samplers, schedulers, upscale models."""
    cfg = load_config()
    if check_service(cfg["comfyui_port"]):
        try:
            from comfyui_client import list_checkpoints, list_loras, list_samplers, list_schedulers, list_upscale_models
            return {
                "checkpoints": list_checkpoints(),
                "loras": list_loras(),
                "samplers": list_samplers(),
                "schedulers": list_schedulers(),
                "upscale_models": list_upscale_models(),
            }
        except Exception:
            pass
    return {"checkpoints": [], "loras": [], "samplers": [], "schedulers": [], "upscale_models": []}


@app.get("/api/pixel-studio/resolutions")
async def pixel_resolutions():
    return {"resolutions": PIXEL_RESOLUTIONS, "upscale_factors": UPSCALE_FACTORS,
            "frame_durations": FRAME_DURATION_OPTIONS, "output_formats": OUTPUT_FORMATS}


# ---- Core generation: txt2img ----

@app.post("/api/pixel-studio/generate")
async def pixel_generate(request: Request):
    """Full pixel art generation pipeline: generate → pixelize → palettize → remove bg.
    Mirrors RetroDiffusion /v1/inferences for txt2img."""
    data = await request.json()
    prompt = data.get("prompt", "")
    style = data.get("style", "")
    resolution = data.get("resolution", 64)
    palette = data.get("palette", "")
    lora_type = data.get("lora_type", "")
    lora_name = data.get("lora_name", "")
    remove_bg = data.get("remove_bg", True)
    do_repair = data.get("repair_grid", True)
    tiling = data.get("tiling", False)
    seed = data.get("seed", None)
    steps = data.get("steps", 25)
    cfg_scale = data.get("cfg", 7.0)
    sampler = data.get("sampler", "dpmpp_2m")
    scheduler = data.get("scheduler", "karras")
    project_path = data.get("project_path", "")
    filename = data.get("filename", "pixel_art.png")
    checkpoint = data.get("checkpoint", "")
    num_images = min(data.get("num_images", 1), 4)
    expand_prompt = data.get("expand_prompt", False)
    return_pre_palette = data.get("return_pre_palette", False)
    return_non_bg_removed = data.get("return_non_bg_removed", False)
    upscale_output_factor = data.get("upscale_output_factor", None)

    # Fill defaults from style preset
    if style and style in PIXEL_STYLE_PRESETS:
        preset = PIXEL_STYLE_PRESETS[style]
        if not palette:
            palette = preset.get("suggested_palette", "")
        if not lora_type:
            lora_type = preset.get("suggested_lora", "sprite_64")
        if not resolution or resolution == 64:
            resolution = preset.get("suggested_resolution", 64)

    cfg_obj = load_config()
    if not check_service(cfg_obj["comfyui_port"]):
        return JSONResponse({"error": "ComfyUI not running"}, status_code=503)

    if expand_prompt:
        prompt = await _expand_prompt(prompt)

    # Apply project style profile defaults
    if project_path:
        profile = load_style_profile(project_path)
        if not palette and profile.get("palette"):
            palette = profile["palette"]
        if not lora_type and profile.get("suggested_lora"):
            lora_type = profile["suggested_lora"]
        if (not resolution or resolution == 64) and profile.get("resolution"):
            resolution = profile["resolution"]
        if not style and profile.get("suggested_style_preset"):
            style = profile["suggested_style_preset"]

    full_prompt, full_negative = _build_pixel_prompt(prompt, style, lora_type, tiling,
                                                      project_path=project_path)
    gen_w, gen_h = _resolve_gen_dims(resolution)

    from comfyui_client import (build_txt2img_with_lora_workflow, build_txt2img_workflow,
                                 build_tiling_workflow, download_image as dl_img)

    results = []
    for i in range(num_images):
        fname = filename if num_images == 1 else f"{Path(filename).stem}_{i}{Path(filename).suffix}"
        out_path = Path(project_path) / "assets" / "img" / fname if project_path else Path(fname)

        if tiling:
            wf = build_tiling_workflow(
                prompt=full_prompt, negative=full_negative,
                checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
                lora_name=lora_name, lora_strength=0.8,
                width=gen_w, height=gen_h, steps=steps, cfg=cfg_scale,
                sampler=sampler, scheduler=scheduler, seed=seed,
            )
        elif lora_name:
            wf = build_txt2img_with_lora_workflow(
                prompt=full_prompt, negative=full_negative,
                checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
                lora_name=lora_name, lora_strength=0.8,
                width=gen_w, height=gen_h, steps=steps, cfg=cfg_scale,
                sampler=sampler, scheduler=scheduler, seed=seed,
            )
        else:
            wf = build_txt2img_workflow(
                prompt=full_prompt, negative=full_negative,
                checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
                width=gen_w, height=gen_h, steps=steps, cfg=cfg_scale,
                sampler=sampler, scheduler=scheduler, seed=seed,
            )

        try:
            await _comfyui_generate(wf, out_path)
        except Exception as e:
            results.append({"ok": False, "error": str(e), "filename": fname})
            continue

        extras = {}
        if return_pre_palette and PIXEL_TOOLKIT_AVAILABLE:
            pre_path = out_path.with_stem(out_path.stem + "_pre_palette")
            from PIL import Image as PILImage
            PILImage.open(out_path).save(pre_path)
            extras["pre_palette_path"] = str(pre_path)

        pp = _post_process(out_path, resolution, palette, do_repair, remove_bg, gen_w)

        if return_non_bg_removed and remove_bg:
            extras["non_bg_removed_note"] = "Save pre-rembg copy via return_pre_palette"

        # Optional upscale
        if upscale_output_factor and upscale_output_factor > 1 and PIXEL_TOOLKIT_AVAILABLE:
            from PIL import Image as PILImage
            img = PILImage.open(out_path).convert("RGBA")
            new_w = img.width * upscale_output_factor
            new_h = img.height * upscale_output_factor
            img = img.resize((new_w, new_h), resample=PILImage.NEAREST)
            img.save(out_path)

        results.append({
            "ok": True, "path": str(out_path), "resolution": resolution,
            "palette": palette, "style": style, "prompt_used": full_prompt,
            **extras, **{k: v for k, v in pp.items() if v},
        })

    if num_images == 1:
        return results[0]
    return {"ok": True, "images": results, "count": len(results)}


# ---- img2img ----

@app.post("/api/pixel-studio/img2img")
async def pixel_img2img(request: Request):
    """Image-to-image pixel art generation. Upload a reference, restyle as pixel art."""
    data = await request.json()
    image_path = data.get("image_path", "")
    prompt = data.get("prompt", "")
    style = data.get("style", "")
    strength = data.get("strength", 0.6)
    resolution = data.get("resolution", 64)
    palette = data.get("palette", "")
    lora_type = data.get("lora_type", "")
    lora_name = data.get("lora_name", "")
    remove_bg = data.get("remove_bg", True)
    do_repair = data.get("repair_grid", True)
    seed = data.get("seed", None)
    steps = data.get("steps", 25)
    cfg_scale = data.get("cfg", 7.0)
    sampler = data.get("sampler", "dpmpp_2m")
    scheduler = data.get("scheduler", "karras")
    project_path = data.get("project_path", "")
    filename = data.get("filename", "pixel_i2i.png")
    checkpoint = data.get("checkpoint", "")

    if not image_path or not Path(image_path).exists():
        return JSONResponse({"error": "image_path required and must exist"}, status_code=400)

    cfg_obj = load_config()
    if not check_service(cfg_obj["comfyui_port"]):
        return JSONResponse({"error": "ComfyUI not running"}, status_code=503)

    from comfyui_client import upload_image, build_img2img_workflow, build_img2img_with_lora_workflow

    uploaded_name = upload_image(Path(image_path))
    full_prompt, full_negative = _build_pixel_prompt(prompt, style, lora_type,
                                                      project_path=project_path)
    out_path = Path(project_path) / "assets" / "img" / filename if project_path else Path(filename)

    if lora_name:
        wf = build_img2img_with_lora_workflow(
            image_filename=uploaded_name, prompt=full_prompt, negative=full_negative,
            checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
            lora_name=lora_name, lora_strength=0.8, denoise=strength,
            steps=steps, cfg=cfg_scale, sampler=sampler, scheduler=scheduler, seed=seed,
        )
    else:
        wf = build_img2img_workflow(
            image_filename=uploaded_name, prompt=full_prompt, negative=full_negative,
            checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
            denoise=strength, steps=steps, cfg=cfg_scale,
            sampler=sampler, scheduler=scheduler, seed=seed,
        )

    try:
        await _comfyui_generate(wf, out_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    gen_w = 1024  # img2img uses input image dims
    pp = _post_process(out_path, resolution, palette, do_repair, remove_bg, gen_w)
    return {"ok": True, "path": str(out_path), "resolution": resolution,
            "palette": palette, "style": style, **{k: v for k, v in pp.items() if v}}


# ---- Pixelate (convert any image to pixel art) ----

@app.post("/api/pixel-studio/pixelate")
async def pixel_pixelate(request: Request):
    """Convert any image into pixel art. Like RetroDiffusion's rd_pro__pixelate."""
    data = await request.json()
    image_path = data.get("image_path", "")
    input_image_b64 = data.get("input_image", "")
    target_size = data.get("target_size", data.get("width", 64))
    palette = data.get("palette", "")
    colors = data.get("colors", 0)
    dither = data.get("dither", False)
    remove_bg = data.get("remove_bg", False)
    output_path = data.get("output_path", "")

    if not PIXEL_TOOLKIT_AVAILABLE:
        return JSONResponse({"error": "Pixel toolkit not available"}, status_code=500)

    from PIL import Image as PILImage
    import base64, io

    if input_image_b64:
        img_bytes = base64.b64decode(input_image_b64)
        img = PILImage.open(io.BytesIO(img_bytes)).convert("RGBA")
        if not output_path:
            output_path = "pixelated_output.png"
    elif image_path:
        img = PILImage.open(image_path).convert("RGBA")
        if not output_path:
            output_path = str(Path(image_path).with_stem(Path(image_path).stem + "_pixel"))
    else:
        return JSONResponse({"error": "image_path or input_image required"}, status_code=400)

    result = pixelize(img, target_size, colors, palette, dither)

    if remove_bg:
        temp = Path(output_path).with_stem(Path(output_path).stem + "_tmp")
        temp.parent.mkdir(parents=True, exist_ok=True)
        result.save(temp)
        tools_dir = SKILLS_DIR / "godotsmith" / "tools"
        subprocess.run(
            [sys.executable, str(tools_dir / "rembg_matting.py"), str(temp), "-o", str(output_path)],
            capture_output=True, text=True, timeout=120,
        )
        temp.unlink(missing_ok=True)
        result = PILImage.open(output_path).convert("RGBA")
    else:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        result.save(output_path)

    # Return base64 too for API consumers
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {"ok": True, "path": str(output_path), "size": list(result.size),
            "base64_image": b64}


# ---- Edit / Inpaint ----

@app.post("/api/pixel-studio/edit")
async def pixel_edit(request: Request):
    """Progressive image editing via inpainting. Like RetroDiffusion /v1/edit."""
    data = await request.json()
    image_path = data.get("image_path", "")
    input_image_b64 = data.get("input_image", "")
    mask_path = data.get("mask_path", "")
    mask_b64 = data.get("mask", "")
    prompt = data.get("prompt", "")
    strength = data.get("strength", 0.8)
    style = data.get("style", "")
    resolution = data.get("resolution", 64)
    palette = data.get("palette", "")
    seed = data.get("seed", None)
    steps = data.get("steps", 25)
    cfg_scale = data.get("cfg", 7.0)
    checkpoint = data.get("checkpoint", "")
    output_path = data.get("output_path", "")
    project_path = data.get("project_path", "")

    cfg_obj = load_config()
    if not check_service(cfg_obj["comfyui_port"]):
        return JSONResponse({"error": "ComfyUI not running"}, status_code=503)

    from comfyui_client import upload_image, build_inpaint_workflow
    from PIL import Image as PILImage
    import base64, io

    # Handle base64 inputs
    if input_image_b64 and not image_path:
        img_bytes = base64.b64decode(input_image_b64)
        tmp_img = Path("_edit_input.png")
        tmp_img.write_bytes(img_bytes)
        image_path = str(tmp_img)

    if mask_b64 and not mask_path:
        mask_bytes = base64.b64decode(mask_b64)
        tmp_mask = Path("_edit_mask.png")
        tmp_mask.write_bytes(mask_bytes)
        mask_path = str(tmp_mask)

    if not image_path or not mask_path:
        return JSONResponse({"error": "image_path + mask_path (or base64 equivalents) required"}, status_code=400)

    uploaded_img = upload_image(Path(image_path))
    uploaded_mask = upload_image(Path(mask_path))

    full_prompt, full_negative = _build_pixel_prompt(prompt, style, project_path=project_path)
    if not output_path:
        output_path = str(Path(image_path).with_stem(Path(image_path).stem + "_edited"))

    wf = build_inpaint_workflow(
        image_filename=uploaded_img, mask_filename=uploaded_mask,
        prompt=full_prompt, negative=full_negative,
        checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
        denoise=strength, steps=steps, cfg=cfg_scale, seed=seed,
    )

    out = Path(output_path)
    try:
        await _comfyui_generate(wf, out)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    pp = _post_process(out, resolution, palette, repair=True, remove_bg=False, gen_width=1024)

    buf = io.BytesIO()
    PILImage.open(out).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {"ok": True, "path": str(out), "base64_image": b64,
            **{k: v for k, v in pp.items() if v}}


# ---- Animation ----

@app.post("/api/pixel-studio/animate")
async def pixel_animate(request: Request):
    """Generate animated sprite sheets / GIFs. Covers walk cycles, attacks, VFX, etc."""
    data = await request.json()
    prompt = data.get("prompt", "")
    animation_type = data.get("animation_type", "idle")
    input_image = data.get("input_image_path", "")
    resolution = data.get("resolution", 0)
    frames_duration = data.get("frames_duration", 0)
    palette = data.get("palette", "")
    lora_type = data.get("lora_type", "")
    lora_name = data.get("lora_name", "")
    return_spritesheet = data.get("return_spritesheet", True)
    return_gif = data.get("return_gif", True)
    fps = data.get("fps", 8)
    style = data.get("style", "")
    seed = data.get("seed", None)
    steps = data.get("steps", 25)
    cfg_scale = data.get("cfg", 7.0)
    sampler = data.get("sampler", "dpmpp_2m")
    scheduler = data.get("scheduler", "karras")
    checkpoint = data.get("checkpoint", "")
    project_path = data.get("project_path", "")
    filename = data.get("filename", "animation")

    if animation_type not in ANIMATION_PRESETS:
        return JSONResponse({"error": f"Unknown animation_type. Options: {list(ANIMATION_PRESETS.keys())}"},
                          status_code=400)

    anim = ANIMATION_PRESETS[animation_type]

    # Resolve frame count
    if frames_duration and "frames_options" in anim:
        if frames_duration not in anim["frames_options"]:
            frames_duration = anim.get("default_frames", 8)
    else:
        frames_duration = anim.get("frames", anim.get("default_frames", 8))

    # Resolve resolution
    if not resolution:
        resolution = anim.get("default_size", 64)
    resolution = min(resolution, anim.get("max_size", 256))

    columns = anim.get("columns", 4)
    rows = math.ceil(frames_duration / columns)

    cfg_obj = load_config()
    if not check_service(cfg_obj["comfyui_port"]):
        return JSONResponse({"error": "ComfyUI not running"}, status_code=503)

    # Build animation prompt
    anim_prompt = anim["prompt_template"].format(prompt=prompt, extra_prompt=prompt)
    if not lora_type:
        lora_type = "character" if anim.get("type") in ("character", "advanced") else "sprite_64"

    full_prompt, full_negative = _build_pixel_prompt(anim_prompt, style, lora_type,
                                                      project_path=project_path)

    # Generate a sprite sheet as a single image (batch of frames in one generation)
    # We generate at higher res, then pixelize each frame down
    sheet_w = resolution * columns
    sheet_h = resolution * rows
    gen_w = max(512, min(1024, sheet_w * 4))
    gen_h = max(512, min(1024, sheet_h * 4))
    # Keep aspect ratio close to sheet
    ar = sheet_w / sheet_h if sheet_h > 0 else 1.0
    if ar > 1:
        gen_h = max(512, int(gen_w / ar))
    else:
        gen_w = max(512, int(gen_h * ar))
    gen_w = (gen_w // 8) * 8
    gen_h = (gen_h // 8) * 8

    from comfyui_client import build_txt2img_with_lora_workflow, build_txt2img_workflow

    if lora_name:
        wf = build_txt2img_with_lora_workflow(
            prompt=full_prompt, negative=full_negative,
            checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
            lora_name=lora_name, lora_strength=0.8,
            width=gen_w, height=gen_h, steps=steps, cfg=cfg_scale,
            sampler=sampler, scheduler=scheduler, seed=seed,
        )
    else:
        wf = build_txt2img_workflow(
            prompt=full_prompt, negative=full_negative,
            checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
            width=gen_w, height=gen_h, steps=steps, cfg=cfg_scale,
            sampler=sampler, scheduler=scheduler, seed=seed,
        )

    base_dir = Path(project_path) / "assets" / "img" if project_path else Path(".")
    sheet_path = base_dir / f"{filename}_sheet.png"

    try:
        await _comfyui_generate(wf, sheet_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    result = {"ok": True, "animation_type": animation_type, "frames": frames_duration,
              "columns": columns, "rows": rows, "resolution": resolution}

    # Post-process: pixelize the sheet down to target size, then extract frames
    if PIXEL_TOOLKIT_AVAILABLE:
        from PIL import Image as PILImage
        sheet_img = PILImage.open(sheet_path).convert("RGBA")

        # Resize to exact sheet dimensions
        target_w = resolution * columns
        target_h = resolution * rows
        sheet_img = sheet_img.resize((target_w, target_h), resample=PILImage.NEAREST)

        if palette:
            sheet_img_rgb = sheet_img.convert("RGB")
            from PIL import Image as PILImg
            sheet_img_reduced = reduce_palette(sheet_img, palette_name=palette)
            sheet_img = sheet_img_reduced

        sheet_img.save(sheet_path)
        result["spritesheet_path"] = str(sheet_path)

        # Extract frames
        frames = extract_frames(sheet_img, columns, rows)
        frames = frames[:frames_duration]  # Trim to exact count

        if return_gif and frames:
            gif_path = base_dir / f"{filename}.gif"
            save_gif(frames, gif_path, fps)
            result["gif_path"] = str(gif_path)

    return result


# ---- Tilesets ----

@app.post("/api/pixel-studio/tileset")
async def pixel_tileset(request: Request):
    """Generate tileset sprites. Wang tilesets, single tiles, variations, objects."""
    data = await request.json()
    prompt = data.get("prompt", "")
    extra_prompt = data.get("extra_prompt", "")
    tileset_type = data.get("tileset_type", "single_tile")
    resolution = data.get("resolution", 0)
    palette = data.get("palette", "")
    input_image_path = data.get("input_image_path", "")
    extra_input_image_path = data.get("extra_input_image_path", "")
    lora_name = data.get("lora_name", "")
    seed = data.get("seed", None)
    steps = data.get("steps", 25)
    cfg_scale = data.get("cfg", 7.0)
    sampler = data.get("sampler", "dpmpp_2m")
    scheduler = data.get("scheduler", "karras")
    checkpoint = data.get("checkpoint", "")
    project_path = data.get("project_path", "")
    filename = data.get("filename", "tileset.png")

    if tileset_type not in TILESET_PRESETS:
        return JSONResponse({"error": f"Unknown tileset_type. Options: {list(TILESET_PRESETS.keys())}"},
                          status_code=400)

    tile_cfg = TILESET_PRESETS[tileset_type]
    if not resolution:
        resolution = tile_cfg.get("default_size", 32)
    resolution = max(tile_cfg.get("min_size", 16), min(resolution, tile_cfg.get("max_size", 64)))

    cfg_obj = load_config()
    if not check_service(cfg_obj["comfyui_port"]):
        return JSONResponse({"error": "ComfyUI not running"}, status_code=503)

    tile_prompt = tile_cfg["prompt_template"].format(prompt=prompt, extra_prompt=extra_prompt)
    full_prompt, full_negative = _build_pixel_prompt(tile_prompt, "", "tileset", tiling=True,
                                                      project_path=project_path)

    from comfyui_client import build_tiling_workflow

    # For wang tilesets, generate larger to get all tiles
    if tile_cfg["type"] in ("wang", "wang_advanced"):
        gen_size = max(512, resolution * 16)
    elif tile_cfg["type"] == "variation":
        gen_size = max(512, resolution * 8)
    else:
        gen_size = max(512, resolution * 8)
    gen_size = min(gen_size, 1024)

    wf = build_tiling_workflow(
        prompt=full_prompt, negative=full_negative,
        checkpoint=checkpoint or "juggernautXL_ragnarokBy.safetensors",
        lora_name=lora_name, lora_strength=0.8,
        width=gen_size, height=gen_size, steps=steps, cfg=cfg_scale,
        sampler=sampler, scheduler=scheduler, seed=seed,
    )

    out_path = Path(project_path) / "assets" / "img" / filename if project_path else Path(filename)
    try:
        await _comfyui_generate(wf, out_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Post-process: pixelize to tile resolution
    if PIXEL_TOOLKIT_AVAILABLE:
        from PIL import Image as PILImage
        img = PILImage.open(out_path).convert("RGBA")
        # Resize to nearest multiple of tile size
        tw = (img.width // resolution) * resolution
        th = (img.height // resolution) * resolution
        img = img.resize((tw, th), resample=PILImage.NEAREST)
        if palette:
            img = reduce_palette(img, palette_name=palette)
        img.save(out_path)

    return {"ok": True, "path": str(out_path), "tileset_type": tileset_type,
            "tile_size": resolution, "palette": palette}


# ---- Upscale ----

@app.post("/api/pixel-studio/upscale")
async def pixel_upscale(request: Request):
    """Upscale pixel art. Nearest-neighbor for pixel-perfect, or model-based for detail."""
    data = await request.json()
    image_path = data.get("image_path", "")
    input_image_b64 = data.get("input_image", "")
    factor = data.get("factor", 4)
    method = data.get("method", "nearest")  # "nearest" or "model"
    model_name = data.get("model_name", "4x-UltraSharp.pth")
    output_path = data.get("output_path", "")

    from PIL import Image as PILImage
    import base64, io

    if input_image_b64:
        img = PILImage.open(io.BytesIO(base64.b64decode(input_image_b64))).convert("RGBA")
        if not output_path:
            output_path = "upscaled_output.png"
    elif image_path:
        img = PILImage.open(image_path).convert("RGBA")
        if not output_path:
            output_path = str(Path(image_path).with_stem(Path(image_path).stem + f"_{factor}x"))
    else:
        return JSONResponse({"error": "image_path or input_image required"}, status_code=400)

    if method == "nearest":
        new_w = img.width * factor
        new_h = img.height * factor
        result = img.resize((new_w, new_h), resample=PILImage.NEAREST)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        result.save(output_path)
    elif method == "model":
        cfg_obj = load_config()
        if not check_service(cfg_obj["comfyui_port"]):
            return JSONResponse({"error": "ComfyUI not running for model upscale"}, status_code=503)
        from comfyui_client import upload_image, build_upscale_workflow
        # Save temp for upload
        tmp = Path("_upscale_input.png")
        img.save(tmp)
        uploaded = upload_image(tmp)
        wf = build_upscale_workflow(image_filename=uploaded, upscale_model=model_name)
        try:
            await _comfyui_generate(wf, Path(output_path))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            tmp.unlink(missing_ok=True)
    else:
        return JSONResponse({"error": f"Unknown method: {method}. Use 'nearest' or 'model'"},
                          status_code=400)

    # Return base64
    result_img = PILImage.open(output_path)
    buf = io.BytesIO()
    result_img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {"ok": True, "path": str(output_path), "factor": factor, "method": method,
            "size": list(result_img.size), "base64_image": b64}


# ---- Post-processing tools ----

@app.post("/api/pixel-studio/pixelize")
async def pixel_pixelize(request: Request):
    """Pixelize an existing image (alias for backward compat)."""
    data = await request.json()
    image_path = data.get("image_path", "")
    target_size = data.get("target_size", 64)
    palette = data.get("palette", "")
    colors = data.get("colors", 0)
    dither = data.get("dither", False)

    if not PIXEL_TOOLKIT_AVAILABLE:
        return JSONResponse({"error": "Pixel toolkit not available"}, status_code=500)

    from PIL import Image as PILImage
    img = PILImage.open(image_path).convert("RGBA")
    result = pixelize(img, target_size, colors, palette, dither)
    output = Path(image_path).with_stem(Path(image_path).stem + "_pixel")
    result.save(output)
    return {"ok": True, "path": str(output), "size": list(result.size)}


@app.post("/api/pixel-studio/palettize")
async def pixel_palettize(request: Request):
    """Apply palette to an image."""
    data = await request.json()
    image_path = data.get("image_path", "")
    palette = data.get("palette", "pico8")
    colors = data.get("colors", 16)
    dither = data.get("dither", False)

    if not PIXEL_TOOLKIT_AVAILABLE:
        return JSONResponse({"error": "Pixel toolkit not available"}, status_code=500)

    from PIL import Image as PILImage
    img = PILImage.open(image_path).convert("RGBA")
    result = reduce_palette(img, colors, palette, dither)
    output = Path(image_path).with_stem(Path(image_path).stem + f"_{palette}")
    result.save(output)
    return {"ok": True, "path": str(output)}


@app.post("/api/pixel-studio/repair")
async def pixel_repair(request: Request):
    """Repair pixel grid alignment."""
    data = await request.json()
    image_path = data.get("image_path", "")
    pixel_size = data.get("pixel_size", 0)

    if not PIXEL_TOOLKIT_AVAILABLE:
        return JSONResponse({"error": "Pixel toolkit not available"}, status_code=500)

    from PIL import Image as PILImage
    img = PILImage.open(image_path).convert("RGBA")
    if pixel_size == 0:
        h, v = detect_pixel_size(img)
        pixel_size = max(h, v)
    result = repair_pixel_grid(img, pixel_size)
    output = Path(image_path).with_stem(Path(image_path).stem + "_repaired")
    result.save(output)
    return {"ok": True, "path": str(output), "pixel_size": pixel_size}


@app.post("/api/pixel-studio/spritesheet")
async def pixel_spritesheet(request: Request):
    """Assemble frames into a sprite sheet."""
    data = await request.json()
    frame_paths = data.get("frame_paths", [])
    columns = data.get("columns", 4)
    output_path = data.get("output_path", "")

    if not frame_paths or not output_path:
        return JSONResponse({"error": "frame_paths and output_path required"}, status_code=400)

    from PIL import Image as PILImage
    frames = [PILImage.open(p).convert("RGBA") for p in frame_paths]
    sheet = make_spritesheet(frames, columns)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return {"ok": True, "path": output_path, "frames": len(frames), "size": list(sheet.size)}


@app.post("/api/pixel-studio/gif")
async def pixel_gif(request: Request):
    """Create animated GIF from sprite sheet or frame paths."""
    data = await request.json()
    sheet_path = data.get("sheet_path", "")
    frame_paths = data.get("frame_paths", [])
    columns = data.get("columns", 4)
    rows = data.get("rows", 4)
    fps = data.get("fps", 8)
    output_path = data.get("output_path", "")

    if not output_path:
        return JSONResponse({"error": "output_path required"}, status_code=400)

    from PIL import Image as PILImage
    if sheet_path:
        sheet = PILImage.open(sheet_path).convert("RGBA")
        frames = extract_frames(sheet, columns, rows)
    elif frame_paths:
        frames = [PILImage.open(p).convert("RGBA") for p in frame_paths]
    else:
        return JSONResponse({"error": "Provide sheet_path or frame_paths"}, status_code=400)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_gif(frames, out, fps)
    return {"ok": True, "path": str(out), "frames": len(frames), "fps": fps}


# ---- Batch generation ----

@app.post("/api/pixel-studio/batch")
async def pixel_batch(request: Request):
    """Generate multiple pixel art images with different seeds."""
    data = await request.json()
    count = min(data.get("count", 1), 8)
    data["num_images"] = count
    data["seed"] = None  # Force random seed per image

    # Reuse the generate endpoint logic
    from starlette.testclient import TestClient
    # Direct call with modified data
    class FakeRequest:
        async def json(self):
            return data
    return await pixel_generate(FakeRequest())


# ---- Prompt expansion ----

@app.post("/api/pixel-studio/expand-prompt")
async def pixel_expand_prompt(request: Request):
    """Expand a terse prompt into a detailed pixel art description via LLM."""
    data = await request.json()
    prompt = data.get("prompt", "")
    if not prompt:
        return JSONResponse({"error": "prompt required"}, status_code=400)
    expanded = await _expand_prompt(prompt)
    return {"ok": True, "original": prompt, "expanded": expanded}


# ---- User custom styles CRUD ----

@app.get("/api/pixel-studio/styles")
async def pixel_list_styles():
    """List user-created custom styles."""
    return _load_custom_styles()


@app.post("/api/pixel-studio/styles")
async def pixel_create_style(request: Request):
    """Create a user-defined custom style."""
    data = await request.json()
    style_id = data.get("id", "").replace(" ", "_").lower()
    if not style_id:
        return JSONResponse({"error": "id required"}, status_code=400)

    styles = _load_custom_styles()
    styles[style_id] = {
        "name": data.get("name", style_id),
        "icon": data.get("icon", "🎨"),
        "prompt_prefix": data.get("prompt_prefix", ""),
        "negative_extra": data.get("negative_extra", ""),
        "suggested_palette": data.get("suggested_palette", ""),
        "suggested_lora": data.get("suggested_lora", "sprite_64"),
        "suggested_resolution": data.get("suggested_resolution", 64),
        "reference_image": data.get("reference_image", ""),
        "llm_instructions": data.get("llm_instructions", ""),
        "force_palette": data.get("force_palette", ""),
        "force_bg_removal": data.get("force_bg_removal", False),
    }
    _save_custom_styles(styles)
    return {"ok": True, "id": style_id, "style": styles[style_id]}


@app.patch("/api/pixel-studio/styles/{style_id}")
async def pixel_update_style(style_id: str, request: Request):
    """Update a user-defined custom style."""
    styles = _load_custom_styles()
    if style_id not in styles:
        return JSONResponse({"error": "Style not found"}, status_code=404)
    data = await request.json()
    for key in data:
        if key in styles[style_id]:
            styles[style_id][key] = data[key]
    _save_custom_styles(styles)
    return {"ok": True, "id": style_id, "style": styles[style_id]}


@app.delete("/api/pixel-studio/styles/{style_id}")
async def pixel_delete_style(style_id: str):
    """Delete a user-defined custom style."""
    styles = _load_custom_styles()
    if style_id not in styles:
        return JSONResponse({"error": "Style not found"}, status_code=404)
    del styles[style_id]
    _save_custom_styles(styles)
    return {"ok": True, "deleted": style_id}


# --- API: VNCCS Character Pipeline ---

@app.post("/api/vnccs/generate-character")
async def vnccs_generate_character(request: Request):
    """Generate a consistent character using VNCCS pipeline via ComfyUI."""
    data = await request.json()
    project_path = data.get("project_path", "")
    character_name = data.get("character_name", "character")
    description = data.get("description", "")
    art_style = data.get("art_style", "anime style")
    emotions = data.get("emotions", ["neutral", "happy", "sad", "angry"])
    checkpoint = data.get("checkpoint", "")

    cfg = load_config()
    if not check_service(cfg["comfyui_port"]):
        return JSONResponse({"error": "ComfyUI not running"}, status_code=503)

    output_dir = Path(project_path) / "assets" / "img" / "characters" / character_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build VNCCS workflow — base character sheet generation
    # Use a txt2img approach with character sheet prompt
    full_prompt = f"character sheet, {art_style}, {description}, multiple views, front side back, white background, full body, consistent design, reference sheet"
    negative = "blurry, low quality, deformed, extra limbs, bad anatomy, watermark"

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"

    results = {"base": None, "emotions": {}}

    # Stage 1: Generate base character sheet
    base_path = output_dir / f"{character_name}_base.png"
    result = subprocess.run(
        [sys.executable, str(tools_dir / "asset_gen.py"), "image",
         "--prompt", full_prompt, "--backend", "comfyui", "--size", "1K",
         "-o", str(base_path)],
        capture_output=True, text=True, cwd=project_path, timeout=120,
    )
    if result.returncode == 0 and base_path.exists():
        results["base"] = str(base_path)

    # Stage 2: Generate emotion variants
    for emotion in emotions:
        emo_prompt = f"{art_style}, {description}, {emotion} expression, portrait, bust shot, white background, same character"
        emo_path = output_dir / f"{character_name}_{emotion}.png"
        emo_result = subprocess.run(
            [sys.executable, str(tools_dir / "asset_gen.py"), "image",
             "--prompt", emo_prompt, "--backend", "comfyui", "--size", "512",
             "-o", str(emo_path)],
            capture_output=True, text=True, cwd=project_path, timeout=120,
        )
        if emo_result.returncode == 0 and emo_path.exists():
            results["emotions"][emotion] = str(emo_path)

    # Stage 3: Remove backgrounds
    rembg_script = tools_dir / "rembg_matting.py"
    if rembg_script.exists():
        for img_path in output_dir.glob("*.png"):
            clean = img_path.with_stem(img_path.stem + "_clean")
            subprocess.run(
                [sys.executable, str(rembg_script), str(img_path), "-o", str(clean)],
                capture_output=True, timeout=120,
            )
            if clean.exists():
                clean.replace(img_path)

    return {
        "ok": True,
        "character": character_name,
        "output_dir": str(output_dir),
        "files": results,
        "total_files": len(list(output_dir.glob("*.png"))),
    }


@app.get("/api/vnccs/characters/{path:path}")
async def list_characters(path: str):
    """List all generated characters in a project."""
    char_dir = Path(path) / "assets" / "img" / "characters"
    if not char_dir.exists():
        return {"characters": []}
    chars = []
    for d in sorted(char_dir.iterdir()):
        if d.is_dir():
            images = list(d.glob("*.png"))
            chars.append({
                "name": d.name,
                "path": str(d),
                "image_count": len(images),
                "images": [{"name": f.name, "path": str(f)} for f in sorted(images)],
            })
    return {"characters": chars}


# --- API: Krita Bridge ---

@app.post("/api/krita/open")
async def krita_open_asset(request: Request):
    """Open an image in Krita for editing."""
    data = await request.json()
    image_path = data.get("image_path", "")
    if not image_path or not Path(image_path).exists():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    # Try to find Krita
    krita_paths = [
        "C:/Program Files/Krita (x64)/bin/krita.exe",
        "C:/Program Files/Krita/bin/krita.exe",
        shutil.which("krita"),
    ]
    krita_exe = None
    for kp in krita_paths:
        if kp and Path(kp).exists():
            krita_exe = kp
            break

    if not krita_exe:
        return {"ok": False, "error": "Krita not found. Install from krita.org"}

    try:
        subprocess.Popen([krita_exe, image_path])
        return {"ok": True, "message": f"Opened {Path(image_path).name} in Krita"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- API: Stable Audio ---

@app.post("/api/audio/generate-ai-music")
async def generate_ai_music(request: Request):
    """Generate music using ComfyUI Stable Audio nodes."""
    data = await request.json()
    project_path = data.get("project_path", "")
    prompt = data.get("prompt", "")
    duration = data.get("duration", 10)
    filename = data.get("filename", "ai_music.wav")

    cfg = load_config()
    if not check_service(cfg["comfyui_port"]):
        # Fallback to procedural
        return await generate_music(request)

    # Build Stable Audio workflow
    workflow = {
        "1": {
            "class_type": "EmptyLatentAudio",
            "inputs": {"seconds": min(duration, 47)}  # Stable Audio max ~47s
        },
        "2": {
            "class_type": "ConditioningStableAudio",
            "inputs": {
                "positive_prompt": prompt,
                "negative_prompt": "noise, static, distortion, low quality",
                "seconds_total": min(duration, 47),
                "seconds_start": 0,
            }
        },
    }

    # Check if Stable Audio nodes exist
    try:
        r = requests.get(f"http://localhost:{cfg['comfyui_port']}/object_info/EmptyLatentAudio", timeout=5)
        if r.status_code != 200:
            # Stable Audio not available, fall back to procedural
            tools_dir = SKILLS_DIR / "godotsmith" / "tools"
            output = Path(project_path) / "assets" / "audio" / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            # Parse mood from prompt
            mood = "neutral"
            for m in ["epic", "dark", "tense", "sad", "happy"]:
                if m in prompt.lower():
                    mood = m
                    break
            result = subprocess.run(
                [sys.executable, str(tools_dir / "audio_gen.py"), "music",
                 "--mood", mood, "--duration", str(duration), "-o", str(output)],
                capture_output=True, text=True, timeout=30,
            )
            return {"ok": result.returncode == 0, "path": str(output), "backend": "procedural",
                    "note": "Stable Audio model not loaded, used procedural fallback"}
    except Exception:
        pass

    # If we get here, try the full Stable Audio workflow
    # For now, fall back to procedural since Stable Audio requires model loading
    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    output = Path(project_path) / "assets" / "audio" / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    mood = "neutral"
    for m in ["epic", "dark", "tense", "sad", "happy"]:
        if m in prompt.lower():
            mood = m
            break
    result = subprocess.run(
        [sys.executable, str(tools_dir / "audio_gen.py"), "music",
         "--mood", mood, "--duration", str(duration), "-o", str(output)],
        capture_output=True, text=True, timeout=30,
    )
    return {"ok": result.returncode == 0, "path": str(output), "backend": "procedural"}


# --- API: Sprite Studio ---

@app.post("/api/sprites/generate")
async def generate_sprite(request: Request):
    """Generate pixel art sprites via ComfyUI with 2D Pixel Toolkit LoRAs."""
    data = await request.json()
    project_path = data.get("project_path", "")
    prompt = data.get("prompt", "")
    sprite_type = data.get("sprite_type", "sprite_64")  # sprite_64, sprite_32, animal, weapon, etc.
    columns = data.get("columns", 4)
    rows = data.get("rows", 4)
    bg_color = data.get("bg_color", "#00FF00")
    filename = data.get("filename", "sprite_sheet.png")
    remove_bg = data.get("remove_bg", True)

    if not project_path or not prompt:
        return JSONResponse({"error": "project_path and prompt required"}, status_code=400)

    cfg = load_config()
    if not check_service(cfg["comfyui_port"]):
        return JSONResponse({"error": "ComfyUI not running"}, status_code=503)

    # Build sprite generation workflow
    # Prefix with pixel art trigger words based on type
    trigger_words = {
        "sprite_64": "sprites_64, pixel art sprite sheet,",
        "sprite_32": "sprites_32, pixel art sprite sheet,",
        "animal": "animal, pixel art sprite,",
        "weapon": "cold_weapon, pixel art sprite,",
        "item": "pixel art item sprite,",
        "building": "isometric building, pixel art,",
        "tileset": "pixel art tileset, seamless tile,",
        "character": "pixel art character sprite sheet, multiple poses,",
    }
    full_prompt = f"{trigger_words.get(sprite_type, 'pixel art sprite,')} {prompt}"

    # Use asset_gen with ComfyUI
    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    output_path = Path(project_path) / "assets" / "img" / filename

    result = subprocess.run(
        [sys.executable, str(tools_dir / "asset_gen.py"), "image",
         "--prompt", full_prompt, "--backend", "comfyui",
         "--size", "1K", "-o", str(output_path)],
        capture_output=True, text=True, cwd=project_path, timeout=120,
    )

    if result.returncode != 0:
        return {"ok": False, "error": result.stderr[:500]}

    # Optional background removal
    if remove_bg and output_path.exists():
        rembg_script = tools_dir / "rembg_matting.py"
        if rembg_script.exists():
            clean_path = output_path.with_stem(output_path.stem + "_clean")
            bg_result = subprocess.run(
                [sys.executable, str(rembg_script), str(output_path), "-o", str(clean_path)],
                capture_output=True, text=True, timeout=120,
            )
            if bg_result.returncode == 0 and clean_path.exists():
                clean_path.replace(output_path)

    return {"ok": True, "path": str(output_path)}


@app.post("/api/sprites/remove-bg")
async def remove_sprite_bg(request: Request):
    """Remove background from an existing sprite image."""
    data = await request.json()
    image_path = data.get("image_path", "")
    if not image_path or not Path(image_path).exists():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    rembg_script = tools_dir / "rembg_matting.py"

    output = Path(image_path).with_stem(Path(image_path).stem + "_nobg")
    result = subprocess.run(
        [sys.executable, str(rembg_script), image_path, "-o", str(output)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0 and output.exists():
        return {"ok": True, "path": str(output)}
    return {"ok": False, "error": result.stderr[:500]}


# --- API: Audio Studio ---

@app.post("/api/audio/generate-sfx")
async def generate_sfx(request: Request):
    """Generate sound effects."""
    data = await request.json()
    project_path = data.get("project_path", "")
    sfx_type = data.get("sfx_type", "hit")
    duration = data.get("duration", 0.5)
    filename = data.get("filename", "sfx.wav")

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    output = Path(project_path) / "assets" / "audio" / filename
    output.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, str(tools_dir / "audio_gen.py"), "sfx",
         "--type", sfx_type, "--duration", str(duration), "-o", str(output)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        return {"ok": True, "path": str(output)}
    return {"ok": False, "error": result.stderr[:500]}


@app.post("/api/audio/generate-tts")
async def generate_tts(request: Request):
    """Generate speech audio."""
    data = await request.json()
    project_path = data.get("project_path", "")
    text = data.get("text", "")
    voice = data.get("voice", "female_us")
    speed = data.get("speed", 1.0)
    filename = data.get("filename", "dialogue.mp3")

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    output = Path(project_path) / "assets" / "audio" / filename
    output.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, str(tools_dir / "audio_gen.py"), "tts",
         "--text", text, "--voice", voice, "--speed", str(speed), "-o", str(output)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode == 0:
        return {"ok": True, "path": str(output)}
    return {"ok": False, "error": result.stderr[:500]}


@app.post("/api/audio/generate-music")
async def generate_music(request: Request):
    """Generate background music."""
    data = await request.json()
    project_path = data.get("project_path", "")
    mood = data.get("mood", "neutral")
    tempo = data.get("tempo", 120)
    key = data.get("key", "C")
    duration = data.get("duration", 30)
    filename = data.get("filename", "bgm.wav")

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    output = Path(project_path) / "assets" / "audio" / filename
    output.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, str(tools_dir / "audio_gen.py"), "music",
         "--mood", mood, "--tempo", str(tempo), "--key", key,
         "--duration", str(duration), "-o", str(output)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        return {"ok": True, "path": str(output)}
    return {"ok": False, "error": result.stderr[:500]}


# --- API: File Browser & Code Editor ---

@app.get("/api/project/files/{path:path}")
async def list_project_files(path: str, dir: str = ""):
    """List files in a project directory."""
    root = Path(path) / dir if dir else Path(path)
    if not root.exists():
        return {"files": [], "error": "Directory not found"}

    items = []
    try:
        for entry in sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            # Skip hidden/build dirs
            if entry.name.startswith(".") and entry.name not in [".gitignore"]:
                continue
            if entry.name in ["__pycache__", "node_modules", ".godot"]:
                continue

            rel = str(entry.relative_to(Path(path))).replace("\\", "/")
            item = {
                "name": entry.name,
                "path": rel,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
            }
            if entry.is_file():
                item["ext"] = entry.suffix.lower()
            items.append(item)
    except PermissionError:
        pass
    return {"files": items, "current_dir": dir}


@app.get("/api/project/file-content/{path:path}")
async def read_file(path: str, file: str = ""):
    """Read a text file's content."""
    fp = Path(path) / file if file else Path(path)
    if not fp.exists() or not fp.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)
    # Only read text files
    text_exts = {".gd", ".tscn", ".tres", ".cfg", ".md", ".txt", ".json", ".csv",
                 ".gdshader", ".import", ".godot", ".gitignore", ".py", ".cs", ".cpp",
                 ".h", ".toml", ".yaml", ".yml", ".ini", ".xml", ".html", ".css", ".js"}
    if fp.suffix.lower() not in text_exts:
        return JSONResponse({"error": "Not a text file", "ext": fp.suffix}, status_code=400)
    try:
        content = fp.read_text(errors="replace")
        return {"content": content, "path": str(fp), "name": fp.name, "ext": fp.suffix}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/project/file-save")
async def save_file(request: Request):
    """Save text content to a file."""
    data = await request.json()
    file_path = data.get("file_path", "")
    content = data.get("content", "")
    if not file_path:
        return JSONResponse({"error": "file_path required"}, status_code=400)
    fp = Path(file_path)
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return {"ok": True, "path": str(fp)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- API: GitHub Integration ---

@app.get("/api/github/status")
async def github_status():
    """Check if gh CLI is authenticated."""
    try:
        result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=10)
        authenticated = "Logged in" in result.stdout or "Logged in" in result.stderr
        user = ""
        for line in (result.stdout + result.stderr).splitlines():
            if "account" in line.lower():
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.lower() == "account":
                        if i + 1 < len(parts):
                            user = parts[i + 1]
                            break
        return {"authenticated": authenticated, "user": user, "output": result.stderr.strip()}
    except FileNotFoundError:
        return {"authenticated": False, "error": "gh CLI not installed"}
    except Exception as e:
        return {"authenticated": False, "error": str(e)}


@app.get("/api/github/repo-status/{path:path}")
async def github_repo_status(path: str):
    """Get git/GitHub status for a project."""
    p = Path(path)
    if not (p / ".git").exists():
        return {"is_repo": False}

    info = {"is_repo": True}

    # Current branch
    try:
        r = subprocess.run(["git", "branch", "--show-current"], cwd=path, capture_output=True, text=True, timeout=5)
        info["branch"] = r.stdout.strip()
    except Exception:
        info["branch"] = "unknown"

    # Remote URL
    try:
        r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=path, capture_output=True, text=True, timeout=5)
        info["remote"] = r.stdout.strip()
        info["has_remote"] = bool(info["remote"])
    except Exception:
        info["remote"] = ""
        info["has_remote"] = False

    # Status (changed files)
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True, timeout=10)
        changes = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        info["changes"] = changes
        info["has_changes"] = len(changes) > 0
        info["change_count"] = len(changes)
    except Exception:
        info["changes"] = []
        info["has_changes"] = False

    # Ahead/behind
    try:
        r = subprocess.run(["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
                          cwd=path, capture_output=True, text=True, timeout=5)
        parts = r.stdout.strip().split()
        if len(parts) == 2:
            info["ahead"] = int(parts[0])
            info["behind"] = int(parts[1])
    except Exception:
        info["ahead"] = 0
        info["behind"] = 0

    return info


@app.post("/api/github/create-repo")
async def create_github_repo(request: Request):
    """Create a GitHub repo for a project."""
    data = await request.json()
    path = data.get("path", "")
    name = data.get("name", "")
    description = data.get("description", "")
    private = data.get("private", False)

    if not path or not name:
        return JSONResponse({"error": "path and name required"}, status_code=400)

    visibility = "--private" if private else "--public"
    cmd = ["gh", "repo", "create", name, visibility,
           "--description", description or f"Game project created with Godotsmith",
           "--source", path, "--push"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            # Extract repo URL from output
            url = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            return {"ok": True, "url": url, "output": result.stdout + result.stderr}
        return {"ok": False, "error": result.stderr.strip(), "output": result.stdout}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/github/commit")
async def git_commit(request: Request):
    """Stage all changes and commit."""
    data = await request.json()
    path = data.get("path", "")
    message = data.get("message", "Update from Godotsmith IDE")

    try:
        # Stage all
        subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, timeout=10)
        # Also force-add assets
        subprocess.run(["git", "add", "-f", "assets/"], cwd=path, capture_output=True, timeout=10)
        # Commit
        result = subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return {"ok": True, "output": result.stdout}
        if "nothing to commit" in result.stdout:
            return {"ok": True, "output": "Nothing to commit"}
        return {"ok": False, "error": result.stderr or result.stdout}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/github/push")
async def git_push(request: Request):
    """Push to remote."""
    data = await request.json()
    path = data.get("path", "")
    try:
        result = subprocess.run(["git", "push"], cwd=path, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return {"ok": True, "output": result.stdout + result.stderr}
        return {"ok": False, "error": result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/github/pull")
async def git_pull(request: Request):
    """Pull from remote."""
    data = await request.json()
    path = data.get("path", "")
    try:
        result = subprocess.run(["git", "pull"], cwd=path, capture_output=True, text=True, timeout=60)
        return {"ok": result.returncode == 0, "output": result.stdout + result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- API: Freesound ---

@app.get("/api/freesound/search")
async def freesound_search(q: str = "", limit: int = 15, page: int = 1):
    """Search Freesound.org for sound effects."""
    cfg = load_config()
    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    env = dict(os.environ)
    env["FREESOUND_API_KEY"] = cfg.get("freesound_api_key", "")
    result = subprocess.run(
        [sys.executable, str(tools_dir / "freesound_client.py"), "search", q,
         "--limit", str(limit), "--page", str(page)],
        capture_output=True, text=True, timeout=15, env=env,
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    return {"error": result.stderr or "Search failed", "sounds": []}


@app.post("/api/freesound/download")
async def freesound_download(request: Request):
    """Download a Freesound preview into a project."""
    data = await request.json()
    sound_id = data.get("sound_id")
    project_path = data.get("project_path", "")
    filename = data.get("filename", f"freesound_{sound_id}.mp3")

    cfg = load_config()
    output = Path(project_path) / "assets" / "audio" / filename
    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    env = dict(os.environ)
    env["FREESOUND_API_KEY"] = cfg.get("freesound_api_key", "")

    result = subprocess.run(
        [sys.executable, str(tools_dir / "freesound_client.py"), "download",
         str(sound_id), "-o", str(output)],
        capture_output=True, text=True, timeout=30, env=env,
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    return {"ok": False, "error": result.stderr or "Download failed"}


# --- API: Color Palette ---

@app.get("/api/palette/presets")
async def palette_presets():
    """List available palette presets."""
    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    result = subprocess.run(
        [sys.executable, str(tools_dir / "palette_gen.py"), "list"],
        capture_output=True, text=True, timeout=5,
    )
    return {"presets": result.stdout.strip().splitlines()}


@app.post("/api/palette/generate")
async def generate_palette(request: Request):
    """Generate a color palette."""
    data = await request.json()
    preset = data.get("preset", "fantasy_rpg")
    variant = data.get("variant", "balanced")
    project_path = data.get("project_path", "")

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    cmd = [sys.executable, str(tools_dir / "palette_gen.py"), "generate",
           "--preset", preset, "--variant", variant]

    if project_path:
        json_out = Path(project_path) / "assets" / "palette.json"
        gd_out = Path(project_path) / "scripts" / "palette_colors.gd"
        cmd.extend(["-o", str(json_out), "--gdscript", str(gd_out)])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return json.loads(result.stdout)
    return {"error": result.stderr}


# --- API: Batch Dialogue ---

@app.post("/api/audio/batch-dialogue")
async def batch_dialogue(request: Request):
    """Generate TTS for multiple dialogue lines from JSON."""
    data = await request.json()
    project_path = data.get("project_path", "")
    lines = data.get("lines", [])  # [{character, text, voice, emotion, filename}]

    if not lines:
        return JSONResponse({"error": "No dialogue lines"}, status_code=400)

    # Write temp JSON file
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(lines, f)
        tmp_path = f.name

    tools_dir = SKILLS_DIR / "godotsmith" / "tools"
    result = subprocess.run(
        [sys.executable, str(tools_dir / "batch_dialogue.py"), tmp_path, "--project", project_path],
        capture_output=True, text=True, timeout=600,  # 10 min for large batches
    )

    os.unlink(tmp_path)

    if result.returncode == 0:
        return json.loads(result.stdout)
    return {"ok": False, "error": result.stderr[:500]}


# --- API: Build/Export ---

@app.post("/api/project/export")
async def export_project(request: Request):
    """Export a Godot project as Windows exe or HTML5."""
    data = await request.json()
    path = data.get("path", "")
    target = data.get("target", "windows")  # windows, web, linux

    cfg = load_config()
    pf = Path(path) / "project.godot"
    if not pf.exists():
        return JSONResponse({"error": "No project.godot"}, status_code=400)

    export_dir = Path(path) / "export" / target
    export_dir.mkdir(parents=True, exist_ok=True)

    # Check for export_presets.cfg — create if missing
    presets_file = Path(path) / "export_presets.cfg"
    if not presets_file.exists():
        # Create minimal export presets
        presets = ""
        if target == "windows":
            presets = '''[preset.0]

name="Windows Desktop"
platform="Windows Desktop"
runnable=true
export_filter="all_resources"
export_path="export/windows/game.exe"

[preset.0.options]
'''
        elif target == "web":
            presets = '''[preset.0]

name="Web"
platform="Web"
runnable=true
export_filter="all_resources"
export_path="export/web/index.html"

[preset.0.options]
'''
        elif target == "linux":
            presets = '''[preset.0]

name="Linux"
platform="Linux"
runnable=true
export_filter="all_resources"
export_path="export/linux/game.x86_64"

[preset.0.options]
'''
        presets_file.write_text(presets)

    # Determine output filename
    filenames = {"windows": "game.exe", "web": "index.html", "linux": "game.x86_64"}
    output_file = export_dir / filenames.get(target, "game.exe")

    try:
        # Try export — needs export templates installed in Godot
        result = subprocess.run(
            [cfg["godot_exe"], "--headless", "--export-all", "--path", path],
            capture_output=True, text=True, timeout=120,
        )

        if output_file.exists():
            return {
                "ok": True,
                "target": target,
                "output": str(output_file),
                "size_mb": round(output_file.stat().st_size / 1048576, 1),
            }

        # Export templates might not be installed
        if "No export template" in result.stderr or "export template" in result.stderr.lower():
            return {
                "ok": False,
                "error": "Export templates not installed. Open Godot > Editor > Manage Export Templates > Download.",
                "output": result.stderr[:500],
            }

        return {"ok": False, "error": result.stderr[:500] or "Export failed", "output": result.stdout[:500]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Export timed out (120s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- API: Project Management ---

@app.post("/api/project/delete")
async def delete_project(request: Request):
    """Remove a project from the registry (optionally delete files)."""
    data = await request.json()
    path = data.get("path", "")
    delete_files = data.get("delete_files", False)

    projects = load_projects()
    projects = [p for p in projects if p["path"] != path]
    save_projects(projects)

    if delete_files and path and Path(path).exists():
        shutil.rmtree(path)
        return {"ok": True, "deleted_files": True, "path": path}

    return {"ok": True, "deleted_files": False, "path": path}


@app.post("/api/project/duplicate")
async def duplicate_project(request: Request):
    """Duplicate a project to a new folder."""
    data = await request.json()
    source_path = data.get("path", "")
    new_name = data.get("new_name", "")

    if not source_path or not new_name or not Path(source_path).exists():
        return JSONResponse({"error": "Invalid source path or name"}, status_code=400)

    cfg = load_config()
    folder = new_name.lower().replace(" ", "-")
    for ch in "!@#$%^&*()+=[]{}|\\:;<>,?/~`'\"":
        folder = folder.replace(ch, "")
    target = Path(cfg["projects_root"]) / folder

    if target.exists():
        return JSONResponse({"error": f"Folder {target} already exists"}, status_code=400)

    # Copy everything except .git and .godot
    shutil.copytree(source_path, str(target), ignore=shutil.ignore_patterns(".git", ".godot", "export"))

    # Init fresh git
    subprocess.run(["git", "init", "-q"], cwd=str(target), capture_output=True)

    # Update project name in project.godot
    pf = target / "project.godot"
    if pf.exists():
        content = pf.read_text()
        content = content.replace(
            f'config/name=',
            f'config/name="{new_name}"\n; old_', 1
        ) if f'config/name="{new_name}"' not in content else content
        pf.write_text(content)

    # Register new project
    projects = load_projects()
    # Find source project info
    source_info = {}
    for p in projects:
        if p["path"] == source_path:
            source_info = dict(p)
            break

    projects.insert(0, {
        "name": new_name,
        "path": str(target),
        "engine": source_info.get("engine", "godot"),
        "genre": source_info.get("genre", ""),
        "concept": source_info.get("concept", ""),
        "created": datetime.now().isoformat(),
        "last_opened": datetime.now().isoformat(),
    })
    save_projects(projects)

    return {"ok": True, "path": str(target), "name": new_name}


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


def resolve_pixel_lora(lora_key: str, available_loras: list[str] | None = None) -> str:
    """Resolve a pixel LoRA key to an actual filename available in ComfyUI.
    Checks PIXEL_LORA_VARIANTS for all known filenames, returns first match."""
    if lora_key in PIXEL_LORA_VARIANTS:
        for variant in PIXEL_LORA_VARIANTS[lora_key]:
            if available_loras is None:
                return variant  # No list to check against, return first
            if variant in available_loras:
                return variant
    return ZIT_PIXEL_LORAS.get(lora_key, "")

# (pixel art toolkit imported near top of file, before STYLE_INTERVIEW_QUESTIONS)

# User custom styles storage
CUSTOM_STYLES_PATH = Path(__file__).parent / "pixel_custom_styles.json"

def _load_custom_styles() -> dict:
    if CUSTOM_STYLES_PATH.exists():
        return json.loads(CUSTOM_STYLES_PATH.read_text())
    return {}

def _save_custom_styles(styles: dict):
    CUSTOM_STYLES_PATH.write_text(json.dumps(styles, indent=2))

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
        prompt = data.get("prompt", "")
        claude_args = "claude"
        if cfg.get("auto_approve"):
            claude_args = "claude --dangerously-skip-permissions"

        if prompt:
            # Build a context-aware continuation prompt
            import tempfile
            prompt_text = ""

            prompt_file = Path(path) / "GAME_PROMPT.md"
            plan_file = Path(path) / "PLAN.md"
            project_file = Path(path) / "project.godot"

            if plan_file.exists():
                # Game already started — find incomplete tasks
                plan_content = plan_file.read_text(errors="ignore")
                pending_tasks = []
                current_task = None
                for line in plan_content.splitlines():
                    if line.startswith("## ") and ". " in line:
                        current_task = line[3:]
                    elif current_task and "**Status:** pending" in line:
                        pending_tasks.append(current_task)
                        current_task = None
                    elif current_task and "**Status:**" in line:
                        current_task = None

                if pending_tasks:
                    prompt_text = f"Continue building this game. Read PLAN.md, STRUCTURE.md, and MEMORY.md for context.\n\nPending tasks:\n"
                    for t in pending_tasks[:5]:
                        prompt_text += f"- {t}\n"
                    prompt_text += "\nPick up where we left off. Run /godotsmith if you need to regenerate the plan."
                else:
                    prompt_text = "The game plan tasks are all done. Read PLAN.md and ask the user what to improve or add next."
            elif prompt_file.exists():
                # Game prompt exists but no plan yet — start building
                prompt_text = prompt_file.read_text()
            else:
                # No context — just open Claude
                prompt_text = ""

            if prompt_text:
                cont_file = Path(path) / "CONTINUE_PROMPT.md"
                cont_file.write_text(prompt_text)

            # Write a batch file to avoid all cmd escaping issues
            bat_file = Path(path) / ".godotsmith_launch.bat"
            bat_lines = [
                "@echo off",
                f'cd /d "{path}"',
            ]
            if prompt_text:
                bat_lines.append(f'{claude_args} "Read CONTINUE_PROMPT.md and proceed with the tasks listed there."')
            else:
                bat_lines.append(claude_args)
            bat_file.write_text("\r\n".join(bat_lines))
            cmd = ["cmd", "/c", "start", "", "cmd", "/k", str(bat_file)]
        else:
            bat_file = Path(path) / ".godotsmith_launch.bat"
            bat_file.write_text(f"@echo off\r\ncd /d \"{path}\"\r\n{claude_args}\r\n")
            cmd = ["cmd", "/c", "start", "", "cmd", "/k", str(bat_file)]
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


# --- Tutorial Ingestion + Distillation ---

DISTILL_PROMPT = """You are compressing a game-dev tutorial transcript into an actionable pattern summary for a Godot game-generation agent.

The transcript is likely noisy (auto-transcribed speech). Extract ONLY concrete, implementable lessons — ignore filler, intros, and generic encouragement.

Output STRICTLY in this markdown format:

## Topic
{one-line description of what this tutorial teaches — e.g. "Procedural dungeon generation using BSP trees"}

## When to Apply
{one sentence — when would an agent building a game use this? e.g. "When asked to generate a roguelike, dungeon crawler, or any game with procedurally laid-out rooms"}

## Key Patterns
- {pattern 1 — concrete technique with 1-line reasoning}
- {pattern 2}
- {3-6 total, no more}

## Code Concepts
{If the transcript describes specific Godot classes, node compositions, or algorithms, list them as a bullet list. Use class names verbatim (e.g. CharacterBody2D, AStar2D, RandomNumberGenerator). Omit this section if no concrete APIs are discussed.}

## Gotchas
{Any warnings, quirks, or "don't do X" advice from the tutorial. Omit if none.}

Aim for ~200 words total. Be concrete. If the tutorial is too vague or off-topic for game dev, output exactly: SKIP — reason

Tutorial domain: {domain}
Tutorial title: {title}

TRANSCRIPT:
{transcript}
"""


async def _distill_tutorial(md_path: Path) -> dict:
    """Use Gemini Flash to distill a tutorial into an actionable summary.
    Returns {ok, summary, skipped, reason}. Writes `## Distilled Summary` section to the tutorial markdown."""
    google_key = os.environ.get("GOOGLE_API_KEY", "")
    if not google_key:
        return {"ok": False, "error": "GOOGLE_API_KEY not set; distillation requires Gemini"}
    if not md_path.exists():
        return {"ok": False, "error": "tutorial not found"}

    text = md_path.read_text(encoding="utf-8", errors="replace")
    # Parse existing metadata
    title = md_path.stem
    domain = "generic"
    for line in text.splitlines()[:20]:
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("**Domain:**"):
            domain = line.split("**Domain:**", 1)[1].strip()

    # Use only the "Full Transcript" section for distillation (the Notes section is just reformatted)
    transcript = text
    if "## Full Transcript" in text:
        transcript = text.split("## Full Transcript", 1)[1]
    # Cap at 30k chars — Gemini Flash handles this fine, avoids runaway costs
    transcript = transcript[:30000]

    prompt = DISTILL_PROMPT.format(domain=domain, title=title, transcript=transcript)

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={google_key}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=60,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Gemini error: {r.text[:300]}"}
            data = r.json()
            summary = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return {"ok": False, "error": f"distill failed: {e}"}

    if summary.startswith("SKIP"):
        return {"ok": True, "skipped": True, "reason": summary, "summary": ""}

    # Write/update `## Distilled Summary` section in the tutorial markdown
    marker = "## Distilled Summary"
    if marker in text:
        # Replace existing section (everything from marker until next ## at column 0 or EOF)
        before, _after = text.split(marker, 1)
        # Find next top-level section after current one
        lines_after = _after.splitlines()
        keep_from = len(lines_after)
        for i, line in enumerate(lines_after[1:], 1):  # skip the marker's own remainder
            if line.startswith("## "):
                keep_from = i
                break
        new_text = before + marker + "\n\n" + summary + "\n\n" + "\n".join(lines_after[keep_from:])
    else:
        # Insert before "## Full Transcript" or at end
        if "## Full Transcript" in text:
            head, tail = text.split("## Full Transcript", 1)
            new_text = head + marker + "\n\n" + summary + "\n\n## Full Transcript" + tail
        else:
            new_text = text + "\n\n" + marker + "\n\n" + summary + "\n"
    md_path.write_text(new_text, encoding="utf-8")
    return {"ok": True, "skipped": False, "summary": summary}


def _rebuild_tutorial_index() -> Path:
    """Regenerate memory/tutorials/INDEX.md from every tutorial's distilled summary."""
    TUTORIALS_DIR.mkdir(parents=True, exist_ok=True)
    index_path = TUTORIALS_DIR / "INDEX.md"
    entries = []
    for md in sorted(TUTORIALS_DIR.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        title = md.stem
        source = ""
        domain = ""
        for line in text.splitlines()[:20]:
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("**Source:**"):
                source = line.split("**Source:**", 1)[1].strip()
            elif line.startswith("**Domain:**"):
                domain = line.split("**Domain:**", 1)[1].strip()
        # Extract distilled summary if present
        summary = ""
        if "## Distilled Summary" in text:
            _, after = text.split("## Distilled Summary", 1)
            lines = after.splitlines()
            summary_lines = []
            for line in lines[1:]:
                if line.startswith("## "):
                    break
                summary_lines.append(line)
            summary = "\n".join(summary_lines).strip()
        entries.append({
            "file": md.name, "title": title, "source": source, "domain": domain, "summary": summary,
        })

    lines = [
        "# Tutorial Index",
        "",
        "Auto-generated registry of ingested game-dev tutorials with distilled patterns.",
        "Read by godot-task when a task involves patterns any of these tutorials cover.",
        "",
        f"**Total:** {len(entries)} tutorial(s)",
        "",
    ]
    for e in entries:
        lines.append(f"## [{e['title']}]({e['file']})")
        lines.append("")
        if e["source"]:
            lines.append(f"- **Source:** {e['source']}")
        if e["domain"]:
            lines.append(f"- **Domain:** {e['domain']}")
        lines.append(f"- **File:** `{e['file']}`")
        lines.append("")
        if e["summary"]:
            lines.append(e["summary"])
        else:
            lines.append("*(Not yet distilled — run `POST /api/tutorials/distill` or use the Distill button in the UI.)*")
        lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def _run_tutorial_ingest(job_id: str, url: str | None, file_path: str | None,
                         domain: str | None, model: str, auto_distill: bool = True) -> None:
    """Background task — calls tutorial_ingest.py and updates TUTORIAL_JOBS."""
    try:
        TUTORIALS_DIR.mkdir(parents=True, exist_ok=True)
        tool = SKILLS_DIR / "godotsmith" / "tools" / "tutorial_ingest.py"
        cmd = [sys.executable, str(tool), "ingest", "--out", str(TUTORIALS_DIR), "--model", model]
        if url:
            cmd += ["--url", url]
        elif file_path:
            cmd += ["--file", file_path]
        else:
            TUTORIAL_JOBS[job_id] = {"status": "error", "message": "No URL or file provided", "path": ""}
            return
        if domain and domain != "auto":
            cmd += ["--domain", domain]
        TUTORIAL_JOBS[job_id] = {"status": "running", "message": "Downloading + transcribing…", "path": ""}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout.strip().splitlines()[-1])
                out_path = payload.get("path", "")
                TUTORIAL_JOBS[job_id] = {
                    "status": "running", "path": out_path,
                    "message": f"Transcribed ({payload.get('segment_count', 0)} segments). Distilling…" if auto_distill else "Done",
                }
                if auto_distill and out_path:
                    # Schedule distillation in same thread (we're already off the event loop)
                    try:
                        import asyncio as _a
                        _a.new_event_loop().run_until_complete(_distill_tutorial(Path(out_path)))
                    except Exception as e:
                        TUTORIAL_JOBS[job_id]["message"] = f"Transcribed, distill failed: {e}"
                _rebuild_tutorial_index()
                TUTORIAL_JOBS[job_id] = {
                    "status": "done",
                    "message": f"Ingested ({payload.get('segment_count', 0)} segments, domain={payload.get('domain', '?')})"
                               + (", distilled + index updated" if auto_distill and os.environ.get("GOOGLE_API_KEY") else ""),
                    "path": out_path,
                }
            except Exception:
                TUTORIAL_JOBS[job_id] = {"status": "done", "message": "Ingested", "path": ""}
        else:
            err = (result.stderr or result.stdout or "Unknown error")[-1000:]
            TUTORIAL_JOBS[job_id] = {"status": "error", "message": err, "path": ""}
    except subprocess.TimeoutExpired:
        TUTORIAL_JOBS[job_id] = {"status": "error", "message": "Timed out after 30 minutes", "path": ""}
    except Exception as e:
        TUTORIAL_JOBS[job_id] = {"status": "error", "message": str(e), "path": ""}


@app.get("/api/tutorials")
async def list_tutorials():
    """List all ingested tutorials with metadata."""
    out = []
    if TUTORIALS_DIR.exists():
        for md in sorted(TUTORIALS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            if md.name == "INDEX.md":
                continue
            text = md.read_text(encoding="utf-8", errors="replace")
            title = md.stem
            source = ""
            domain = ""
            duration = ""
            has_distilled = "## Distilled Summary" in text
            for line in text.splitlines()[:20]:
                if line.startswith("# "):
                    title = line[2:].strip()
                elif line.startswith("**Source:**"):
                    source = line.split("**Source:**", 1)[1].strip()
                elif line.startswith("**Domain:**"):
                    domain = line.split("**Domain:**", 1)[1].strip()
                elif line.startswith("**Duration:**"):
                    duration = line.split("**Duration:**", 1)[1].strip()
            out.append({
                "file": md.name, "path": str(md), "title": title,
                "source": source, "domain": domain, "duration": duration,
                "size_kb": round(md.stat().st_size / 1024, 1),
                "modified": md.stat().st_mtime,
                "distilled": has_distilled,
            })
    index_exists = (TUTORIALS_DIR / "INDEX.md").exists()
    return {"ok": True, "tutorials": out, "dir": str(TUTORIALS_DIR), "index_exists": index_exists}


@app.post("/api/tutorials/ingest")
async def ingest_tutorial(request: Request):
    """Kick off a tutorial ingestion job (returns job_id for polling)."""
    import asyncio as _asyncio
    import uuid
    body = await request.json()
    url = body.get("url", "").strip()
    file_path = body.get("file", "").strip()
    domain = body.get("domain", "auto")
    model = body.get("model", "base")
    auto_distill = body.get("auto_distill", True)
    if not url and not file_path:
        return {"ok": False, "error": "Provide either url or file"}
    job_id = uuid.uuid4().hex[:12]
    TUTORIAL_JOBS[job_id] = {"status": "running", "message": "Starting…", "path": ""}
    loop = _asyncio.get_event_loop()
    loop.run_in_executor(None, _run_tutorial_ingest, job_id, url or None, file_path or None, domain, model, auto_distill)
    return {"ok": True, "job_id": job_id}


@app.get("/api/tutorials/job/{job_id}")
async def tutorial_job_status(job_id: str):
    job = TUTORIAL_JOBS.get(job_id)
    if job is None:
        return {"ok": False, "error": "unknown job"}
    return {"ok": True, **job}


@app.get("/api/tutorials/content/{filename}")
async def tutorial_content(filename: str):
    """Return the markdown content of one tutorial."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return {"ok": False, "error": "invalid filename"}
    md_path = TUTORIALS_DIR / filename
    if not md_path.exists() or not md_path.is_file():
        return {"ok": False, "error": "not found"}
    return {"ok": True, "filename": filename, "content": md_path.read_text(encoding="utf-8", errors="replace")}


@app.post("/api/tutorials/delete")
async def tutorial_delete(request: Request):
    body = await request.json()
    filename = body.get("filename", "")
    if "/" in filename or "\\" in filename or ".." in filename:
        return {"ok": False, "error": "invalid filename"}
    md_path = TUTORIALS_DIR / filename
    if md_path.exists():
        md_path.unlink()
        _rebuild_tutorial_index()
        return {"ok": True}
    return {"ok": False, "error": "not found"}


@app.post("/api/tutorials/distill")
async def tutorial_distill(request: Request):
    """Run (or re-run) distillation on one tutorial via Gemini."""
    body = await request.json()
    filename = body.get("filename", "")
    if "/" in filename or "\\" in filename or ".." in filename:
        return {"ok": False, "error": "invalid filename"}
    md_path = TUTORIALS_DIR / filename
    if not md_path.exists():
        return {"ok": False, "error": "not found"}
    result = await _distill_tutorial(md_path)
    _rebuild_tutorial_index()
    return result


@app.post("/api/tutorials/reindex")
async def tutorial_reindex():
    """Rebuild INDEX.md from existing distilled summaries."""
    idx = _rebuild_tutorial_index()
    return {"ok": True, "index": str(idx)}


@app.post("/api/tutorials/promote")
async def tutorial_promote(request: Request):
    """Promote a tutorial's distilled summary into a named skill file under
    .claude/skills/godot-task/tutorials/. The task executor can then treat
    it as a first-class reference, loaded when relevant."""
    body = await request.json()
    filename = body.get("filename", "")
    slug = body.get("slug", "").strip().replace(" ", "_").lower()
    if "/" in filename or "\\" in filename or ".." in filename or not slug:
        return {"ok": False, "error": "invalid filename or slug"}
    if not all(c.isalnum() or c in "_-" for c in slug):
        return {"ok": False, "error": "slug must be alphanumeric/_/- only"}
    md_path = TUTORIALS_DIR / filename
    if not md_path.exists():
        return {"ok": False, "error": "tutorial not found"}
    text = md_path.read_text(encoding="utf-8", errors="replace")
    if "## Distilled Summary" not in text:
        return {"ok": False, "error": "tutorial not yet distilled — distill first"}
    _, after = text.split("## Distilled Summary", 1)
    lines = after.splitlines()
    summary_lines = []
    for line in lines[1:]:
        if line.startswith("## "):
            break
        summary_lines.append(line)
    summary = "\n".join(summary_lines).strip()

    # Parse title for the header
    title = md_path.stem
    source = ""
    for line in text.splitlines()[:10]:
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("**Source:**"):
            source = line.split("**Source:**", 1)[1].strip()

    skill_dir = SKILLS_DIR / "godot-task" / "tutorials"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / f"{slug}.md"
    out = [
        f"# {title}",
        "",
        f"**Source:** {source}" if source else "",
        f"**Origin:** Promoted from `memory/tutorials/{filename}`",
        "",
        summary,
        "",
        "---",
        f"*See `memory/tutorials/{filename}` for the full transcript and timestamps.*",
    ]
    skill_path.write_text("\n".join(l for l in out if l is not None), encoding="utf-8")
    return {"ok": True, "skill_path": str(skill_path), "slug": slug}


@app.get("/api/tutorials/check")
async def tutorial_check():
    """Report whether yt-dlp + faster-whisper are installed + Gemini available for distillation."""
    deps = {}
    for mod in ["yt_dlp", "faster_whisper"]:
        try:
            __import__(mod)
            deps[mod] = True
        except ImportError:
            deps[mod] = False
    gemini_ok = bool(os.environ.get("GOOGLE_API_KEY"))
    return {
        "ok": all(deps.values()),
        "deps": deps,
        "gemini_configured": gemini_ok,
        "install_cmd": "pip install yt-dlp faster-whisper" if not all(deps.values()) else "",
    }



# ==========================================================================
# Noxdev Studio integration endpoints
# --------------------------------------------------------------------------
# Thin wrappers over existing logic, returning the {ok, data} | {ok: false, error}
# envelope that Noxdev Studio's GodotsmithHttpClient expects.
# See: C:\code\ai\Noxdev-Studio\packages\providers\src\godotsmith.ts
# ==========================================================================

SERVER_START_TS = time.time()
BUILD_JOBS: dict = {}  # buildId -> {status, artifactPath?, startedAt, finishedAt?}


def _nox_ok(data):
    return {"ok": True, "data": data}


def _nox_err(code: str, message: str, status: int = 500):
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
    )


def _slug_to_project(slug: str) -> dict | None:
    """Resolve a Noxdev project slug to a godotsmith project entry."""
    projects = load_projects()
    slug_norm = slug.strip().lower()
    for p in projects:
        name = str(p.get("name", "")).strip().lower()
        dir_name = Path(p["path"]).name.lower()
        if slug_norm in (name, dir_name, dir_name.replace("-", "").replace("_", "")):
            return p
        if slug_norm == name.replace(" ", "-"):
            return p
    return None


def _detect_engine(path: str) -> dict:
    """Single-directory engine detection. Mirrors scan_projects logic."""
    d = Path(path)
    if not d.exists() or not d.is_dir():
        raise ValueError(f"Not a directory: {path}")

    godot_file = d / "project.godot"
    unity_dir = d / "ProjectSettings"
    unreal_files = list(d.glob("*.uproject"))

    if godot_file.exists():
        name = None
        version = None
        main_scene = None
        for line in godot_file.read_text(errors="ignore").splitlines():
            if line.startswith("config/name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("application/config/name="):
                name = name or line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("config_version="):
                version = f"config_version={line.split('=', 1)[1].strip()}"
            elif line.startswith("run/main_scene="):
                main_scene = line.split("=", 1)[1].strip().strip('"')
        return {
            "engine": "GODOT",
            "name": name,
            "version": version,
            "configPath": "project.godot",
            "mainScene": main_scene,
        }

    if unity_dir.exists() and unity_dir.is_dir():
        version = None
        name = None
        vtxt = unity_dir / "ProjectVersion.txt"
        if vtxt.exists():
            for line in vtxt.read_text(errors="ignore").splitlines():
                if line.startswith("m_EditorVersion:"):
                    version = line.split(":", 1)[1].strip()
                    break
        settings = unity_dir / "ProjectSettings.asset"
        if settings.exists():
            for line in settings.read_text(errors="ignore").splitlines():
                stripped = line.strip()
                if stripped.startswith("productName:"):
                    name = stripped.split(":", 1)[1].strip()
                    break
        return {
            "engine": "UNITY",
            "name": name,
            "version": version,
            "configPath": "ProjectSettings/ProjectSettings.asset",
        }

    if unreal_files:
        up = unreal_files[0]
        association = None
        try:
            association = json.loads(up.read_text()).get("EngineAssociation")
        except Exception:
            pass
        return {
            "engine": "UNREAL",
            "name": up.stem,
            "version": association,
            "configPath": up.name,
        }

    raise ValueError(
        "No engine signals found (looked for project.godot, ProjectSettings/, *.uproject)."
    )


@app.get("/api/health")
async def nox_health():
    return _nox_ok({
        "version": "godotsmith-0.1",
        "uptimeSec": int(time.time() - SERVER_START_TS),
    })


@app.get("/api/engine/detect")
async def nox_engine_detect(path: str):
    try:
        data = _detect_engine(path)
    except ValueError as e:
        return _nox_err("invalid_input", str(e), status=400)
    except Exception as e:  # noqa: BLE001
        return _nox_err("upstream_error", str(e), status=500)
    return _nox_ok(data)


@app.get("/api/style-profile")
async def nox_style_profile(project: str):
    entry = _slug_to_project(project)
    if not entry:
        return _nox_err("not_found", f"No project registered with slug '{project}'.", status=404)

    profile = load_style_profile(entry["path"])
    profile_file = _get_style_profile_path(entry["path"])
    return _nox_ok({
        "id": f"sp-{Path(entry['path']).name}",
        "projectSlug": project,
        "answers": profile,
        "updatedAt": datetime.fromtimestamp(profile_file.stat().st_mtime).isoformat()
            if profile_file.exists() else None,
    })


@app.post("/api/build/trigger")
async def nox_build_trigger(request: Request):
    """Register a build intent. Actual export runs via /api/project/export
    (which Godotsmith's UI invokes); this endpoint gives Noxdev Studio a
    handle to track cert/release builds."""
    data = await request.json()
    slug = data.get("projectSlug")
    target = (data.get("target") or "windows").lower()
    channel = (data.get("channel") or "internal").lower()

    entry = _slug_to_project(slug) if slug else None
    if not entry:
        return _nox_err("not_found", f"No project registered with slug '{slug}'.", status=404)

    build_id = f"b-{int(time.time() * 1000)}"
    now = datetime.now().isoformat()
    BUILD_JOBS[build_id] = {
        "status": "queued",
        "startedAt": now,
        "finishedAt": None,
        "artifactPath": None,
        "channel": channel,
        "target": target,
        "projectPath": entry["path"],
    }
    return _nox_ok({
        "buildId": build_id,
        "status": "queued",
        "artifactPath": None,
        "startedAt": now,
        "finishedAt": None,
    })


@app.get("/api/build/{build_id}/status")
async def nox_build_status(build_id: str):
    job = BUILD_JOBS.get(build_id)
    if not job:
        return _nox_err("not_found", f"Build {build_id} not found.", status=404)
    return _nox_ok({
        "buildId": build_id,
        "status": job["status"],
        "artifactPath": job.get("artifactPath"),
        "startedAt": job.get("startedAt"),
        "finishedAt": job.get("finishedAt"),
    })


# --- Run ---

if __name__ == "__main__":
    cfg = load_config()
    save_config(cfg)
    print(f"\n  Godotsmith IDE")
    print(f"  http://localhost:{cfg['port']}")
    print(f"  http://{_get_local_ip()}:{cfg['port']}  (LAN)\n")
    uvicorn.run(app, host=cfg["host"], port=cfg["port"])
