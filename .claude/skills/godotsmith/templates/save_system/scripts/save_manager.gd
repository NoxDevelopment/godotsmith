extends Node
## res://scripts/save_manager.gd — Autoload. Save/load with versioning and migration.
## Register in project.godot:
##   [autoload]
##   SaveManager="*res://scripts/save_manager.gd"

signal game_saved(slot: int)
signal game_loaded(slot: int)

const SAVE_PATH_FMT := "user://save_%d.dat"
const SAVE_VERSION := 1
const AUTOSAVE_SLOT := 99
const AUTOSAVE_INTERVAL := 60.0  # seconds

var _autosave_timer: Timer

func _ready() -> void:
    _autosave_timer = Timer.new()
    _autosave_timer.wait_time = AUTOSAVE_INTERVAL
    _autosave_timer.autostart = false
    _autosave_timer.timeout.connect(func(): save_game(AUTOSAVE_SLOT))
    add_child(_autosave_timer)

func start_autosave() -> void:
    _autosave_timer.start()

func stop_autosave() -> void:
    _autosave_timer.stop()

func save_game(slot: int = 0) -> bool:
    var data := {
        "version": SAVE_VERSION,
        "timestamp": Time.get_unix_time_from_system(),
        "scene": get_tree().current_scene.scene_file_path if get_tree().current_scene else "",
        "player": _collect_player_data(),
        "world": _collect_world_data(),
        "flags": _collect_flags(),
    }
    var file := FileAccess.open(SAVE_PATH_FMT % slot, FileAccess.WRITE)
    if file == null:
        push_error("Save failed: " + error_string(FileAccess.get_open_error()))
        return false
    file.store_var(data)
    file.close()
    game_saved.emit(slot)
    return true

func load_game(slot: int = 0) -> Dictionary:
    var path: String = SAVE_PATH_FMT % slot
    if not FileAccess.file_exists(path):
        return {}
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        return {}
    var data: Variant = file.get_var()
    file.close()
    if typeof(data) != TYPE_DICTIONARY:
        return {}
    var version: int = data.get("version", 0)
    if version < SAVE_VERSION:
        data = _migrate(data, version)
    game_loaded.emit(slot)
    return data

func has_save(slot: int) -> bool:
    return FileAccess.file_exists(SAVE_PATH_FMT % slot)

func delete_save(slot: int) -> void:
    var path: String = SAVE_PATH_FMT % slot
    if FileAccess.file_exists(path):
        DirAccess.remove_absolute(path)

func list_saves() -> Array[Dictionary]:
    var out: Array[Dictionary] = []
    for i in range(0, 100):
        var path: String = SAVE_PATH_FMT % i
        if FileAccess.file_exists(path):
            var file := FileAccess.open(path, FileAccess.READ)
            var data: Variant = file.get_var() if file else null
            file.close()
            if typeof(data) == TYPE_DICTIONARY:
                out.append({"slot": i, "timestamp": data.get("timestamp", 0), "scene": data.get("scene", "")})
    return out

func _collect_player_data() -> Dictionary:
    var player: Node = get_tree().get_first_node_in_group("player")
    if player == null:
        return {}
    var d := {}
    if player is Node3D:
        d["position"] = var_to_str(player.global_position)
    elif player is Node2D:
        d["position"] = var_to_str(player.global_position)
    for prop in ["current_health", "max_health", "xp", "level", "gold"]:
        if prop in player:
            d[prop] = player.get(prop)
    return d

func _collect_world_data() -> Dictionary:
    # Serialize nodes in the "persistent" group that implement save_data()
    var d := {}
    for node in get_tree().get_nodes_in_group("persistent"):
        if node.has_method("save_data"):
            d[str(node.get_path())] = node.save_data()
    return d

func _collect_flags() -> Dictionary:
    var gm: Node = get_tree().get_first_node_in_group("game_manager")
    if gm and "flags" in gm:
        return gm.flags
    return {}

func _migrate(data: Dictionary, from_version: int) -> Dictionary:
    # Progressively upgrade old saves
    if from_version < 1:
        data["flags"] = data.get("flags", {})
    data["version"] = SAVE_VERSION
    return data
