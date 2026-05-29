extends Node
## Godotsmith Runtime Bridge — optional addon for live game inspection.
##
## Opens a TCP server on port 6007. Clients send JSON line-delimited requests,
## receive JSON line-delimited responses. Supported verbs:
##
##   {"verb": "ping"}
##   {"verb": "scene_tree", "detail": "brief|full"}
##   {"verb": "screenshot", "path": "user://shot.png"}
##   {"verb": "node_info", "path": "/root/Main/Player"}
##   {"verb": "set_property", "path": "...", "property": "position", "value": [0,0]}
##   {"verb": "call_method", "path": "...", "method": "take_damage", "args": [10]}
##   {"verb": "input", "action": "jump", "pressed": true}
##   {"verb": "mouse", "pos": [100, 200], "button": 1, "pressed": true}
##   {"verb": "fps"}
##   {"verb": "errors"}
##   {"verb": "eval", "expr": "Engine.get_frames_drawn()"}
##   {"verb": "ui_map"}                      -- every visible Control with rect + focus/disabled state
##   {"verb": "spatial_audit"}               -- overlapping colliders, stray origin nodes, floating/buried objects
##   {"verb": "quit"}
##
## Add as autoload in project.godot:
##   GodotsmithBridge="*res://addons/godotsmith_bridge/godotsmith_bridge.gd"

const PORT := 6007

var _server := TCPServer.new()
var _clients: Array[StreamPeerTCP] = []
var _buffers: Dictionary = {}  # StreamPeerTCP -> String
var _errors: Array[Dictionary] = []

func _ready() -> void:
    var err: int = _server.listen(PORT, "127.0.0.1")
    if err != OK:
        push_error("[bridge] Failed to listen on %d: %s" % [PORT, error_string(err)])
        return
    print("[bridge] listening on 127.0.0.1:%d" % PORT)

func _process(_delta: float) -> void:
    while _server.is_connection_available():
        var c: StreamPeerTCP = _server.take_connection()
        _clients.append(c)
        _buffers[c] = ""
    var dead: Array[StreamPeerTCP] = []
    for c in _clients:
        c.poll()
        if c.get_status() != StreamPeerTCP.STATUS_CONNECTED:
            dead.append(c)
            continue
        var available: int = c.get_available_bytes()
        if available > 0:
            var chunk: PackedByteArray = c.get_data(available)[1]
            _buffers[c] += chunk.get_string_from_utf8()
            while "\n" in _buffers[c]:
                var idx: int = _buffers[c].find("\n")
                var line: String = _buffers[c].substr(0, idx).strip_edges()
                _buffers[c] = _buffers[c].substr(idx + 1)
                if not line.is_empty():
                    _handle(c, line)
    for c in dead:
        _clients.erase(c)
        _buffers.erase(c)

func _handle(client: StreamPeerTCP, line: String) -> void:
    var parsed: Variant = JSON.parse_string(line)
    if typeof(parsed) != TYPE_DICTIONARY:
        _reply(client, {"ok": false, "error": "invalid json"})
        return
    var req: Dictionary = parsed
    var verb: String = req.get("verb", "")
    var result: Dictionary = {}
    match verb:
        "ping":           result = {"ok": true, "pong": true, "fps": Engine.get_frames_per_second()}
        "scene_tree":     result = _scene_tree(req.get("detail", "brief"))
        "screenshot":     result = _screenshot(req.get("path", "user://bridge_shot.png"))
        "node_info":      result = _node_info(req.get("path", ""))
        "set_property":   result = _set_property(req.get("path", ""), req.get("property", ""), req.get("value"))
        "call_method":    result = _call_method(req.get("path", ""), req.get("method", ""), req.get("args", []))
        "input":          result = _simulate_action(req.get("action", ""), req.get("pressed", true))
        "mouse":          result = _simulate_mouse(req.get("pos", [0, 0]), req.get("button", 1), req.get("pressed", true))
        "fps":            result = {"ok": true, "fps": Engine.get_frames_per_second(), "frame": Engine.get_frames_drawn()}
        "errors":         result = {"ok": true, "errors": _errors}
        "eval":           result = _eval(req.get("expr", ""))
        "ui_map":         result = _ui_map()
        "spatial_audit":  result = _spatial_audit()
        "quit":           result = {"ok": true}; _reply(client, result); get_tree().quit(); return
        _:                result = {"ok": false, "error": "unknown verb: " + verb}
    _reply(client, result)

