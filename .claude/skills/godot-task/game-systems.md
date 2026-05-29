# Game Systems Reference

Production-tested patterns for common game systems. Use these as starting points — adapt parameters to the specific game's feel.

## Save / Load System

### Config-Based (settings, preferences)
```gdscript
# Simple key-value via ConfigFile
var cfg := ConfigFile.new()
cfg.set_value("audio", "master", 0.8)
cfg.save("user://settings.cfg")

cfg.load("user://settings.cfg")
var vol: float = cfg.get_value("audio", "master", 1.0)  # default 1.0
```

### Save Game — Dictionary Serialization
```gdscript
# Autoload — SaveManager
extends Node

const SAVE_PATH := "user://save_%d.dat"
const SAVE_VERSION := 1

signal game_saved(slot: int)
signal game_loaded(slot: int)

func save_game(slot: int = 0) -> bool:
    var data := {
        "version": SAVE_VERSION,
        "timestamp": Time.get_unix_time_from_system(),
        "player": _collect_player_data(),
        "world": _collect_world_data(),
        "inventory": _collect_inventory_data(),
        "quests": _collect_quest_data(),
    }
    var file := FileAccess.open(SAVE_PATH % slot, FileAccess.WRITE)
    if file == null:
        push_error("Failed to open save file: " + str(FileAccess.get_open_error()))
        return false
    file.store_var(data)
    file.close()
    game_saved.emit(slot)
    return true

func load_game(slot: int = 0) -> Dictionary:
    var path: String = SAVE_PATH % slot
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
        data = _migrate_save(data, version)
    game_loaded.emit(slot)
    return data

func _collect_player_data() -> Dictionary:
    var player: Node = get_tree().get_first_node_in_group("player")
    if player == null:
        return {}
    return {
        "position": var_to_str(player.global_position),
        "health": player.current_health,
        "max_health": player.max_health,
        "xp": player.xp,
        "level": player.level,
    }

func _migrate_save(data: Dictionary, from_version: int) -> Dictionary:
    # Progressively upgrade old saves through version transitions
    if from_version < 1:
        data["quests"] = data.get("quests", {})
    return data

func has_save(slot: int) -> bool:
    return FileAccess.file_exists(SAVE_PATH % slot)

func delete_save(slot: int) -> void:
    var path: String = SAVE_PATH % slot
    if FileAccess.file_exists(path):
        DirAccess.remove_absolute(path)
```

### Autosave Pattern
```gdscript
# In SaveManager:
var _autosave_timer: Timer

func _ready() -> void:
    _autosave_timer = Timer.new()
    _autosave_timer.wait_time = 60.0  # every minute
    _autosave_timer.autostart = true
    _autosave_timer.timeout.connect(func(): save_game(99))  # slot 99 = autosave
    add_child(_autosave_timer)
```

## State Machine

Hierarchical node-based state machine — clean, extensible, works for players/enemies/UI:

```gdscript
# Base state class
class_name State
extends Node

signal finished(next_state: StringName, data: Dictionary)

var host: Node  # owning entity

func enter(_data: Dictionary = {}) -> void: pass
func exit() -> void: pass
func handle_input(_event: InputEvent) -> void: pass
func update(_delta: float) -> void: pass
func physics_update(_delta: float) -> void: pass
```

```gdscript
# State machine
class_name StateMachine
extends Node

@export var initial_state: NodePath
var current_state: State
var states: Dictionary[StringName, State] = {}

func _ready() -> void:
    var host: Node = get_parent()
    for child in get_children():
        if child is State:
            states[child.name] = child
            child.host = host
            child.finished.connect(_on_state_finished)
    if initial_state:
        _transition(get_node(initial_state).name, {})

func _input(event: InputEvent) -> void:
    if current_state:
        current_state.handle_input(event)

func _process(delta: float) -> void:
    if current_state:
        current_state.update(delta)

func _physics_process(delta: float) -> void:
    if current_state:
        current_state.physics_update(delta)

func _transition(next: StringName, data: Dictionary) -> void:
    if current_state:
        current_state.exit()
    if next not in states:
        push_warning("State not found: " + str(next))
        return
    current_state = states[next]
    current_state.enter(data)

func _on_state_finished(next: StringName, data: Dictionary) -> void:
    _transition(next, data)
```

