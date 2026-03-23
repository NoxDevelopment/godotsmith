# Known Quirks

- **RID leak errors on exit** — headless scene builders always produce these. Harmless; ignore them.
- **`add_to_group()` in scene builders** — groups set at build-time persist in saved .tscn files.
- **MultiMeshInstance3D + GLBs** — does NOT render after pack+save (mesh resource reference lost during serialization). Use individual GLB instances instead.
- **`_ready()` skipped in `_initialize()`** — when running `--script`, `_ready()` on instantiated scene nodes does NOT fire during `_initialize()`. Call `node.generate()` or other init methods manually after `root.add_child()`.
- **`_process()` signature in SceneTree scripts** — must be `func _process(delta: float) -> bool:` (returns bool), not void.
- **Autoloads in SceneTree scripts** — cannot reference autoload singletons by name (compile error). Find them via `root.get_children()` and match by `.name`.
- **`free()` vs `queue_free()` in test harnesses** — `queue_free()` leaves the node in `root.get_children()` until frame end, blocking name reuse. Use `free()` when immediately replacing scenes.
- **Camera2D has no `current` property** — use `make_current()`, and only after the node is in the scene tree.
- **`--write-movie` frame 0** — the first movie frame renders before `_process()` runs. Camera position set in `_process()` won't appear until frame 1. Pre-position the camera in `_initialize()` (via `position`/`rotation_degrees`, NOT `look_at()`) or accept a junk frame 0.
- **`await` during `--write-movie`** — `await get_tree().process_frame` advances the movie frame counter each tick. A single await takes many movie frames, not 1. Use `_init_frames` counter in `_physics_process()` instead of await chains.
- **Collision layer bitmask vs UI index** — `collision_layer` and `collision_mask` are bitmasks in code, NOT UI layer numbers. UI Layer 1 = bitmask 1, Layer 2 = bitmask 2, Layer 3 = bitmask 4, Layer 4 = bitmask 8 (powers of 2). `collision_layer = 4` means UI Layer 3, NOT Layer 4.
- **GLB `material_override` doesn't serialize** — setting `material_override` on GLB-internal MeshInstance3D nodes does NOT persist in .tscn because `set_owner_on_new_nodes()` skips GLB children (has `scene_file_path`). Use procedural ArrayMesh when custom material is required.
- **Camera lerp from origin** — cameras using `lerp()` in `_physics_process()` will visibly swoop from (0,0,0) on the first frame. Use an `_initialized` flag to snap position on the first frame, then lerp on subsequent frames.
- **Chase camera `current` re-assertion** — game cameras that set `current = true` in `_physics_process()` override the test harness camera every frame. Test harnesses must disable the game camera EVERY frame.
- **`CharacterBody3D.MOTION_MODE_FLOATING`** — also needed for 3D non-platformer movement (vehicles on slopes, snowboards). GROUNDED mode's `floor_stop_on_slope` fights slope movement.

## Type Inference Errors

Three common issues — applies in both scene builders and runtime scripts:

```gdscript
# WRONG — load() returns Resource, which has no instantiate():
var scene := load("res://assets/glb/car.glb")
var model := scene.instantiate()  # Error: Resource has no instantiate()

# WRONG — := with instantiate() causes Variant inference error:
var scene: PackedScene = load("res://assets/glb/car.glb")
var model := scene.instantiate()  # Error: Cannot infer type from Variant

# CORRECT — type load() AND use = (not :=) for instantiate():
var scene: PackedScene = load("res://assets/glb/car.glb")
var model = scene.instantiate()  # Works: no type inference attempted

# WRONG — := with array/dictionary element access (returns Variant):
var pos := positions[i]          # Error: Cannot infer type from Variant
var val := my_dict["key"]        # Error: Same problem

# CORRECT — explicit type or untyped:
var pos: Vector3 = positions[i]  # OK
var val = my_dict["key"]         # OK (untyped)
```

## Common Runtime Pitfalls

**init() vs _ready() timing:**
- `init()` / `setup()` called before `add_child()` → `@onready` vars are null. Store params in plain vars, apply to nodes in `_ready()`.
- `@onready var x = $Node if has_node("Node") else null` is unreliable. Declare `var x: Type = null` and resolve in `_ready()` with `get_node_or_null()`.
- `get_path()` is a built-in Node method (returns NodePath). Cannot override — name yours `get_track_path()`, `get_road_path()`, etc.

