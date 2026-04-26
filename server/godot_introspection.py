"""Godot project introspection — scene/resource parsers and project-wide analyses.

Consumed by HTTP endpoints in app.py. All functions accept string/Path and return
plain dicts for JSON serialization. No FastAPI, no global state.

Adapted from the ai_assistant_for_godot plugin's introspection tools, reimplemented
as headless parsers so agents can call them over HTTP.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# .tscn / .tres common parsing
# ---------------------------------------------------------------------------

# Match [section_type key="value" key=literal]
_SECTION_RE = re.compile(r"^\[([a-zA-Z_]+)(.*?)\]\s*$")

# Inside a section header, extract k=v pairs (quoted or bare)
_KV_RE = re.compile(r'(\w+)=(?:"([^"]*)"|([^\s\]]+))')

# Inside a section body, match "key = value" (value is the rest of the line)
_BODY_KV_RE = re.compile(r"^([a-zA-Z_][a-zA-Z_0-9/]*)\s*=\s*(.+)$")


def _parse_godot_file(text: str) -> list[dict[str, Any]]:
    """Parse a .tscn or .tres into a list of section dicts.

    Each section: {"type": "node"|"ext_resource"|..., "attrs": {...}, "props": {...}}
    - `attrs` — keys from the section header line.
    - `props` — `key = value` lines in the section body (values left as raw text).
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        header = _SECTION_RE.match(line)
        if header:
            stype = header.group(1)
            attrs = {
                k: (q or b) for k, q, b in _KV_RE.findall(header.group(2))
            }
            current = {"type": stype, "attrs": attrs, "props": {}}
            sections.append(current)
            continue

        if current is None:
            # Lines before any section; skip.
            continue

        body = _BODY_KV_RE.match(line)
        if body:
            current["props"][body.group(1)] = body.group(2).strip()

    return sections


# ---------------------------------------------------------------------------
# Scene parsing — .tscn
# ---------------------------------------------------------------------------

def parse_scene(scene_path: Path) -> dict[str, Any]:
    """Parse a Godot .tscn and return a structured node tree + resource list."""
    scene_path = Path(scene_path)
    if not scene_path.exists():
        return {"error": f"Scene not found: {scene_path}"}
    if scene_path.suffix != ".tscn":
        return {"error": f"Not a .tscn file: {scene_path}"}

    text = scene_path.read_text(errors="replace")
    sections = _parse_godot_file(text)

    ext_resources: list[dict[str, Any]] = []
    sub_resources: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}

    for s in sections:
        stype = s["type"]
        attrs = s["attrs"]
        props = s["props"]

        if stype == "gd_scene":
            meta = dict(attrs)
        elif stype == "ext_resource":
            ext_resources.append({
                "id": attrs.get("id"),
                "type": attrs.get("type"),
                "path": attrs.get("path"),
                "uid": attrs.get("uid"),
            })
        elif stype == "sub_resource":
            sub_resources.append({
                "id": attrs.get("id"),
                "type": attrs.get("type"),
                "props": props,
            })
        elif stype == "node":
            nodes.append({
                "name": attrs.get("name"),
                "type": attrs.get("type") or "",
                "parent": attrs.get("parent", ""),
                "instance": attrs.get("instance"),  # ExtResource(...) ref if instanced
                "groups": attrs.get("groups"),
                "owner": attrs.get("owner"),
                "props": props,
            })

    # Build hierarchy — node's "parent" is "." for root, "NodeName/ChildName" for nested
    tree = _build_node_tree(nodes)

    return {
        "path": str(scene_path),
        "format": meta.get("format"),
        "uid": meta.get("uid"),
        "load_steps": meta.get("load_steps"),
        "ext_resource_count": len(ext_resources),
        "sub_resource_count": len(sub_resources),
        "node_count": len(nodes),
        "ext_resources": ext_resources,
        "sub_resources": sub_resources,
        "nodes_flat": nodes,
        "tree": tree,
    }