```gdscript
# Example state
class_name IdleState
extends State

func enter(_data: Dictionary = {}) -> void:
    host.velocity = Vector2.ZERO
    host.play_animation("idle")

func physics_update(_delta: float) -> void:
    if Input.get_vector("left", "right", "up", "down").length() > 0.1:
        finished.emit(&"Walking", {})
    elif Input.is_action_just_pressed("attack"):
        finished.emit(&"Attacking", {})
```

## Combat — Hitbox / Hurtbox

```gdscript
# Hitbox — emits damage
class_name Hitbox
extends Area2D

@export var damage: int = 10
@export var knockback_force: float = 300.0
@export var team: StringName = &"player"

func _ready() -> void:
    area_entered.connect(_on_area_entered)

func _on_area_entered(area: Area2D) -> void:
    if area is Hurtbox and area.team != team:
        area.take_damage(damage, _get_knockback_direction(area))

func _get_knockback_direction(target: Area2D) -> Vector2:
    return (target.global_position - global_position).normalized() * knockback_force
```

```gdscript
# Hurtbox — receives damage
class_name Hurtbox
extends Area2D

signal damaged(amount: int, knockback: Vector2)

@export var team: StringName = &"enemy"
@export var invincible: bool = false
@export var i_frames_duration: float = 0.5

func take_damage(amount: int, knockback: Vector2) -> void:
    if invincible:
        return
    damaged.emit(amount, knockback)
    _start_i_frames()

func _start_i_frames() -> void:
    invincible = true
    modulate = Color(1, 1, 1, 0.5)
    var timer := get_tree().create_timer(i_frames_duration)
    await timer.timeout
    invincible = false
    modulate = Color.WHITE
```

### Damage Numbers (floating text)
```gdscript
# On hurtbox's damaged signal:
func _on_damaged(amount: int, knockback: Vector2) -> void:
    current_health -= amount
    _spawn_damage_number(amount)
    velocity += knockback
    if current_health <= 0:
        _die()

func _spawn_damage_number(amount: int) -> void:
    var label := Label.new()
    label.text = str(amount)
    label.add_theme_font_size_override("font_size", 24)
    label.add_theme_color_override("font_color", Color.RED)
    label.position = global_position + Vector2(randf_range(-20, 20), -20)
    get_tree().root.add_child(label)
    var tween := create_tween()
    tween.tween_property(label, ^"position:y", label.position.y - 60, 0.8)
    tween.parallel().tween_property(label, ^"modulate:a", 0.0, 0.8).set_delay(0.2)
    tween.tween_callback(label.queue_free)
```

## Inventory System

### Slot-Based Inventory with Stacking
```gdscript
class_name ItemData
extends Resource

@export var id: StringName
@export var display_name: String
@export var icon: Texture2D
@export var max_stack: int = 99
@export var description: String
@export var item_type: StringName = &"misc"  # consumable, weapon, armor, key
@export var value: int = 0  # gold value
@export_multiline var use_script: String = ""  # optional GDScript to eval on use
```

```gdscript
class_name Inventory
extends Resource

signal changed
signal item_added(item: ItemData, count: int)
signal item_removed(item: ItemData, count: int)

@export var slot_count: int = 20
@export var slots: Array[Dictionary] = []  # [{item: ItemData, count: int}, ...]

func _init() -> void:
    if slots.is_empty():
        slots.resize(slot_count)
        for i in slot_count:
            slots[i] = {"item": null, "count": 0}

func add_item(item: ItemData, count: int = 1) -> int:
    var remaining: int = count
    # First pass — fill existing stacks
    for i in slots.size():
        if remaining <= 0:
            break
        var slot: Dictionary = slots[i]
        if slot.item == item and slot.count < item.max_stack:
            var can_add: int = min(remaining, item.max_stack - slot.count)
            slot.count += can_add
            remaining -= can_add
    # Second pass — fill empty slots
    for i in slots.size():
        if remaining <= 0:
            break
        var slot: Dictionary = slots[i]
        if slot.item == null:
            var can_add: int = min(remaining, item.max_stack)
            slot.item = item
            slot.count = can_add
            remaining -= can_add
    var added: int = count - remaining
    if added > 0:
        item_added.emit(item, added)
        changed.emit()
    return remaining  # 0 = all added, >0 = inventory full

func remove_item(item: ItemData, count: int = 1) -> int:
    var remaining: int = count
    for i in slots.size():
        if remaining <= 0:
            break
        var slot: Dictionary = slots[i]
        if slot.item == item:
            var can_remove: int = min(remaining, slot.count)
            slot.count -= can_remove
            remaining -= can_remove
            if slot.count == 0:
                slot.item = null
    var removed: int = count - remaining
    if removed > 0:
        item_removed.emit(item, removed)
        changed.emit()
    return removed

func has_item(item: ItemData, count: int = 1) -> bool:
    var total: int = 0
    for slot in slots:
        if slot.item == item:
            total += slot.count
            if total >= count:
                return true
    return false

func get_count(item: ItemData) -> int:
    var total: int = 0
    for slot in slots:
        if slot.item == item:
            total += slot.count
    return total

func swap_slots(a: int, b: int) -> void:
    var tmp: Dictionary = slots[a]
    slots[a] = slots[b]
    slots[b] = tmp
    changed.emit()
```