**Collision state changes in callbacks:**
- Changing collision shape `.disabled` inside `body_entered`/`body_exited` → "Can't change state while flushing queries". Use `set_deferred("disabled", false)`.

**Spawn immunity for revealed items:**
- Items spawned inside an active Area2D (e.g., power-up revealed by explosion) get `area_entered` immediately → destroyed same frame.
- Fix: track `_alive_time` in `_process()`, ignore `area_entered` for ~0.8s (longer than the triggering effect's lifetime).

**Pass-by-value types in functions:**
- `bool`, `int`, `float`, `Vector3`, `AABB`, `Transform3D` etc. are value types — assigning to a parameter inside a function does NOT update the caller's variable. Use Array/Dictionary accumulator for out-parameters:
  ```gdscript
  # WRONG — result never updates caller:
  func collect(node: Node, result: AABB) -> void:
      result = result.merge(child_aabb)  # lost at return
  # CORRECT — use Array accumulator:
  func collect(node: Node, out: Array) -> void:
      out.append(child_aabb)
  ```

**UV tiling double-scaling:**
- Do NOT use world-space UV coords AND `uv1_scale` together — causes extreme Moire. Pick one: world-space UVs with `uv1_scale = Vector3(1,1,1)`, OR normalized UVs with `uv1_scale = Vector3(tiles, tiles, 1)`.

**Material visibility in forward_plus:**
- `StandardMaterial3D` with `no_depth_test = true` + `TRANSPARENCY_ALPHA` → invisible. Use opaque + unshaded for overlays.
- Z-fighting between layered surfaces (road on terrain): offset 0.15-0.30m vertically + `render_priority = 1`.
- `cull_mode = CULL_DISABLED` as safety net on all procedural meshes until winding is confirmed correct.

## Godot 4.4+ Quirks

**Jolt Physics is the default 3D engine (4.4+):**
- New 3D projects use Jolt by default. Existing projects keep their engine setting.
- Jolt provides better stability, performance, and accuracy than GodotPhysics3D.
- CapsuleShape3D recommended over BoxShape3D for objects sliding on trimesh (Jolt handles this better but capsule is still safer).
- `project.godot` should include: `3d/physics_engine="Jolt Physics"` for explicit Jolt selection.

**Typed Dictionaries (4.4+):**
- `Dictionary[String, int]` is now valid. But accessing values still returns Variant — `:=` inference still fails on dict access.

## Godot 4.5+ Quirks

**Variadic functions:**
- Rest parameter type is always `Array` — cannot use `Array[Type]`.
- Cannot unpack/spread arguments on call sites — use `callv()` for dynamic dispatch.

**Abstract classes:**
- `@abstract` classes cannot be instantiated with `.new()` OR attached to nodes in the editor.
- `@abstract` methods must have NO body — subclasses must implement them.
- An `@abstract` class with a mix of abstract and concrete methods works fine.

**Physics interpolation moved to SceneTree (4.5):**
- Physics interpolation is now handled by SceneTree instead of RenderingServer. More reliable for variable-framerate games.

## Godot 4.6 Quirks

**D3D12 is the default renderer on Windows (4.6):**
- New projects on Windows default to Direct3D 12 instead of Vulkan. For headless/CI or explicit Vulkan, set `rendering/rendering_device/driver.windows="vulkan"` in project.godot.
- D3D12 has better driver stability on Windows but slightly different rendering behavior from Vulkan.

**Unique Node IDs (4.6):**
- Nodes now track identity across refactoring. Scenes should be re-saved via "Project > Tools > Upgrade Project Files" to benefit.
- Scene builders creating .tscn files programmatically are unaffected — IDs are assigned on save.

**IK Modifier nodes (4.6):**
- New IK framework: `TwoBoneIK3D`, `FABRIK3D`, `CCDIK3D`, `JacobianIK3D`.
- These are children of Skeleton3D, not standalone nodes.
- They replace the old SkeletonIK3D node (still available but deprecated).

**Glow blending change (4.6):**
- Glow is now applied before tonemapping with Screen as default blend mode. Visual defaults changed from 4.5 — projects migrating may look different.

**pivot_offset_ratio on Control nodes (4.6):**
- Control nodes now use normalized 0-1 pivot coordinates instead of pixel values. Old code setting `pivot_offset` in pixels still works but behavior may differ.
