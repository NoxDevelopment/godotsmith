# Code Quality Reference

Static analysis, naming conventions, signal validation, and anti-patterns to catch problems *before* they hit the test harness.

## Pre-Flight Checks (before running godot)

Before invoking `timeout 60 godot --headless --quit`, scan your generated files for these common issues:

### 1. Signal Map Consistency
For every `signal X` declared in a script, verify:
- Every `.emit()` call passes the correct argument types/count.
- Every `.connect(handler)` points to a handler that exists with matching signature.

```bash
# Find all signals declared:
grep -rn "^signal " scripts/
# Find all emits:
grep -rn "\.emit(" scripts/
# Find all connects:
grep -rn "\.connect(" scripts/
```

For each `signal foo(arg1: T1, arg2: T2)`:
- `foo.emit(...)` must pass exactly 2 args of correct types
- Handler `_on_foo(a: T1, b: T2)` must match

### 2. Autoload References
If STRUCTURE.md lists autoloads like `GameManager`, verify:
- The autoload is registered in `project.godot` under `[autoload]`
- The script path in the autoload config exists
- Scripts reference it by the exact registered name (case-sensitive)

### 3. Input Action Names
Every `Input.is_action_*(name)` call must use an action declared in `project.godot`.

```bash
# Extract all action names referenced:
grep -rhoE 'Input\.is_action_[a-z_]+\("[a-z_]+"\)' scripts/ | grep -oE '"[a-z_]+"'
# Compare to project.godot [input] section
```

### 4. Node Path Validity
`@onready var x: T = $Path/To/Node` requires `Path/To/Node` to exist in the scene at runtime. Check against the scene builder output:
- Every `@onready var x = $Name` means the scene root must have a child named `Name`
- Every `@onready var x = $A/B/C` requires the full chain in the scene tree

### 5. Load Path Existence
Every `load("res://path")` or `preload("res://path")` must resolve:
- `res://scenes/*.tscn` — check that scene builder exists and was run
- `res://scripts/*.gd` — check file exists
- `res://assets/**/*` — check asset was generated

## GDScript Naming Conventions

Follow Godot's official style guide (inspired by PEP 8):

| Element | Convention | Example |
|---------|-----------|---------|
| File names | snake_case.gd | `player_controller.gd` |
| Classes (class_name) | PascalCase | `class_name PlayerController` |
| Functions | snake_case | `func take_damage()` |
| Variables | snake_case | `var current_health` |
| Private members | _underscore_prefix | `var _internal_state` |
| Signals | past_tense snake_case | `signal health_changed` |
| Signal handlers | _on_prefix | `func _on_health_changed()` |
| Constants | UPPER_SNAKE_CASE | `const MAX_SPEED := 10.0` |
| Enums | PascalCase, values UPPER | `enum State { IDLE, RUN }` |
| Node names | PascalCase | `PlayerSprite`, `HealthBar` |
| Input actions | snake_case | `move_forward`, `jump` |
| Groups | snake_case | `add_to_group("enemies")` |

### Auto-Fix Naming Violations

Common violations to auto-fix:
```gdscript
# WRONG → CORRECT
func TakeDamage()         → func take_damage()
var CurrentHealth         → var current_health
signal HealthChanged      → signal health_changed
signal changing_health    → signal health_changed  (past tense)
const max_speed := 10     → const MAX_SPEED := 10
enum state { idle, run }  → enum State { IDLE, RUN }
func on_pressed()         → func _on_pressed()  (signal handler)
```

## Script Structure (Enforced Ordering)

```gdscript
# 1. class_name (optional)
class_name Player

# 2. extends (required)
extends CharacterBody2D

# 3. Documentation
## Player controller — handles movement, combat, and inventory.

# 4. Signals
signal died
signal health_changed(new_hp: int)

# 5. Enums & Constants
enum State { IDLE, MOVING, ATTACKING }
const MAX_SPEED := 300.0

# 6. @export vars
@export var max_health: int = 100
@export var speed: float = 200.0

# 7. @onready vars
@onready var sprite: Sprite2D = $Sprite2D
@onready var anim: AnimationPlayer = $AnimationPlayer

# 8. Public vars
var current_health: int
var current_state: State = State.IDLE

# 9. Private vars
var _input_dir: Vector2
var _attack_cooldown: float = 0.0

# 10. Built-in virtuals (_init, _ready, _process, _physics_process, _input, _exit_tree)
func _ready() -> void: ...
func _physics_process(delta: float) -> void: ...

# 11. Public methods
func take_damage(amount: int) -> void: ...
func heal(amount: int) -> void: ...

# 12. Private methods
func _update_animation() -> void: ...

# 13. Signal handlers (at bottom)
func _on_hurt_box_area_entered(area: Area2D) -> void: ...
```