### Inventory UI (Drag-and-Drop)
```gdscript
# On each slot (TextureButton):
extends TextureButton

@export var slot_index: int = 0
var inventory: Inventory

func _get_drag_data(_at_position: Vector2) -> Variant:
    var slot: Dictionary = inventory.slots[slot_index]
    if slot.item == null:
        return null
    # Create preview
    var preview := TextureRect.new()
    preview.texture = slot.item.icon
    preview.custom_minimum_size = Vector2(48, 48)
    set_drag_preview(preview)
    return {"from_slot": slot_index, "item": slot.item, "count": slot.count}

func _can_drop_data(_at_position: Vector2, data: Variant) -> bool:
    return data is Dictionary and data.has("from_slot")

func _drop_data(_at_position: Vector2, data: Variant) -> void:
    inventory.swap_slots(data.from_slot, slot_index)
```

## Dialogue System

### Branching Dialogue with Conditions
```gdscript
class_name DialogueNode
extends Resource

@export var speaker: String = ""
@export_multiline var text: String = ""
@export var portrait: Texture2D
@export var choices: Array[DialogueChoice] = []
@export var next_node: DialogueNode  # auto-advance if no choices
@export var on_end: StringName = &""  # signal name to emit
@export_multiline var condition: String = ""  # GDScript expression
```

```gdscript
class_name DialogueChoice
extends Resource

@export var text: String = ""
@export var next: DialogueNode
@export_multiline var condition: String = ""  # only show if true
@export_multiline var action: String = ""     # run when chosen
```

```gdscript
extends Node
## res://scripts/dialogue_manager.gd — Autoload

signal dialogue_started
signal dialogue_ended
signal line_shown(node: DialogueNode)
signal choices_shown(choices: Array[DialogueChoice])

var _current: DialogueNode = null
var _expression := Expression.new()

func start_dialogue(root: DialogueNode) -> void:
    dialogue_started.emit()
    _advance(root)

func _advance(node: DialogueNode) -> void:
    if node == null:
        dialogue_ended.emit()
        return
    if not node.condition.is_empty() and not _eval(node.condition):
        _advance(node.next_node)
        return
    _current = node
    line_shown.emit(node)
    var valid_choices: Array[DialogueChoice] = []
    for c in node.choices:
        if c.condition.is_empty() or _eval(c.condition):
            valid_choices.append(c)
    if valid_choices.size() > 0:
        choices_shown.emit(valid_choices)
    elif node.next_node != null:
        pass  # player continues via UI

func continue_dialogue() -> void:
    if _current == null:
        return
    _advance(_current.next_node)

func choose(choice: DialogueChoice) -> void:
    if not choice.action.is_empty():
        _eval(choice.action)
    _advance(choice.next)

func _eval(script: String) -> Variant:
    var err: int = _expression.parse(script, ["player", "flags"])
    if err != OK:
        push_error("Dialogue expression error: " + _expression.get_error_text())
        return null
    return _expression.execute([_get_player(), _get_flags()])

func _get_player() -> Node:
    return get_tree().get_first_node_in_group("player")

func _get_flags() -> Dictionary:
    var gm: Node = get_tree().get_first_node_in_group("game_manager")
    return gm.flags if gm else {}
```

## Economy / Shops

```gdscript
class_name Wallet
extends Resource

signal changed(new_total: int, delta: int)

@export var balance: int = 0

func can_afford(amount: int) -> bool:
    return balance >= amount

func spend(amount: int) -> bool:
    if not can_afford(amount):
        return false
    balance -= amount
    changed.emit(balance, -amount)
    return true

func deposit(amount: int) -> void:
    balance += amount
    changed.emit(balance, amount)
```

