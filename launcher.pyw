"""Godotsmith Launcher — Create and manage Godot game projects."""

import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime

# --- Config ---
PROJECTS_ROOT = Path("C:/code/ai")
GODOTSMITH_DIR = Path(__file__).parent
SKILLS_DIR = GODOTSMITH_DIR / ".claude" / "skills"
GAME_CLAUDE_MD = GODOTSMITH_DIR / "game_claude.md"
PROJECTS_FILE = GODOTSMITH_DIR / "projects.json"
GODOT_EXE = "godot"

# --- Project Registry ---

def load_projects() -> list[dict]:
    if PROJECTS_FILE.exists():
        return json.loads(PROJECTS_FILE.read_text())
    return []

def save_projects(projects: list[dict]):
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))

def add_project(name: str, path: str, genre: str, concept: str):
    projects = load_projects()
    # Don't duplicate
    for p in projects:
        if p["path"] == path:
            p["name"] = name
            p["genre"] = genre
            p["concept"] = concept
            p["last_opened"] = datetime.now().isoformat()
            save_projects(projects)
            return
    projects.insert(0, {
        "name": name,
        "path": path,
        "genre": genre,
        "concept": concept,
        "created": datetime.now().isoformat(),
        "last_opened": datetime.now().isoformat(),
    })
    save_projects(projects)

def update_last_opened(path: str):
    projects = load_projects()
    for p in projects:
        if p["path"] == path:
            p["last_opened"] = datetime.now().isoformat()
            break
    save_projects(projects)

# --- Project Creation ---

def publish_project(target_dir: Path, log_func):
    """Copy skills and CLAUDE.md into target project."""
    target_dir.mkdir(parents=True, exist_ok=True)
    skills_target = target_dir / ".claude" / "skills"
    skills_target.mkdir(parents=True, exist_ok=True)

    # Copy skills
    import shutil
    for skill_name in ["godotsmith", "godot-task"]:
        src = SKILLS_DIR / skill_name
        dst = skills_target / skill_name
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            log_func(f"  Copied skill: {skill_name}")

    # Copy CLAUDE.md
    if GAME_CLAUDE_MD.exists():
        shutil.copy2(GAME_CLAUDE_MD, target_dir / "CLAUDE.md")
        log_func("  Created CLAUDE.md")

    # Create .gitignore
    gitignore = target_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".claude\nCLAUDE.md\nassets\nscreenshots\n.godot\n*.import\n")
        log_func("  Created .gitignore")

    # Git init
    if not (target_dir / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(target_dir), capture_output=True)
        log_func("  Initialized git repo")

    log_func(f"Project ready at: {target_dir}")

# --- GUI ---

class GodotsmithLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Godotsmith — Game Forge")
        self.root.geometry("900x700")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)

        # Style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#e0e0ff", background="#1a1a2e")
        style.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#a0a0c0", background="#1a1a2e")
        style.configure("Field.TLabel", font=("Segoe UI", 10), foreground="#c0c0e0", background="#1a1a2e")
        style.configure("TFrame", background="#1a1a2e")
        style.configure("Card.TFrame", background="#16213e")
        style.configure("Accent.TButton", font=("Segoe UI", 11, "bold"), foreground="#1a1a2e", background="#4ecca3")
        style.configure("Action.TButton", font=("Segoe UI", 9), foreground="#1a1a2e", background="#7ec8e3")
        style.configure("Small.TButton", font=("Segoe UI", 9), foreground="#c0c0c0", background="#2a2a4e")
        style.map("Accent.TButton", background=[("active", "#3ba888")])
        style.map("Action.TButton", background=[("active", "#5aa8c3")])

        self._build_ui()
        self._refresh_projects()

    def _build_ui(self):
        # Main container with tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Tab 1: My Projects ---
        self.projects_frame = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.projects_frame, text="  My Projects  ")

        header = ttk.Frame(self.projects_frame, style="TFrame")
        header.pack(fill=tk.X, pady=(10, 5), padx=10)
        ttk.Label(header, text="My Games", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", style="Small.TButton",
                   command=self._refresh_projects).pack(side=tk.RIGHT, padx=5)

        # Project list with scrollbar
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

        # --- Tab 2: New Game ---
        self.new_frame = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.new_frame, text="  New Game  ")

        form_scroll = ttk.Frame(self.new_frame, style="TFrame")
        form_scroll.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        ttk.Label(form_scroll, text="Create a New Game", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 10))

        # Form fields
        self.fields = {}
        self._add_field(form_scroll, "name", "Game Name", "e.g., Asteroid Miner")
        self._add_field(form_scroll, "genre", "Genre", "e.g., top-down RPG, platformer, arcade shooter")
        self._add_field(form_scroll, "concept", "Concept (1-3 sentences)", "Describe your game idea...", height=3)
        self._add_field(form_scroll, "style", "Art Style", "e.g., 16-bit pixel art, low-poly 3D, hand-drawn")
        self._add_field(form_scroll, "mechanics", "Core Mechanics (one per line)", "- movement\n- combat\n- crafting", height=4)
        self._add_field(form_scroll, "player", "Player Character", "What does the player control?")
        self._add_field(form_scroll, "goal", "Win Condition", "How does the player win?")
        self._add_field(form_scroll, "enemies", "Enemies / Obstacles", "What opposes the player?")
        self._add_field(form_scroll, "special", "Special Features (optional)", "Anything unique about your game?", height=2)

        # Buttons
        btn_frame = ttk.Frame(form_scroll, style="TFrame")
        btn_frame.pack(fill=tk.X, pady=15)
        ttk.Button(btn_frame, text="Create Game Project", style="Accent.TButton",
                   command=self._create_project).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="Clear Form", style="Small.TButton",
                   command=self._clear_form).pack(side=tk.LEFT)

        # --- Tab 3: Log ---
        self.log_frame = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.log_frame, text="  Log  ")

        self.log_text = scrolledtext.ScrolledText(self.log_frame, bg="#0a0a1a", fg="#4ecca3",
            font=("Consolas", 10), insertbackground="#4ecca3", wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def _add_field(self, parent, key, label, placeholder="", height=1):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor=tk.W, pady=(8, 2))
        if height > 1:
            widget = tk.Text(parent, height=height, bg="#16213e", fg="#e0e0ff",
                           insertbackground="#4ecca3", font=("Segoe UI", 10),
                           relief=tk.FLAT, padx=8, pady=4)
            widget.insert("1.0", placeholder)
            widget.bind("<FocusIn>", lambda e, w=widget, p=placeholder: self._clear_placeholder(w, p))
        else:
            widget = tk.Entry(parent, bg="#16213e", fg="#e0e0ff",
                            insertbackground="#4ecca3", font=("Segoe UI", 10),
                            relief=tk.FLAT)
            widget.insert(0, placeholder)
            widget.bind("<FocusIn>", lambda e, w=widget, p=placeholder: self._clear_placeholder_entry(w, p))
        widget.pack(fill=tk.X, pady=(0, 2))
        self.fields[key] = widget

    def _clear_placeholder(self, widget, placeholder):
        if widget.get("1.0", "end-1c") == placeholder:
            widget.delete("1.0", tk.END)

    def _clear_placeholder_entry(self, widget, placeholder):
        if widget.get() == placeholder:
            widget.delete(0, tk.END)

    def _get_field(self, key) -> str:
        widget = self.fields[key]
        if isinstance(widget, tk.Text):
            return widget.get("1.0", "end-1c").strip()
        return widget.get().strip()

    def _log(self, msg: str):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def _refresh_projects(self):
        # Clear existing cards
        for widget in self.project_inner.winfo_children():
            widget.destroy()

        projects = load_projects()

        if not projects:
            # Scan for existing projects
            self._scan_for_projects()
            projects = load_projects()

        if not projects:
            ttk.Label(self.project_inner, text="No projects yet. Create one in the 'New Game' tab!",
                     style="Sub.TLabel").pack(pady=20)
            return

        for proj in projects:
            self._add_project_card(proj)

    def _scan_for_projects(self):
        """Auto-discover game projects in PROJECTS_ROOT."""
        projects = load_projects()
        existing_paths = {p["path"] for p in projects}

        for d in PROJECTS_ROOT.iterdir():
            if not d.is_dir():
                continue
            # Check if it has .claude/skills/godotsmith or godot-task
            skills_dir = d / ".claude" / "skills"
            has_godotsmith = (skills_dir / "godotsmith").exists()
            has_godot_task = (skills_dir / "godot-task").exists()
            has_project_godot = (d / "project.godot").exists()

            if (has_godotsmith or has_godot_task or has_project_godot) and str(d) not in existing_paths:
                name = d.name.replace("-", " ").replace("_", " ").title()
                # Try to read game name from project.godot
                pf = d / "project.godot"
                if pf.exists():
                    for line in pf.read_text(errors="ignore").splitlines():
                        if line.startswith("config/name="):
                            name = line.split("=", 1)[1].strip().strip('"')
                            break

                projects.append({
                    "name": name,
                    "path": str(d),
                    "genre": "Unknown",
                    "concept": "",
                    "created": datetime.fromtimestamp(d.stat().st_ctime).isoformat(),
                    "last_opened": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                })

        save_projects(projects)

    def _add_project_card(self, proj: dict):
        card = tk.Frame(self.project_inner, bg="#16213e", padx=12, pady=10,
                       highlightbackground="#2a2a4e", highlightthickness=1)
        card.pack(fill=tk.X, pady=4, padx=4)

        # Top row: name + genre
        top = tk.Frame(card, bg="#16213e")
        top.pack(fill=tk.X)
        tk.Label(top, text=proj["name"], font=("Segoe UI", 13, "bold"),
                fg="#e0e0ff", bg="#16213e").pack(side=tk.LEFT)
        tk.Label(top, text=proj.get("genre", ""),
                font=("Segoe UI", 9), fg="#7ec8e3", bg="#16213e").pack(side=tk.LEFT, padx=10)

        # Path
        tk.Label(card, text=proj["path"], font=("Consolas", 8),
                fg="#606080", bg="#16213e").pack(anchor=tk.W)

        # Concept preview
        concept = proj.get("concept", "")
        if concept:
            preview = concept[:120] + "..." if len(concept) > 120 else concept
            tk.Label(card, text=preview, font=("Segoe UI", 9),
                    fg="#a0a0b0", bg="#16213e", wraplength=700, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 0))

        # Buttons
        btn_row = tk.Frame(card, bg="#16213e")
        btn_row.pack(fill=tk.X, pady=(8, 0))

        path = proj["path"]
        ttk.Button(btn_row, text="Open in Claude Code", style="Accent.TButton",
                   command=lambda p=path: self._open_claude(p)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Open in Godot", style="Action.TButton",
                   command=lambda p=path: self._open_godot(p)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Open Folder", style="Small.TButton",
                   command=lambda p=path: self._open_folder(p)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Run Game (F5)", style="Action.TButton",
                   command=lambda p=path: self._run_game(p)).pack(side=tk.LEFT, padx=(0, 8))

        # Last opened
        last = proj.get("last_opened", "")
        if last:
            try:
                dt = datetime.fromisoformat(last)
                age = (datetime.now() - dt).days
                age_str = "today" if age == 0 else f"{age}d ago"
                tk.Label(btn_row, text=age_str, font=("Segoe UI", 8),
                        fg="#505060", bg="#16213e").pack(side=tk.RIGHT)
            except (ValueError, TypeError):
                pass

    def _create_project(self):
        name = self._get_field("name")
        if not name or name.startswith("e.g."):
            messagebox.showwarning("Missing Name", "Please enter a game name.")
            return

        # Sanitize folder name
        folder_name = name.lower().replace(" ", "-").replace("'", "").replace('"', "")
        for ch in "!@#$%^&*()+=[]{}|\\:;<>,?/~`":
            folder_name = folder_name.replace(ch, "")
        target = PROJECTS_ROOT / folder_name

        if target.exists() and (target / "project.godot").exists():
            if not messagebox.askyesno("Project Exists",
                    f"{target} already exists. Update skills and open it?"):
                return

        # Switch to log tab
        self.notebook.select(self.log_frame)
        self._log(f"Creating project: {name}")
        self._log(f"  Path: {target}")

        # Publish skills
        publish_project(target, self._log)

        # Build the prompt file
        genre = self._get_field("genre")
        concept = self._get_field("concept")
        art_style = self._get_field("style")
        mechanics = self._get_field("mechanics")
        player = self._get_field("player")
        goal = self._get_field("goal")
        enemies = self._get_field("enemies")
        special = self._get_field("special")

        prompt_lines = [f'Make a {genre} game called "{name}".', ""]
        if concept and not concept.startswith("Describe"):
            prompt_lines += [f"**Concept:** {concept}", ""]
        if art_style and not art_style.startswith("e.g."):
            prompt_lines += [f"**Style:** {art_style}", ""]
        if mechanics and not mechanics.startswith("- movement"):
            prompt_lines += ["**Core Mechanics:**", mechanics, ""]
        if player and not player.startswith("What"):
            prompt_lines += [f"**Player:** {player}", ""]
        if goal and not goal.startswith("How"):
            prompt_lines += [f"**Goal:** {goal}", ""]
        if enemies and not enemies.startswith("What"):
            prompt_lines += [f"**Enemies/Obstacles:** {enemies}", ""]
        if special and not special.startswith("Anything"):
            prompt_lines += [f"**Special Features:** {special}", ""]
        prompt_lines += ["**Budget:** local only (use ComfyUI for all image generation)"]

        prompt_text = "\n".join(prompt_lines)
        prompt_file = target / "GAME_PROMPT.md"
        prompt_file.write_text(prompt_text)
        self._log(f"  Wrote game prompt to GAME_PROMPT.md")
        self._log(f"\n--- PROMPT ---\n{prompt_text}\n--- END ---\n")

        # Register project
        add_project(name, str(target), genre, concept if not concept.startswith("Describe") else "")
        self._refresh_projects()

        self._log("Done! Opening in Claude Code...")
        self._log("Once Claude Code opens, type:  /godotsmith")
        self._log("Then paste the contents of GAME_PROMPT.md or just describe your game.")

        # Open Claude Code
        self._open_claude(str(target))

    def _open_claude(self, path: str):
        update_last_opened(path)
        try:
            subprocess.Popen(["cmd", "/c", "start", "cmd", "/k",
                            f"cd /d {path} && claude"], shell=False)
        except Exception as e:
            self._log(f"Error opening Claude Code: {e}")
            # Fallback
            try:
                subprocess.Popen(["cmd", "/c", f"cd /d {path} && start cmd /k claude"], shell=True)
            except Exception as e2:
                self._log(f"Fallback failed: {e2}")
                messagebox.showinfo("Open Manually",
                    f"Open a terminal and run:\n\ncd {path}\nclaude")

    def _open_godot(self, path: str):
        update_last_opened(path)
        project_file = Path(path) / "project.godot"
        if project_file.exists():
            subprocess.Popen([GODOT_EXE, "--editor", "--path", path])
        else:
            messagebox.showinfo("No Project", "No project.godot found. Create the game first with Claude Code.")

    def _run_game(self, path: str):
        project_file = Path(path) / "project.godot"
        if project_file.exists():
            subprocess.Popen([GODOT_EXE, "--path", path])
        else:
            messagebox.showinfo("No Project", "No project.godot found yet.")

    def _open_folder(self, path: str):
        os.startfile(path)

    def _clear_form(self):
        for key, widget in self.fields.items():
            if isinstance(widget, tk.Text):
                widget.delete("1.0", tk.END)
            else:
                widget.delete(0, tk.END)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = GodotsmithLauncher()
    app.run()