## Common Anti-Patterns

### AP-1: Polling in `_process()` instead of signals
```gdscript
# WRONG — polls every frame
func _process(_delta: float) -> void:
    if player.health != last_health:
        update_health_bar(player.health)
        last_health = player.health

# CORRECT — signal-driven
func _ready() -> void:
    player.health_changed.connect(update_health_bar)
```

### AP-2: `get_node()` every frame
```gdscript
# WRONG — string lookup per frame
func _process(_delta: float) -> void:
    get_node("HealthBar").value = health

# CORRECT — cached
@onready var health_bar: ProgressBar = $HealthBar
func _process(_delta: float) -> void:
    health_bar.value = health
```

### AP-3: `preload()` of potentially-missing resources
```gdscript
# WRONG — fails at parse time if file doesn't exist yet
const ENEMY_SCENE := preload("res://scenes/enemy.tscn")

# CORRECT — runtime load with null check
var enemy_scene: PackedScene = load("res://scenes/enemy.tscn")
if enemy_scene == null:
    push_error("Failed to load enemy scene")
```

### AP-4: `:=` with polymorphic math
```gdscript
# WRONG — Variant inference fails
var x := abs(velocity.x)
var y := clamp(health, 0, 100)
var z := min(a, b)

# CORRECT — explicit type
var x: float = abs(velocity.x)
var y: int = clamp(health, 0, 100)
var z: float = min(a, b)
```

### AP-5: Signal declared but never emitted (or vice versa)
```gdscript
# WRONG — signal defined but nothing fires it
signal boss_defeated  # searched: never .emit()ed

# CORRECT — either emit it, or remove it
signal boss_defeated
func _on_boss_died() -> void:
    boss_defeated.emit()
```

### AP-6: Connecting to nonexistent signal
```gdscript
# WRONG — compile-time error if signal doesn't exist
button.clicked.connect(_on_clicked)  # Button has `pressed`, not `clicked`

# CORRECT
button.pressed.connect(_on_pressed)
```

### AP-7: `_ready()` sibling timing bug
```gdscript
# WRONG — emitter's _ready() fired before listener connected
func _ready() -> void:
    get_node("../Emitter").ready_signal.connect(_on_ready)

# CORRECT — check if emitter already fired, call handler directly
func _ready() -> void:
    var emitter: Node = get_node("../Emitter")
    emitter.ready_signal.connect(_on_ready)
    if emitter.has_fired:
        _on_ready()
```

### AP-8: Physics mutations in callbacks
```gdscript
# WRONG — "Can't change state while flushing queries"
func _on_body_entered(_body: Node) -> void:
    $CollisionShape2D.disabled = true

# CORRECT — deferred
func _on_body_entered(_body: Node) -> void:
    $CollisionShape2D.set_deferred("disabled", true)
```

### AP-9: Missing `queue_free()` on spawned objects
```gdscript
# WRONG — orphaned nodes accumulate, slow the game
func spawn_particle() -> void:
    var p = particle_scene.instantiate()
    add_child(p)
    # No cleanup! Stays forever.

# CORRECT — auto-cleanup via timer, signal, or VisibleOnScreenNotifier
func spawn_particle() -> void:
    var p = particle_scene.instantiate()
    add_child(p)
    get_tree().create_timer(2.0).timeout.connect(p.queue_free)
```

### AP-10: Hardcoded magic numbers instead of `@export`
```gdscript
# WRONG — designer can't tune without code changes
func _physics_process(delta: float) -> void:
    velocity.x = move_toward(velocity.x, 0, 1000 * delta)

# CORRECT — exposed
@export var deceleration: float = 1000.0
func _physics_process(delta: float) -> void:
    velocity.x = move_toward(velocity.x, 0, deceleration * delta)
```

### AP-11: `get_tree().get_nodes_in_group()` in tight loops
```gdscript
# WRONG — scans entire tree every frame
func _process(_delta: float) -> void:
    for enemy in get_tree().get_nodes_in_group("enemies"):
        check_distance(enemy)

# CORRECT — cache once, update on spawn/death signals
var _enemies: Array[Node] = []
func _ready() -> void:
    _enemies = get_tree().get_nodes_in_group("enemies")
    # Update cache when enemies spawn/die
```

### AP-12: Reference-type mutation surprises
```gdscript
# WRONG — Arrays/Dicts are reference types; this modifies the original!
var original := [1, 2, 3]
var copy = original  # NOT a copy!
copy.append(4)       # original is now [1, 2, 3, 4]

# CORRECT — explicit duplicate
var copy := original.duplicate()      # shallow
var deep := original.duplicate_deep() # recursive (4.5+)
```