```gdscript
class_name Shop
extends Node

signal purchased(item: ItemData, cost: int)

@export var inventory: Array[Dictionary] = []  # [{item: ItemData, stock: int, price_mult: float}]
@export var buyback_multiplier: float = 0.5

var wallet: Wallet
var player_inv: Inventory

func buy(item: ItemData) -> bool:
    for entry in inventory:
        if entry.item == item and entry.stock > 0:
            var cost: int = int(item.value * entry.get("price_mult", 1.0))
            if not wallet.spend(cost):
                return false
            entry.stock -= 1
            player_inv.add_item(item, 1)
            purchased.emit(item, cost)
            return true
    return false

func sell(item: ItemData) -> bool:
    if not player_inv.has_item(item):
        return false
    player_inv.remove_item(item, 1)
    var price: int = int(item.value * buyback_multiplier)
    wallet.deposit(price)
    return true
```

### Loot Tables (Weighted Random)
```gdscript
class_name LootTable
extends Resource

@export var entries: Array[Dictionary] = []  # [{item: ItemData, weight: int, min: int, max: int}]

func roll() -> Dictionary:
    var total_weight: int = 0
    for e in entries:
        total_weight += e.weight
    var roll_val: int = randi() % total_weight
    var cumulative: int = 0
    for e in entries:
        cumulative += e.weight
        if roll_val < cumulative:
            var count: int = randi_range(e.get("min", 1), e.get("max", 1))
            return {"item": e.item, "count": count}
    return {}

func roll_multiple(count: int) -> Array[Dictionary]:
    var results: Array[Dictionary] = []
    for i in count:
        results.append(roll())
    return results
```

## Wave / Spawn System

```gdscript
class_name WaveSpawner
extends Node2D

signal wave_started(wave_num: int)
signal wave_cleared(wave_num: int)
signal all_waves_done

@export var waves: Array[Dictionary] = []
# Format: [{enemies: [{scene: PackedScene, count: int, delay: float}], wave_delay: float}]

var current_wave: int = -1
var _alive_count: int = 0

func start() -> void:
    _next_wave()

func _next_wave() -> void:
    current_wave += 1
    if current_wave >= waves.size():
        all_waves_done.emit()
        return
    var wave: Dictionary = waves[current_wave]
    wave_started.emit(current_wave)
    _alive_count = 0
    for group in wave.enemies:
        for i in group.count:
            _alive_count += 1
            var timer: SceneTreeTimer = get_tree().create_timer(group.delay * i)
            timer.timeout.connect(_spawn_enemy.bind(group.scene))

func _spawn_enemy(scene: PackedScene) -> void:
    var enemy = scene.instantiate()
    enemy.global_position = _pick_spawn_point()
    get_parent().add_child(enemy)
    if enemy.has_signal("died"):
        enemy.died.connect(_on_enemy_died)

func _on_enemy_died() -> void:
    _alive_count -= 1
    if _alive_count <= 0:
        wave_cleared.emit(current_wave)
        var wave: Dictionary = waves[current_wave]
        var timer: SceneTreeTimer = get_tree().create_timer(wave.get("wave_delay", 3.0))
        timer.timeout.connect(_next_wave)

func _pick_spawn_point() -> Vector2:
    var markers: Array[Node] = get_tree().get_nodes_in_group("spawn_points")
    if markers.is_empty():
        return global_position
    return markers[randi() % markers.size()].global_position
```

## Object Pooling (Bullets, Particles, Enemies)

```gdscript
class_name ObjectPool
extends Node

@export var scene: PackedScene
@export var initial_size: int = 20
@export var grow: bool = true

var _available: Array[Node] = []
var _all: Array[Node] = []

func _ready() -> void:
    for i in initial_size:
        _create_one()

func _create_one() -> Node:
    var obj = scene.instantiate()
    add_child(obj)
    obj.set_process(false)
    obj.set_physics_process(false)
    if obj is Node2D:
        obj.visible = false
    elif obj is Node3D:
        obj.visible = false
    _available.append(obj)
    _all.append(obj)
    return obj

func acquire() -> Node:
    if _available.is_empty():
        if grow:
            _create_one()
        else:
            return null
    var obj: Node = _available.pop_back()
    obj.set_process(true)
    obj.set_physics_process(true)
    if obj is Node2D or obj is Node3D:
        obj.visible = true
    return obj

func release(obj: Node) -> void:
    obj.set_process(false)
    obj.set_physics_process(false)
    if obj is Node2D or obj is Node3D:
        obj.visible = false
    if obj not in _available:
        _available.append(obj)
```

## Quest System