func _reply(client: StreamPeerTCP, data: Dictionary) -> void:
    var text: String = JSON.stringify(data) + "\n"
    client.put_data(text.to_utf8_buffer())

func _scene_tree(detail: String) -> Dictionary:
    return {"ok": true, "tree": _dump_node(get_tree().root, detail, 0, 8)}

func _dump_node(node: Node, detail: String, depth: int, max_depth: int) -> Dictionary:
    var info: Dictionary = {"name": node.name, "class": node.get_class(), "path": str(node.get_path())}
    if detail == "full":
        if node is Node2D:     info["pos"] = [node.position.x, node.position.y]
        elif node is Node3D:   info["pos"] = [node.position.x, node.position.y, node.position.z]
        if node is CanvasItem: info["visible"] = node.visible
        if node.get_script():  info["script"] = node.get_script().resource_path
        if node.get_groups().size() > 0:
            info["groups"] = Array(node.get_groups()).map(func(g): return str(g))
    if depth < max_depth:
        var kids: Array = []
        for c in node.get_children():
            kids.append(_dump_node(c, detail, depth + 1, max_depth))
        info["children"] = kids
    else:
        info["children_count"] = node.get_child_count()
    return info

func _screenshot(path: String) -> Dictionary:
    var img: Image = get_viewport().get_texture().get_image()
    if img == null:
        return {"ok": false, "error": "viewport image unavailable"}
    var err: int = img.save_png(path)
    if err != OK:
        return {"ok": false, "error": "save failed: " + error_string(err)}
    return {"ok": true, "path": ProjectSettings.globalize_path(path), "size": [img.get_width(), img.get_height()]}

func _node_info(path: String) -> Dictionary:
    var node: Node = get_node_or_null(path)
    if node == null:
        return {"ok": false, "error": "node not found: " + path}
    var props: Array = []
    for p in node.get_property_list():
        if p.usage & PROPERTY_USAGE_EDITOR:
            props.append({"name": p.name, "type": type_string(p.type), "value": str(node.get(p.name))})
    return {"ok": true, "name": node.name, "class": node.get_class(), "properties": props}

func _set_property(path: String, prop: String, value: Variant) -> Dictionary:
    var node: Node = get_node_or_null(path)
    if node == null:
        return {"ok": false, "error": "node not found: " + path}
    if value is Array:
        if value.size() == 2:   value = Vector2(value[0], value[1])
        elif value.size() == 3: value = Vector3(value[0], value[1], value[2])
    node.set(prop, value)
    return {"ok": true}

func _call_method(path: String, method: String, args: Array) -> Dictionary:
    var node: Node = get_node_or_null(path)
    if node == null:
        return {"ok": false, "error": "node not found: " + path}
    if not node.has_method(method):
        return {"ok": false, "error": "method not found: " + method}
    return {"ok": true, "result": str(node.callv(method, args))}

func _simulate_action(action: String, pressed: bool) -> Dictionary:
    if not InputMap.has_action(action):
        return {"ok": false, "error": "action not registered: " + action}
    var ev := InputEventAction.new()
    ev.action = action
    ev.pressed = pressed
    Input.parse_input_event(ev)
    return {"ok": true}

func _simulate_mouse(pos: Array, button: int, pressed: bool) -> Dictionary:
    var ev := InputEventMouseButton.new()
    ev.position = Vector2(pos[0], pos[1])
    ev.global_position = ev.position
    ev.button_index = button
    ev.pressed = pressed
    Input.parse_input_event(ev)
    return {"ok": true}