### AP-13: Boolean flags for state (use enum)
```gdscript
# WRONG — boolean explosion
var is_jumping := false
var is_falling := false
var is_attacking := false
var is_dashing := false
# Now every check is `if is_jumping and not is_attacking and not is_dashing:`

# CORRECT — enum state
enum State { IDLE, JUMPING, FALLING, ATTACKING, DASHING }
var state: State = State.IDLE
```

### AP-14: Unbounded queue_redraw() in _process
```gdscript
# WRONG — redraws every frame regardless of changes
func _process(_delta: float) -> void:
    queue_redraw()

# CORRECT — only when something changed
func set_value(v: float) -> void:
    if v != _value:
        _value = v
        queue_redraw()
```

### AP-15: Over-reliance on strings for identifiers
```gdscript
# WRONG — typos fail silently
add_to_group("enemie")  # misspelled!
if node.is_in_group("enemie"): ...  # matches typo

# CORRECT — StringName constants
const GROUP_ENEMIES := &"enemies"
add_to_group(GROUP_ENEMIES)
if node.is_in_group(GROUP_ENEMIES): ...
```

## Scene Validation

### Node Name Must Match `@onready`
```bash
# Extract @onready paths from scripts:
grep -rhoE '@onready var [a-z_]+ *: *[A-Za-z0-9_]+ *= *\$[A-Za-z0-9_/]+' scripts/
# Each `$Path` must exist in the scene tree.
```

### Script Attachment Matches `extends`
If `player.gd` says `extends CharacterBody3D`, the node it attaches to in `player.tscn` must be a `CharacterBody3D` (or subclass).

### Signal Wiring in `.tscn`
Signal connections in `.tscn` files look like:
```
[connection signal="pressed" from="Button" to="." method="_on_pressed"]
```
For every such connection, verify the `method` exists in the target script.

## Validation Commands

```bash
# Full parse check — catches syntax, typing, missing classes
timeout 60 godot --headless --quit 2>&1 | grep -E "ERROR|WARNING"

# Import all assets before validating scene loads
timeout 60 godot --headless --import 2>&1

# Validate a specific scene builder produces a valid tscn
timeout 60 godot --headless --script scenes/build_player.gd 2>&1
timeout 60 godot --headless --check-only scripts/player.gd 2>&1

# Count warnings by type (for triage)
godot --headless --quit 2>&1 | grep WARNING | sort | uniq -c | sort -rn
```

## Error Triage

| Error message | Likely cause | Fix |
|---------------|-------------|-----|
| `Parser Error: Expected ...` | Syntax error on indicated line | Read line, fix syntax |
| `Could not resolve class "X"` | Missing `class_name`, typo, or `preload` order | Check spelling; use `load()` instead of `preload()` |
| `Invalid call. Nonexistent function 'X'` | Method doesn't exist on this type | Look up class in `doc_api/` |
| `Cannot infer the type of "x" variable` | `:=` used with Variant-returning function | Use explicit type annotation |
| `The identifier "X" isn't declared in the current scope` | Typo or missing `var` declaration | Declare the variable |
| `Attempt to call function 'X' in base 'Nil'` | `@onready` node missing from scene | Verify scene hierarchy matches script |
| `Condition "!is_inside_tree()" is true` | Accessing tree before `_ready()` | Move code to `_ready()` or later |
| `Can't change state while flushing queries` | Physics mutation in signal callback | Use `set_deferred()` |
| `RID leaked` | Created RID without freeing | Call `*Server.free_rid()` in `_exit_tree()` — benign at scene exit |

## Signal Flow Tracing

To trace a signal chain across files (useful for debugging "why didn't X happen?"):

```bash
# 1. Find where the signal is declared:
grep -rn "^signal target_signal" scripts/

# 2. Find every emit:
grep -rn "target_signal\.emit" scripts/

# 3. Find every connect:
grep -rn "target_signal\.connect" scripts/

# 4. For each connect, find the handler:
#    a.target_signal.connect(b._on_target)
# Then search the receiver's script for _on_target
```

If emits happen but no handler fires, the connection was never established — check `_ready()` timing and whether the receiver was added to the tree before the emitter.

## Dependency Graph

Quick way to map which scripts depend on which:

```bash
# Which scripts reference each other class?
for file in scripts/*.gd; do
    class=$(grep -oE 'class_name [A-Za-z_]+' "$file" | head -1 | awk '{print $2}')
    if [ -n "$class" ]; then
        echo "=== $class (in $file) ==="
        grep -lE "(: *$class|extends $class|$class\.)" scripts/ 2>/dev/null
    fi
done
```

This surfaces circular dependencies — if `A.gd` references `B` and `B.gd` references `A`, extract shared code to a third file or use signals.

## Impact Check Before Changes

When modifying a shared class:
1. `grep -rn "ClassName" scripts/` — find every reference
2. For each file, check whether the change affects its usage
3. If signatures change, update all call sites in one pass