```gdscript
class_name Quest
extends Resource

@export var id: StringName
@export var title: String
@export_multiline var description: String
@export var objectives: Array[QuestObjective] = []
@export var prerequisites: Array[StringName] = []
@export var rewards: Dictionary = {}  # {gold: 100, xp: 50, items: [ItemData]}

func is_complete() -> bool:
    for obj in objectives:
        if not obj.complete:
            return false
    return true
```

```gdscript
class_name QuestObjective
extends Resource

@export var description: String
@export var target: StringName  # enemy group, item id, location id
@export var required_count: int = 1
@export var current_count: int = 0
@export var complete: bool = false

func progress(amount: int = 1) -> bool:
    if complete:
        return false
    current_count = min(current_count + amount, required_count)
    if current_count >= required_count:
        complete = true
        return true
    return false
```

```gdscript
# Autoload — QuestManager
extends Node

signal quest_started(quest: Quest)
signal quest_progressed(quest: Quest, objective: QuestObjective)
signal quest_completed(quest: Quest)

var active: Dictionary[StringName, Quest] = {}
var completed: Dictionary[StringName, Quest] = {}

func can_start(quest: Quest) -> bool:
    for prereq in quest.prerequisites:
        if prereq not in completed:
            return false
    return quest.id not in active and quest.id not in completed

func start_quest(quest: Quest) -> bool:
    if not can_start(quest):
        return false
    active[quest.id] = quest
    quest_started.emit(quest)
    return true

func report_event(event_type: StringName, target: StringName, amount: int = 1) -> void:
    # e.g. report_event(&"kill", &"goblin", 1)
    for quest in active.values():
        for obj in quest.objectives:
            if obj.target == target and not obj.complete:
                if obj.progress(amount):
                    quest_progressed.emit(quest, obj)
                    if quest.is_complete():
                        _complete_quest(quest)

func _complete_quest(quest: Quest) -> void:
    active.erase(quest.id)
    completed[quest.id] = quest
    _grant_rewards(quest)
    quest_completed.emit(quest)

func _grant_rewards(quest: Quest) -> void:
    var player: Node = get_tree().get_first_node_in_group("player")
    if "gold" in quest.rewards:
        player.wallet.deposit(quest.rewards.gold)
    if "xp" in quest.rewards:
        player.add_xp(quest.rewards.xp)
    if "items" in quest.rewards:
        for item in quest.rewards.items:
            player.inventory.add_item(item, 1)
```

## Scene Manager (Transitions + Preloading)

```gdscript
# Autoload — SceneManager
extends Node

signal scene_loading(progress: float)
signal scene_loaded(path: String)

var _current: Node = null
var _loading_path: String = ""
var _progress_array: Array = []

func change_scene(path: String, use_transition: bool = true) -> void:
    if use_transition:
        await _fade_out()
    ResourceLoader.load_threaded_request(path)
    _loading_path = path
    set_process(true)

func _process(_delta: float) -> void:
    if _loading_path.is_empty():
        return
    var status: int = ResourceLoader.load_threaded_get_status(_loading_path, _progress_array)
    match status:
        ResourceLoader.THREAD_LOAD_IN_PROGRESS:
            scene_loading.emit(_progress_array[0])
        ResourceLoader.THREAD_LOAD_LOADED:
            var packed: PackedScene = ResourceLoader.load_threaded_get(_loading_path)
            get_tree().change_scene_to_packed(packed)
            scene_loaded.emit(_loading_path)
            _loading_path = ""
            set_process(false)
            await _fade_in()
        ResourceLoader.THREAD_LOAD_FAILED:
            push_error("Scene load failed: " + _loading_path)
            _loading_path = ""
            set_process(false)

func _fade_out() -> void:
    # Implement via CanvasLayer overlay
    pass

func _fade_in() -> void:
    pass
```

## Signal Bus (Global Event System)

For loosely-coupled cross-system events. Use sparingly — prefer direct signal connections when a direct relationship exists.

```gdscript
# Autoload — EventBus
extends Node

# Player lifecycle
signal player_damaged(amount: int, source: Node)
signal player_died
signal player_respawned

# Progression
signal xp_gained(amount: int)
signal level_up(new_level: int)
signal item_picked_up(item: ItemData)

# World events
signal area_entered(area_id: StringName)
signal npc_interacted(npc: Node)

# UI requests
signal show_toast(text: String, color: Color)
signal show_dialog(text: String, callback: Callable)
```