def _build_node_tree(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Turn the flat node list into a nested tree rooted at the node with parent unset."""
    # Index by path key — "" for root, "NodeA", "NodeA/NodeB", ...
    by_path: dict[str, dict[str, Any]] = {}
    root: dict[str, Any] | None = None

    for n in nodes:
        parent = n.get("parent")
        if parent in (None, ""):
            # This is the scene root.
            path_key = ""
            node_obj = {
                "name": n["name"],
                "type": n["type"],
                "instance": n.get("instance"),
                "children": [],
            }
            root = node_obj
            by_path[path_key] = node_obj
        else:
            parent_key = parent if parent != "." else ""
            node_obj = {
                "name": n["name"],
                "type": n["type"],
                "instance": n.get("instance"),
                "children": [],
            }
            parent_path = parent_key
            path_key = f"{parent_path}/{n['name']}" if parent_path else n["name"]
            by_path[path_key] = node_obj
            parent_node = by_path.get(parent_path)
            if parent_node is not None:
                parent_node["children"].append(node_obj)

    return root


# ---------------------------------------------------------------------------
# Resource parsing — .tres
# ---------------------------------------------------------------------------

def parse_resource(res_path: Path) -> dict[str, Any]:
    """Parse a .tres and return its metadata + [resource] section props."""
    res_path = Path(res_path)
    if not res_path.exists():
        return {"error": f"Resource not found: {res_path}"}
    if res_path.suffix != ".tres":
        return {"error": f"Not a .tres file: {res_path}"}

    text = res_path.read_text(errors="replace")
    sections = _parse_godot_file(text)

    meta: dict[str, Any] = {}
    ext_resources: list[dict[str, Any]] = []
    sub_resources: list[dict[str, Any]] = []
    resource_props: dict[str, str] = {}

    for s in sections:
        stype = s["type"]
        attrs = s["attrs"]
        props = s["props"]

        if stype == "gd_resource":
            meta = dict(attrs)
        elif stype == "ext_resource":
            ext_resources.append({
                "id": attrs.get("id"),
                "type": attrs.get("type"),
                "path": attrs.get("path"),
                "uid": attrs.get("uid"),
            })
        elif stype == "sub_resource":
            sub_resources.append({
                "id": attrs.get("id"),
                "type": attrs.get("type"),
                "props": props,
            })
        elif stype == "resource":
            resource_props = props

    return {
        "path": str(res_path),
        "type": meta.get("type"),
        "script_class": meta.get("script_class"),
        "uid": meta.get("uid"),
        "format": meta.get("format"),
        "ext_resources": ext_resources,
        "sub_resources": sub_resources,
        "resource_props": resource_props,
    }


# ---------------------------------------------------------------------------
# Project.godot autoload extraction
# ---------------------------------------------------------------------------

def find_autoloads(project_path: Path) -> dict[str, Any]:
    """Extract the [autoload] section from project.godot."""
    project_path = Path(project_path)
    pg = project_path / "project.godot" if project_path.is_dir() else project_path
    if not pg.exists():
        return {"error": f"project.godot not found at {pg}"}

    text = pg.read_text(errors="replace")
    in_autoload = False
    autoloads: dict[str, dict[str, Any]] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_autoload = stripped == "[autoload]"
            continue
        if in_autoload and "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip('"')
            # Godot prefixes enabled autoloads with "*"
            enabled = value.startswith("*")
            if enabled:
                value = value[1:]
            autoloads[key] = {"path": value, "enabled": enabled}

    return {
        "project": str(pg),
        "count": len(autoloads),
        "autoloads": autoloads,
    }


# ---------------------------------------------------------------------------
# Dependency scan — what references a given file
# ---------------------------------------------------------------------------

_RES_PATH_RE = re.compile(r'res://[^\s"\']+')


def get_dependencies(project_path: Path, target: str) -> dict[str, Any]:
    """Find all files in the project that reference `target`.

    `target` is a res:// path or a file path relative to project root. Returns
    a list of referencing files with occurrence counts.
    """
    project_path = Path(project_path)
    if not project_path.is_dir():
        return {"error": f"Not a directory: {project_path}"}

    # Normalize target to `res://...` form
    if not target.startswith("res://"):
        target = "res://" + target.replace("\\", "/").lstrip("/")

    refs: list[dict[str, Any]] = []
    scan_exts = {".tscn", ".tres", ".gd", ".gdshader", ".cfg"}

    for f in project_path.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in scan_exts:
            continue
        # Skip godot cache / editor dirs
        rel = f.relative_to(project_path)
        if any(part.startswith(".") for part in rel.parts):
            continue

        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue

        if target in text:
            count = text.count(target)
            refs.append({
                "file": str(rel).replace("\\", "/"),
                "count": count,
            })

    return {
        "target": target,
        "reference_count": len(refs),
        "references": sorted(refs, key=lambda r: (-r["count"], r["file"])),
    }


# ---------------------------------------------------------------------------
# GDScript file summaries
# ---------------------------------------------------------------------------

_CLASS_NAME_RE = re.compile(r"^\s*class_name\s+([A-Za-z_][A-Za-z_0-9]*)")
_EXTENDS_RE = re.compile(r"^\s*extends\s+(.+?)\s*$")
_SIGNAL_RE = re.compile(r"^\s*signal\s+([A-Za-z_][A-Za-z_0-9]*)\s*(\(.*\))?")
_FUNC_RE = re.compile(
    r"^\s*(?:static\s+)?func\s+([A-Za-z_][A-Za-z_0-9]*)\s*\((.*?)\)\s*(?:->\s*(.+?))?\s*:"
)
_VAR_RE = re.compile(
    r"^\s*(?:@export(?:_[a-z]+)?(?:\([^)]*\))?\s+)*(var|const)\s+([A-Za-z_][A-Za-z_0-9]*)"
)


def summarize_gdscript(script_path: Path) -> dict[str, Any]:
    """Return a cheap structural summary of a .gd file without reading the full body."""
    script_path = Path(script_path)
    if not script_path.exists() or script_path.suffix != ".gd":
        return {"error": f"Not a .gd file: {script_path}"}

    class_name: str | None = None
    extends: str | None = None
    signals: list[dict[str, str]] = []
    functions: list[dict[str, str]] = []
    vars_consts: list[dict[str, str]] = []

    try:
        text = script_path.read_text(errors="replace")
    except Exception as e:
        return {"error": str(e)}

    for line in text.splitlines():
        if class_name is None:
            m = _CLASS_NAME_RE.match(line)
            if m:
                class_name = m.group(1)
                continue
        if extends is None:
            m = _EXTENDS_RE.match(line)
            if m:
                extends = m.group(1).strip()
                continue
        m = _SIGNAL_RE.match(line)
        if m:
            signals.append({
                "name": m.group(1),
                "params": (m.group(2) or "()").strip(),
            })
            continue
        m = _FUNC_RE.match(line)
        if m:
            functions.append({
                "name": m.group(1),
                "params": m.group(2).strip(),
                "return": (m.group(3) or "").strip(),
            })
            continue
        m = _VAR_RE.match(line)
        if m:
            vars_consts.append({"kind": m.group(1), "name": m.group(2)})

    return {
        "path": str(script_path),
        "class_name": class_name,
        "extends": extends,
        "signals": signals,
        "functions": functions,
        "vars_consts": vars_consts,
    }


def get_file_summaries(project_path: Path, pattern: str = "**/*.gd") -> dict[str, Any]:
    """Summarize all .gd files matching `pattern` under `project_path`."""
    project_path = Path(project_path)
    if not project_path.is_dir():
        return {"error": f"Not a directory: {project_path}"}

    summaries: list[dict[str, Any]] = []
    for f in project_path.glob(pattern):
        if not f.is_file():
            continue
        if any(part.startswith(".") for part in f.relative_to(project_path).parts):
            continue
        summaries.append(summarize_gdscript(f))

    return {
        "project": str(project_path),
        "pattern": pattern,
        "count": len(summaries),
        "summaries": summaries,
    }


# ---------------------------------------------------------------------------
# Project blueprint — aggregate context dump
# ---------------------------------------------------------------------------

def generate_blueprint(project_path: Path) -> str:
    """Produce a markdown summary of a Godot project for agent context.

    Returns the markdown string. Caller is responsible for persisting to
    `.ai_blueprint.md` if desired.
    """
    project_path = Path(project_path)
    out: list[str] = []
    out.append(f"# Godot Project Blueprint — {project_path.name}")
    out.append("")
    out.append(f"Generated at: `{project_path}`")
    out.append("")

    # Project.godot basic info
    pg = project_path / "project.godot"
    if pg.exists():
        text = pg.read_text(errors="replace")
        cfg_version_match = re.search(r"config/features\s*=\s*PackedStringArray\(([^)]*)\)", text)
        name_match = re.search(r'config/name\s*=\s*"([^"]*)"', text)
        main_scene_match = re.search(r'run/main_scene\s*=\s*"([^"]*)"', text)
        out.append("## Project")
        if name_match:
            out.append(f"- **Name:** {name_match.group(1)}")
        if main_scene_match:
            out.append(f"- **Main scene:** `{main_scene_match.group(1)}`")
        if cfg_version_match:
            out.append(f"- **Features:** {cfg_version_match.group(1).strip()}")
        out.append("")

    # Autoloads
    autos = find_autoloads(project_path)
    if "autoloads" in autos and autos["autoloads"]:
        out.append("## Autoloads")
        for name, info in autos["autoloads"].items():
            state = "[on] " if info["enabled"] else "[off]"
            out.append(f"- {state} **{name}** → `{info['path']}`")
        out.append("")

    # Scene count + listing
    scenes = sorted(project_path.rglob("*.tscn"))
    scenes = [s for s in scenes if not any(p.startswith(".") for p in s.relative_to(project_path).parts)]
    out.append(f"## Scenes ({len(scenes)})")
    for s in scenes[:30]:
        out.append(f"- `{s.relative_to(project_path).as_posix()}`")
    if len(scenes) > 30:
        out.append(f"- _(+{len(scenes) - 30} more)_")
    out.append("")

    # Scripts — summarize
    scripts = sorted(project_path.rglob("*.gd"))
    scripts = [s for s in scripts if not any(p.startswith(".") for p in s.relative_to(project_path).parts)]
    out.append(f"## Scripts ({len(scripts)})")
    classnamed = []
    for s in scripts:
        summary = summarize_gdscript(s)
        if summary.get("class_name"):
            classnamed.append(summary)
    for summary in classnamed[:40]:
        name = summary["class_name"]
        extends = summary.get("extends") or "?"
        rel = Path(summary["path"]).relative_to(project_path).as_posix()
        out.append(f"- **{name}** (extends {extends}) — `{rel}`")
    if len(classnamed) > 40:
        out.append(f"- _(+{len(classnamed) - 40} more classes)_")
    out.append("")

    # Resources
    resources = sorted(project_path.rglob("*.tres"))
    resources = [r for r in resources if not any(p.startswith(".") for p in r.relative_to(project_path).parts)]
    out.append(f"## Resources ({len(resources)})")
    for r in resources[:20]:
        out.append(f"- `{r.relative_to(project_path).as_posix()}`")
    if len(resources) > 20:
        out.append(f"- _(+{len(resources) - 20} more)_")
    out.append("")

    return "\n".join(out)