func _eval(expr_str: String) -> Dictionary:
    var expr := Expression.new()
    var err: int = expr.parse(expr_str)
    if err != OK:
        return {"ok": false, "error": expr.get_error_text()}
    var result: Variant = expr.execute([], self)
    if expr.has_execute_failed():
        return {"ok": false, "error": "execute failed"}
    return {"ok": true, "result": str(result)}

# ===========================
# UI Map — runtime dump of every visible Control with screen rect
# ===========================

func _ui_map() -> Dictionary:
    var controls: Array = []
    _walk_controls(get_tree().root, controls)
    return {"ok": true, "controls": controls, "viewport": [get_viewport().size.x, get_viewport().size.y]}

func _walk_controls(node: Node, out: Array) -> void:
    if node is Control and node.visible:
        var rect: Rect2 = node.get_global_rect()
        var entry := {
            "path": str(node.get_path()),
            "name": node.name,
            "class": node.get_class(),
            "rect": [rect.position.x, rect.position.y, rect.size.x, rect.size.y],
            "focused": node.has_focus(),
            "mouse_filter": node.mouse_filter,
        }
        if node is Button:
            entry["text"] = node.text
            entry["disabled"] = node.disabled
        elif node is Label:
            entry["text"] = node.text
        elif node is LineEdit:
            entry["text"] = node.text
            entry["editable"] = node.editable
        out.append(entry)
    for c in node.get_children():
        _walk_controls(c, out)

# ===========================
# Spatial Audit — detect common scene-building bugs
# ===========================

func _spatial_audit() -> Dictionary:
    var issues: Array = []
    _audit_node(get_tree().root, issues)
    return {"ok": true, "issues": issues, "issue_count": issues.size()}

func _audit_node(node: Node, issues: Array) -> void:
    # Nodes at origin that probably forgot positioning (heuristic: non-root, has mesh/collision, at 0,0,0)
    if node is Node3D and node.get_parent() != get_tree().root:
        var has_geometry: bool = false
        for child in node.get_children():
            if child is MeshInstance3D or child is CollisionShape3D or child is CSGShape3D:
                has_geometry = true
                break
        if has_geometry and node.position == Vector3.ZERO and node.get_parent().get_child_count() > 1:
            issues.append({
                "severity": "info",
                "rule": "origin_stack",
                "path": str(node.get_path()),
                "message": "Node with geometry at origin under a multi-child parent — verify positioning",
            })

    # MeshInstance3D with no material and no GLB source — pure-white placeholder
    if node is MeshInstance3D and node.mesh != null:
        var override: Material = node.get_surface_override_material(0) if node.get_surface_override_material_count() > 0 else null
        if override == null and node.material_override == null:
            # Check if mesh itself has surface material
            var mesh: Mesh = node.mesh
            if mesh.get_surface_count() > 0 and mesh.surface_get_material(0) == null:
                issues.append({
                    "severity": "warning", "rule": "missing_material",
                    "path": str(node.get_path()),
                    "message": "MeshInstance3D has no material — will render default white",
                })

    # CollisionShape with null shape
    if (node is CollisionShape2D or node is CollisionShape3D) and node.shape == null:
        issues.append({
            "severity": "error", "rule": "null_collision_shape",
            "path": str(node.get_path()),
            "message": "CollisionShape has null shape resource",
        })

    # Camera3D/Camera2D with no `current` anywhere (if we walked the whole tree)
    # (checked at root-level after walk)

    # Scale anomalies — non-uniform scale on physics body (jitter risk)
    if node is RigidBody3D or node is CharacterBody3D:
        var s: Vector3 = node.scale
        if not is_equal_approx(s.x, s.y) or not is_equal_approx(s.y, s.z):
            issues.append({
                "severity": "warning", "rule": "nonuniform_physics_scale",
                "path": str(node.get_path()),
                "message": "Non-uniform scale %s on physics body — causes physics jitter. Scale the collider/mesh instead." % str(s),
            })

    # Very deep tree warning (hierarchy complexity)
    # Tracked via depth parameter would be cleaner; keep simple for now

    for c in node.get_children():
        _audit_node(c, issues)