Emit from anywhere: `EventBus.player_damaged.emit(10, self)`
Listen from anywhere: `EventBus.player_damaged.connect(_on_player_damaged)`

## Cooldown / Ability System

```gdscript
class_name Ability
extends Resource

@export var id: StringName
@export var display_name: String
@export var cooldown: float = 1.0
@export var cost: int = 0  # mana/stamina/etc
@export var icon: Texture2D
```

```gdscript
class_name AbilityController
extends Node

signal ability_used(ability: Ability)
signal ability_ready(ability: Ability)

@export var abilities: Array[Ability] = []

var _cooldowns: Dictionary[StringName, float] = {}

func _process(delta: float) -> void:
    for id in _cooldowns.keys():
        _cooldowns[id] -= delta
        if _cooldowns[id] <= 0.0:
            _cooldowns.erase(id)
            var ability: Ability = _find(id)
            if ability:
                ability_ready.emit(ability)

func can_use(id: StringName) -> bool:
    return id not in _cooldowns

func use(id: StringName) -> bool:
    if not can_use(id):
        return false
    var ability: Ability = _find(id)
    if ability == null:
        return false
    _cooldowns[id] = ability.cooldown
    ability_used.emit(ability)
    return true

func get_cooldown_ratio(id: StringName) -> float:
    if id not in _cooldowns:
        return 0.0
    var ability: Ability = _find(id)
    if ability == null:
        return 0.0
    return _cooldowns[id] / ability.cooldown

func _find(id: StringName) -> Ability:
    for a in abilities:
        if a.id == id:
            return a
    return null
```

## Camera Shake (Trauma-Based)

```gdscript
extends Camera2D

var _trauma: float = 0.0
var _trauma_power: float = 2.0  # how quickly shake scales with trauma
var max_offset: Vector2 = Vector2(16, 12)
var max_roll: float = 0.1
var decay: float = 1.5  # per second

func add_trauma(amount: float) -> void:
    _trauma = min(1.0, _trauma + amount)

func _process(delta: float) -> void:
    if _trauma > 0.0:
        _trauma = maxf(_trauma - decay * delta, 0.0)
        var shake_amount: float = pow(_trauma, _trauma_power)
        offset.x = max_offset.x * shake_amount * randf_range(-1, 1)
        offset.y = max_offset.y * shake_amount * randf_range(-1, 1)
        rotation = max_roll * shake_amount * randf_range(-1, 1)
    else:
        offset = Vector2.ZERO
        rotation = 0.0
```

Usage: `$Camera2D.add_trauma(0.5)` on damage, explosions, screen impacts.

## Input Buffer (Fighting Game / Platformer)

```gdscript
# Tracks recent input for combos and lenient timing (coyote time, jump buffer)
class_name InputBuffer
extends Node

var _buffer: Array[Dictionary] = []  # [{action: StringName, time: float}]
const BUFFER_DURATION: float = 0.15

func _input(event: InputEvent) -> void:
    for action in InputMap.get_actions():
        if event.is_action_pressed(action):
            _buffer.append({"action": action, "time": Time.get_ticks_msec() / 1000.0})

func _process(_delta: float) -> void:
    var now: float = Time.get_ticks_msec() / 1000.0
    _buffer = _buffer.filter(func(e): return now - e.time < BUFFER_DURATION)

func consume(action: StringName) -> bool:
    for i in range(_buffer.size() - 1, -1, -1):
        if _buffer[i].action == action:
            _buffer.remove_at(i)
            return true
    return false

# Usage: if input_buffer.consume(&"jump") and is_on_floor(): jump()
```

## Coyote Time + Jump Buffer (Platformer)

```gdscript
const COYOTE_TIME: float = 0.1  # grace period to jump after leaving ground
const JUMP_BUFFER: float = 0.1  # grace period for early jump presses

var _coyote_timer: float = 0.0
var _jump_buffer_timer: float = 0.0

func _physics_process(delta: float) -> void:
    if is_on_floor():
        _coyote_timer = COYOTE_TIME
    else:
        _coyote_timer = max(0.0, _coyote_timer - delta)

    if Input.is_action_just_pressed("jump"):
        _jump_buffer_timer = JUMP_BUFFER
    else:
        _jump_buffer_timer = max(0.0, _jump_buffer_timer - delta)

    if _jump_buffer_timer > 0.0 and _coyote_timer > 0.0:
        velocity.y = JUMP_VELOCITY
        _jump_buffer_timer = 0.0
        _coyote_timer = 0.0
```
