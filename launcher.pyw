"""Godotsmith Launcher — Create, manage, and run Godot game projects with embedded console."""

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from pathlib import Path
from datetime import datetime

import requests

# --- Config ---
CONFIG_FILE = Path(__file__).parent / "launcher_config.json"
PROJECTS_FILE = Path(__file__).parent / "projects.json"
GODOTSMITH_DIR = Path(__file__).parent
SKILLS_DIR = GODOTSMITH_DIR / ".claude" / "skills"
GAME_CLAUDE_MD = GODOTSMITH_DIR / "game_claude.md"

DEFAULT_CONFIG = {
    "projects_root": "C:/code/ai",
    "comfyui_path": "C:/code/ai/localllm_poc/ComfyUI",
    "comfyui_port": 8188,
    "godot_exe": "godot",
    "kokoro_port": 8880,
    "auto_approve": True,
    "claude_model": "opus",
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        # Merge with defaults for any missing keys
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# --- Project Registry ---

def load_projects() -> list[dict]:
    if PROJECTS_FILE.exists():
        return json.loads(PROJECTS_FILE.read_text())
    return []


def save_projects(projects: list[dict]):
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))


def add_project(name: str, path: str, genre: str, concept: str):
    projects = load_projects()
    for p in projects:
        if p["path"] == path:
            p.update({"name": name, "genre": genre, "concept": concept,
                      "last_opened": datetime.now().isoformat()})
            save_projects(projects)
            return
    projects.insert(0, {
        "name": name, "path": path, "genre": genre, "concept": concept,
        "created": datetime.now().isoformat(),
        "last_opened": datetime.now().isoformat(),
    })
    save_projects(projects)


# --- Service Checks ---

def check_service(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        r = requests.get(f"http://{host}:{port}/", timeout=timeout)
        return True
    except Exception:
        try:
            r = requests.get(f"http://{host}:{port}/system_stats", timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False


def start_comfyui(comfyui_path: str, port: int, log_func) -> subprocess.Popen | None:
    main_py = Path(comfyui_path) / "main.py"
    if not main_py.exists():
        log_func(f"[ERROR] ComfyUI not found at {comfyui_path}")
        return None
    log_func(f"[ComfyUI] Starting from {comfyui_path} on port {port}...")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(main_py), "--listen", "0.0.0.0", "--port", str(port)],
            cwd=comfyui_path,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return proc
    except Exception as e:
        log_func(f"[ERROR] Failed to start ComfyUI: {e}")
        return None


# --- Publish ---

def publish_project(target_dir: Path, log_func):
    import shutil
    target_dir.mkdir(parents=True, exist_ok=True)
    skills_target = target_dir / ".claude" / "skills"
    skills_target.mkdir(parents=True, exist_ok=True)

    for skill_name in ["godotsmith", "godot-task"]:
        src = SKILLS_DIR / skill_name
        dst = skills_target / skill_name
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            log_func(f"  Copied skill: {skill_name}")

    if GAME_CLAUDE_MD.exists():
        shutil.copy2(GAME_CLAUDE_MD, target_dir / "CLAUDE.md")
        log_func("  Created CLAUDE.md")

    gitignore = target_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".claude\nCLAUDE.md\nassets\nscreenshots\n.godot\n*.import\n")

    if not (target_dir / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(target_dir), capture_output=True)

    # Write auto-approve settings if configured
    cfg = load_config()
    if cfg.get("auto_approve", False):
        settings_dir = target_dir / ".claude"
        settings_dir.mkdir(exist_ok=True)
        settings = {
            "permissions": {
                "allow": [
                    "Bash(*)",
                    "Read(*)",
                    "Write(*)",
                    "Edit(*)",
                    "Glob(*)",
                    "Grep(*)",
                    "WebFetch(*)",
                    "WebSearch(*)",
                ]
            }
        }
        (settings_dir / "settings.json").write_text(json.dumps(settings, indent=2))
        log_func("  Created .claude/settings.json (auto-approve enabled)")

    log_func(f"  Project ready at: {target_dir}")


# --- GUI ---

class GodotsmithLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Godotsmith — Game Forge")
        self.root.geometry("1050x750")
        self.root.configure(bg="#1a1a2e")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.config = load_config()
        self.comfyui_proc = None
        self.claude_proc = None
        self._console_active = False

        self._setup_styles()
        self._build_ui()
        self._refresh_projects()
        self._check_services()

        # Periodic service check
        self._service_check_loop()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#e0e0ff", background="#1a1a2e")
        style.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#a0a0c0", background="#1a1a2e")
        style.configure("Field.TLabel", font=("Segoe UI", 10), foreground="#c0c0e0", background="#1a1a2e")
        style.configure("Status.TLabel", font=("Segoe UI", 9), foreground="#808090", background="#1a1a2e")
        style.configure("TFrame", background="#1a1a2e")
        style.configure("Card.TFrame", background="#16213e")
        style.configure("Accent.TButton", font=("Segoe UI", 11, "bold"), foreground="#1a1a2e", background="#4ecca3")
        style.configure("Action.TButton", font=("Segoe UI", 9), foreground="#1a1a2e", background="#7ec8e3")
        style.configure("Danger.TButton", font=("Segoe UI", 9), foreground="#ffffff", background="#e74c3c")
        style.configure("Small.TButton", font=("Segoe UI", 9), foreground="#c0c0c0", background="#2a2a4e")
        style.configure("Green.TLabel", font=("Segoe UI", 9, "bold"), foreground="#4ecca3", background="#1a1a2e")
        style.configure("Red.TLabel", font=("Segoe UI", 9, "bold"), foreground="#e74c3c", background="#1a1a2e")
        style.map("Accent.TButton", background=[("active", "#3ba888")])
        style.map("Action.TButton", background=[("active", "#5aa8c3")])
        style.map("Danger.TButton", background=[("active", "#c0392b")])

    def _build_ui(self):
        # Status bar at top
        self._build_status_bar()

        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self._build_projects_tab()
        self._build_new_game_tab()
        self._build_console_tab()
        self._build_settings_tab()

    # --- Status Bar ---

    def _build_status_bar(self):
        bar = ttk.Frame(self.root, style="TFrame")
        bar.pack(fill=tk.X, padx=10, pady=(8, 4))

        ttk.Label(bar, text="Services:", style="Sub.TLabel").pack(side=tk.LEFT, padx=(0, 8))

        # ComfyUI status
        self.comfyui_status = ttk.Label(bar, text="ComfyUI: checking...", style="Status.TLabel")
        self.comfyui_status.pack(side=tk.LEFT, padx=(0, 5))
        self.comfyui_btn = ttk.Button(bar, text="Start", style="Small.TButton",
                                       command=self._toggle_comfyui)
        self.comfyui_btn.pack(side=tk.LEFT, padx=(0, 15))

        # Kokoro status
        self.kokoro_status = ttk.Label(bar, text="Kokoro TTS: checking...", style="Status.TLabel")
        self.kokoro_status.pack(side=tk.LEFT, padx=(0, 5))

        # Godot version
        self.godot_status = ttk.Label(bar, text="Godot: checking...", style="Status.TLabel")
        self.godot_status.pack(side=tk.LEFT, padx=(0, 15))

        # Auto-approve indicator
        self.approve_label = ttk.Label(bar, text="", style="Status.TLabel")
        self.approve_label.pack(side=tk.RIGHT)
        self._update_approve_label()

    def _check_services(self):
        cfg = self.config
        # ComfyUI
        if check_service("localhost", cfg["comfyui_port"]):
            self.comfyui_status.configure(text="ComfyUI: ONLINE", style="Green.TLabel")
            self.comfyui_btn.configure(text="Stop" if self.comfyui_proc else "Running")
        else:
            self.comfyui_status.configure(text="ComfyUI: OFFLINE", style="Red.TLabel")
            self.comfyui_btn.configure(text="Start")

        # Kokoro
        if check_service("localhost", cfg["kokoro_port"]):
            self.kokoro_status.configure(text="Kokoro TTS: ONLINE", style="Green.TLabel")
        else:
            self.kokoro_status.configure(text="Kokoro TTS: offline", style="Status.TLabel")

        # Godot
        try:
            result = subprocess.run([cfg["godot_exe"], "--version"], capture_output=True, text=True, timeout=5)
            ver = result.stdout.strip().split("\n")[0]
            self.godot_status.configure(text=f"Godot: {ver}", style="Green.TLabel")
        except Exception:
            self.godot_status.configure(text="Godot: not found", style="Red.TLabel")

    def _service_check_loop(self):
        self._check_services()
        self.root.after(15000, self._service_check_loop)  # Every 15s

    def _toggle_comfyui(self):
        cfg = self.config
        if check_service("localhost", cfg["comfyui_port"]):
            # Already running — if we started it, stop it
            if self.comfyui_proc:
                self.comfyui_proc.terminate()
                self.comfyui_proc = None
                self._console_log("[ComfyUI] Stopped")
            else:
                self._console_log("[ComfyUI] Running externally — can't stop from here")
        else:
            # Start it
            self.comfyui_proc = start_comfyui(cfg["comfyui_path"], cfg["comfyui_port"], self._console_log)
            if self.comfyui_proc:
                threading.Thread(target=self._read_comfyui_output, daemon=True).start()

        self.root.after(3000, self._check_services)

    def _read_comfyui_output(self):
        if not self.comfyui_proc:
            return
        try:
            for line in self.comfyui_proc.stdout:
                self._console_log(f"[ComfyUI] {line.rstrip()}")
        except Exception:
            pass

    def _update_approve_label(self):
        if self.config.get("auto_approve", False):
            self.approve_label.configure(text="Auto-Approve: ON", style="Green.TLabel")
        else:
            self.approve_label.configure(text="Auto-Approve: off", style="Status.TLabel")

    # --- Projects Tab ---

    def _build_projects_tab(self):
        self.projects_frame = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.projects_frame, text="  My Projects  ")

        header = ttk.Frame(self.projects_frame, style="TFrame")
        header.pack(fill=tk.X, pady=(10, 5), padx=10)
        ttk.Label(header, text="My Games", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Scan for Projects", style="Small.TButton",
                   command=self._scan_and_refresh).pack(side=tk.RIGHT, padx=5)

        list_frame = ttk.Frame(self.projects_frame, style="TFrame")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.project_canvas = tk.Canvas(list_frame, bg="#1a1a2e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.project_canvas.yview)
        self.project_inner = ttk.Frame(self.project_canvas, style="TFrame")
        self.project_inner.bind("<Configure>",
            lambda e: self.project_canvas.configure(scrollregion=self.project_canvas.bbox("all")))
        self.project_canvas.create_window((0, 0), window=self.project_inner, anchor="nw")
        self.project_canvas.configure(yscrollcommand=scrollbar.set)
        self.project_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _refresh_projects(self):
        for widget in self.project_inner.winfo_children():
            widget.destroy()

        projects = load_projects()
        if not projects:
            self._scan_for_projects()
            projects = load_projects()

        if not projects:
            ttk.Label(self.project_inner, text="No projects yet. Create one in the 'New Game' tab!",
                     style="Sub.TLabel").pack(pady=20)
            return

        for proj in projects:
            self._add_project_card(proj)

    def _scan_and_refresh(self):
        self._scan_for_projects()
        self._refresh_projects()

    def _scan_for_projects(self):
        projects = load_projects()
        existing_paths = {p["path"] for p in projects}
        root = Path(self.config["projects_root"])
        if not root.exists():
            return

        for d in root.iterdir():
            if not d.is_dir() or str(d) in existing_paths:
                continue
            has_skills = (d / ".claude" / "skills" / "godotsmith").exists() or (d / ".claude" / "skills" / "godot-task").exists()
            has_godot = (d / "project.godot").exists()
            if not (has_skills or has_godot):
                continue

            name = d.name.replace("-", " ").replace("_", " ").title()
            pf = d / "project.godot"
            if pf.exists():
                for line in pf.read_text(errors="ignore").splitlines():
                    if line.startswith("config/name="):
                        name = line.split("=", 1)[1].strip().strip('"')
                        break

            projects.append({
                "name": name, "path": str(d), "genre": "", "concept": "",
                "created": datetime.fromtimestamp(d.stat().st_ctime).isoformat(),
                "last_opened": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
            })
        save_projects(projects)

    def _add_project_card(self, proj: dict):
        card = tk.Frame(self.project_inner, bg="#16213e", padx=12, pady=10,
                       highlightbackground="#2a2a4e", highlightthickness=1)
        card.pack(fill=tk.X, pady=4, padx=4)

        top = tk.Frame(card, bg="#16213e")
        top.pack(fill=tk.X)
        tk.Label(top, text=proj["name"], font=("Segoe UI", 13, "bold"),
                fg="#e0e0ff", bg="#16213e").pack(side=tk.LEFT)
        if proj.get("genre"):
            tk.Label(top, text=proj["genre"], font=("Segoe UI", 9),
                    fg="#7ec8e3", bg="#16213e").pack(side=tk.LEFT, padx=10)

        tk.Label(card, text=proj["path"], font=("Consolas", 8),
                fg="#606080", bg="#16213e").pack(anchor=tk.W)

        concept = proj.get("concept", "")
        if concept:
            preview = concept[:150] + "..." if len(concept) > 150 else concept
            tk.Label(card, text=preview, font=("Segoe UI", 9),
                    fg="#a0a0b0", bg="#16213e", wraplength=800, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 0))

        btn_row = tk.Frame(card, bg="#16213e")
        btn_row.pack(fill=tk.X, pady=(8, 0))

        path = proj["path"]
        ttk.Button(btn_row, text="Open in Claude Code", style="Accent.TButton",
                   command=lambda p=path: self._open_claude_embedded(p)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Godot Editor", style="Action.TButton",
                   command=lambda p=path: self._open_godot(p)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Run Game", style="Action.TButton",
                   command=lambda p=path: self._run_game(p)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Folder", style="Small.TButton",
                   command=lambda p=path: os.startfile(p)).pack(side=tk.LEFT, padx=(0, 8))

    # --- New Game Tab ---

    def _build_new_game_tab(self):
        self.new_frame = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.new_frame, text="  New Game  ")

        # Scrollable form
        canvas = tk.Canvas(self.new_frame, bg="#1a1a2e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.new_frame, orient=tk.VERTICAL, command=canvas.yview)
        form = ttk.Frame(canvas, style="TFrame")
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(form, text="Create a New Game", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 10))

        self.fields = {}
        self._add_field(form, "name", "Game Name *")
        self._add_field(form, "genre", "Genre", "e.g., top-down RPG, platformer, arcade shooter")
        self._add_field(form, "concept", "Concept", "Describe your game in 1-3 sentences...", height=3)
        self._add_field(form, "style", "Art Style", "e.g., 16-bit pixel art, low-poly 3D")
        self._add_field(form, "mechanics", "Core Mechanics (one per line)", "- movement\n- combat", height=4)
        self._add_field(form, "player", "Player Character")
        self._add_field(form, "goal", "Win Condition")
        self._add_field(form, "enemies", "Enemies / Obstacles")
        self._add_field(form, "special", "Special Features (optional)", height=2)

        btn_frame = ttk.Frame(form, style="TFrame")
        btn_frame.pack(fill=tk.X, pady=15)
        ttk.Button(btn_frame, text="Create & Launch", style="Accent.TButton",
                   command=self._create_project).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="Clear", style="Small.TButton",
                   command=self._clear_form).pack(side=tk.LEFT)

    def _add_field(self, parent, key, label, placeholder="", height=1):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor=tk.W, pady=(8, 2))
        if height > 1:
            widget = tk.Text(parent, height=height, bg="#16213e", fg="#e0e0ff",
                           insertbackground="#4ecca3", font=("Segoe UI", 10),
                           relief=tk.FLAT, padx=8, pady=4, width=80)
            if placeholder:
                widget.insert("1.0", placeholder)
                widget.bind("<FocusIn>", lambda e, w=widget, p=placeholder: self._clear_ph(w, p))
        else:
            widget = tk.Entry(parent, bg="#16213e", fg="#e0e0ff",
                            insertbackground="#4ecca3", font=("Segoe UI", 10), relief=tk.FLAT)
            if placeholder:
                widget.insert(0, placeholder)
                widget.bind("<FocusIn>", lambda e, w=widget, p=placeholder: self._clear_ph_entry(w, p))
        widget.pack(fill=tk.X, pady=(0, 2))
        self.fields[key] = widget

    def _clear_ph(self, w, p):
        if w.get("1.0", "end-1c") == p:
            w.delete("1.0", tk.END)

    def _clear_ph_entry(self, w, p):
        if w.get() == p:
            w.delete(0, tk.END)

    def _get_field(self, key) -> str:
        w = self.fields[key]
        return w.get("1.0", "end-1c").strip() if isinstance(w, tk.Text) else w.get().strip()

    def _clear_form(self):
        for w in self.fields.values():
            if isinstance(w, tk.Text):
                w.delete("1.0", tk.END)
            else:
                w.delete(0, tk.END)

    def _create_project(self):
        name = self._get_field("name")
        if not name:
            messagebox.showwarning("Missing Name", "Enter a game name.")
            return

        folder = name.lower().replace(" ", "-")
        for ch in "!@#$%^&*()+=[]{}|\\:;<>,?/~`'\"":
            folder = folder.replace(ch, "")
        target = Path(self.config["projects_root"]) / folder

        self.notebook.select(self.console_frame)
        self._console_log(f"=== Creating: {name} ===")

        publish_project(target, self._console_log)

        # Build prompt
        genre = self._get_field("genre")
        concept = self._get_field("concept")
        parts = [f'/godotsmith\n\nMake a {genre} game called "{name}".']
        for key, label in [("concept", "Concept"), ("style", "Style"), ("mechanics", "Core Mechanics"),
                          ("player", "Player"), ("goal", "Goal"), ("enemies", "Enemies/Obstacles"),
                          ("special", "Special Features")]:
            val = self._get_field(key)
            placeholders = ["e.g.", "Describe", "- movement", "What", "How", "Anything"]
            if val and not any(val.startswith(p) for p in placeholders):
                parts.append(f"\n**{label}:** {val}")
        parts.append("\n**Budget:** local only (use ComfyUI)")
        prompt = "\n".join(parts)

        (target / "GAME_PROMPT.md").write_text(prompt)
        self._console_log(f"\n{prompt}\n")

        add_project(name, str(target), genre,
                   concept if not concept.startswith("Describe") else "")
        self._refresh_projects()

        self._console_log("Launching Claude Code...")
        self._open_claude_embedded(str(target))

    # --- Console Tab ---

    def _build_console_tab(self):
        self.console_frame = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.console_frame, text="  Console  ")

        # Output area
        self.console_text = scrolledtext.ScrolledText(
            self.console_frame, bg="#0a0a1a", fg="#4ecca3",
            font=("Consolas", 10), insertbackground="#4ecca3",
            wrap=tk.WORD, state=tk.NORMAL)
        self.console_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        # Input area
        input_frame = ttk.Frame(self.console_frame, style="TFrame")
        input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.console_input = tk.Entry(input_frame, bg="#16213e", fg="#e0e0ff",
                                      insertbackground="#4ecca3", font=("Consolas", 10),
                                      relief=tk.FLAT)
        self.console_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.console_input.bind("<Return>", self._console_send)

        ttk.Button(input_frame, text="Send", style="Action.TButton",
                   command=self._console_send).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(input_frame, text="Stop", style="Danger.TButton",
                   command=self._console_stop).pack(side=tk.LEFT)

    def _console_log(self, msg: str):
        self.console_text.insert(tk.END, msg + "\n")
        self.console_text.see(tk.END)
        self.root.update_idletasks()

    def _console_send(self, event=None):
        text = self.console_input.get().strip()
        if not text:
            return
        self.console_input.delete(0, tk.END)
        self._console_log(f"> {text}")
        if self.claude_proc and self.claude_proc.stdin:
            try:
                self.claude_proc.stdin.write(text + "\n")
                self.claude_proc.stdin.flush()
            except Exception as e:
                self._console_log(f"[ERROR] {e}")

    def _console_stop(self):
        if self.claude_proc:
            self.claude_proc.terminate()
            self.claude_proc = None
            self._console_active = False
            self._console_log("[Stopped]")

    def _open_claude_embedded(self, path: str):
        """Run Claude Code inside the embedded console."""
        self.notebook.select(self.console_frame)

        if self.claude_proc and self.claude_proc.poll() is None:
            self._console_log("[Already running — stop first or wait]")
            return

        self._console_log(f"\n=== Opening Claude Code in {path} ===")

        cmd = ["claude"]
        cfg = self.config
        if cfg.get("auto_approve", False):
            cmd.append("--dangerously-skip-permissions")
            self._console_log("[Auto-approve enabled]")

        try:
            self.claude_proc = subprocess.Popen(
                cmd, cwd=path,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._console_active = True
            threading.Thread(target=self._read_claude_output, daemon=True).start()
        except FileNotFoundError:
            self._console_log("[ERROR] 'claude' not found. Install Claude Code: npm install -g @anthropic-ai/claude-code")
            # Fallback: open external terminal
            subprocess.Popen(["cmd", "/c", "start", "cmd", "/k",
                            f"cd /d {path} && claude"], shell=False)

    def _read_claude_output(self):
        if not self.claude_proc:
            return
        try:
            for line in self.claude_proc.stdout:
                self.root.after(0, self._console_log, line.rstrip())
        except Exception:
            pass
        self.root.after(0, self._console_log, "[Process ended]")
        self._console_active = False

    # --- Settings Tab ---

    def _build_settings_tab(self):
        self.settings_frame = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.settings_frame, text="  Settings  ")

        form = ttk.Frame(self.settings_frame, style="TFrame")
        form.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        ttk.Label(form, text="Settings", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 15))

        self.setting_vars = {}

        # Path settings
        self._add_path_setting(form, "projects_root", "Projects Root Folder",
                              "Where new game projects are created")
        self._add_path_setting(form, "comfyui_path", "ComfyUI Install Path",
                              "Folder containing ComfyUI main.py")
        self._add_entry_setting(form, "comfyui_port", "ComfyUI Port", "8188")
        self._add_entry_setting(form, "godot_exe", "Godot Executable", "godot")
        self._add_entry_setting(form, "kokoro_port", "Kokoro TTS Port", "8880")
        self._add_entry_setting(form, "claude_model", "Claude Model", "opus")

        # Auto-approve toggle
        ttk.Label(form, text="Auto-Approve Agent Actions", style="Field.TLabel").pack(anchor=tk.W, pady=(15, 2))
        self.auto_approve_var = tk.BooleanVar(value=self.config.get("auto_approve", True))
        approve_frame = ttk.Frame(form, style="TFrame")
        approve_frame.pack(fill=tk.X)
        cb = tk.Checkbutton(approve_frame, text="Skip all permission prompts (--dangerously-skip-permissions)",
                          variable=self.auto_approve_var, bg="#1a1a2e", fg="#c0c0e0",
                          selectcolor="#16213e", activebackground="#1a1a2e",
                          font=("Segoe UI", 10))
        cb.pack(anchor=tk.W)
        ttk.Label(form, text="When enabled, Claude Code runs without stopping for confirmations.\n"
                  "Also writes .claude/settings.json with broad tool permissions into each project.",
                 style="Status.TLabel").pack(anchor=tk.W, pady=(2, 0))

        # Save button
        ttk.Button(form, text="Save Settings", style="Accent.TButton",
                   command=self._save_settings).pack(anchor=tk.W, pady=20)

    def _add_path_setting(self, parent, key, label, hint=""):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor=tk.W, pady=(10, 2))
        frame = ttk.Frame(parent, style="TFrame")
        frame.pack(fill=tk.X)
        var = tk.StringVar(value=self.config.get(key, ""))
        entry = tk.Entry(frame, textvariable=var, bg="#16213e", fg="#e0e0ff",
                        insertbackground="#4ecca3", font=("Segoe UI", 10), relief=tk.FLAT)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(frame, text="Browse", style="Small.TButton",
                   command=lambda v=var: v.set(filedialog.askdirectory(initialdir=v.get()) or v.get())
                   ).pack(side=tk.LEFT)
        if hint:
            ttk.Label(parent, text=hint, style="Status.TLabel").pack(anchor=tk.W)
        self.setting_vars[key] = var

    def _add_entry_setting(self, parent, key, label, default=""):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor=tk.W, pady=(10, 2))
        var = tk.StringVar(value=str(self.config.get(key, default)))
        entry = tk.Entry(parent, textvariable=var, bg="#16213e", fg="#e0e0ff",
                        insertbackground="#4ecca3", font=("Segoe UI", 10), relief=tk.FLAT)
        entry.pack(fill=tk.X)
        self.setting_vars[key] = var

    def _save_settings(self):
        for key, var in self.setting_vars.items():
            val = var.get()
            if key in ("comfyui_port", "kokoro_port"):
                try:
                    val = int(val)
                except ValueError:
                    pass
            self.config[key] = val
        self.config["auto_approve"] = self.auto_approve_var.get()
        save_config(self.config)
        self._update_approve_label()
        self._check_services()
        messagebox.showinfo("Saved", "Settings saved.")

    # --- Actions ---

    def _open_godot(self, path: str):
        pf = Path(path) / "project.godot"
        if pf.exists():
            subprocess.Popen([self.config["godot_exe"], "--editor", "--path", path])
        else:
            messagebox.showinfo("No Project", "No project.godot found. Create the game first.")

    def _run_game(self, path: str):
        pf = Path(path) / "project.godot"
        if pf.exists():
            subprocess.Popen([self.config["godot_exe"], "--path", path])
        else:
            messagebox.showinfo("No Project", "No project.godot found yet.")

    def _on_close(self):
        if self.comfyui_proc:
            self.comfyui_proc.terminate()
        if self.claude_proc:
            self.claude_proc.terminate()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = GodotsmithLauncher()
    app.run()
