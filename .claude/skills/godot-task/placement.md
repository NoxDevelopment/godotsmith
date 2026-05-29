# Smart Placement — Constraint-Based Scene Building

When a scene builder needs to place N objects with rules (pickups along a path, cover between spawn and enemies, props avoiding each other), brute-forcing random positions fails or produces bad layouts. Use constraint solving.

## Core Helpers (copy into scene builders as needed)

### Poisson-Disc Sampling (2D)
Non-overlapping random placement with minimum spacing. Ideal for pickups, decorations, enemies.

```gdscript
func poisson_disc_2d(area: Rect2, min_distance: float, max_points: int = 100, max_attempts: int = 30) -> Array[Vector2]:
    var points: Array[Vector2] = []
    var active: Array[Vector2] = []
    # Seed with a random starting point
    var start := Vector2(
        area.position.x + randf() * area.size.x,
        area.position.y + randf() * area.size.y,
    )
    points.append(start)
    active.append(start)
    while not active.is_empty() and points.size() < max_points:
        var idx: int = randi() % active.size()
        var base: Vector2 = active[idx]
        var found := false
        for i in max_attempts:
            var angle: float = randf() * TAU
            var radius: float = min_distance * (1.0 + randf())
            var candidate := base + Vector2(cos(angle), sin(angle)) * radius
            if not area.has_point(candidate):
                continue
            var ok := true
            for p in points:
                if candidate.distance_to(p) < min_distance:
                    ok = false
                    break
            if ok:
                points.append(candidate)
                active.append(candidate)
                found = true
                break
        if not found:
            active.remove_at(idx)
    return points
```

Usage:
```gdscript
for pos in poisson_disc_2d(Rect2(0, 0, 1920, 1080), 80.0, 40):
    var pickup = pickup_scene.instantiate()
    pickup.position = pos
    root.add_child(pickup)
```

### Along-Path Placement
Evenly spaced points along a `Curve2D`/`Curve3D` with optional jitter.

```gdscript
func place_along_curve_2d(curve: Curve2D, count: int, jitter: float = 0.0) -> Array[Vector2]:
    var out: Array[Vector2] = []
    var length: float = curve.get_baked_length()
    if length <= 0.0 or count <= 0:
        return out
    for i in count:
        var t: float = (float(i) + 0.5) / float(count)  # center points in segments
        var pos: Vector2 = curve.sample_baked(t * length)
        if jitter > 0.0:
            pos += Vector2(randf_range(-jitter, jitter), randf_range(-jitter, jitter))
        out.append(pos)
    return out
```

### Between-Points (Cover, Obstacles)
Place N items in a line or rectangle between two anchors.

```gdscript
func place_between(start: Vector3, end: Vector3, count: int, spread: float = 2.0) -> Array[Vector3]:
    var out: Array[Vector3] = []
    var axis: Vector3 = (end - start).normalized()
    var perp: Vector3 = axis.cross(Vector3.UP).normalized() if axis != Vector3.UP else Vector3.RIGHT
    for i in count:
        var t: float = (float(i) + 0.5) / float(count)
        var base: Vector3 = start.lerp(end, t)
        out.append(base + perp * randf_range(-spread, spread))
    return out
```

### Grid Placement with Gap Rules
Grid placement where some cells are excluded (obstacle avoidance).

```gdscript
func grid_place(rows: int, cols: int, cell_size: Vector2, origin: Vector2 = Vector2.ZERO,
                excluded_cells: Array = []) -> Array[Vector2]:
    var out: Array[Vector2] = []
    for r in rows:
        for c in cols:
            if [r, c] in excluded_cells:
                continue
            out.append(origin + Vector2(c * cell_size.x, r * cell_size.y))
    return out
```

### Physics-Validated Placement
Drop objects onto terrain using raycasts — ensures they rest on the ground.

```gdscript
func drop_to_surface(world: Node3D, candidates: Array[Vector3], from_height: float = 50.0) -> Array[Vector3]:
    var space: PhysicsDirectSpaceState3D = world.get_world_3d().direct_space_state
    var grounded: Array[Vector3] = []
    for pos in candidates:
        var from := Vector3(pos.x, pos.y + from_height, pos.z)
        var to := Vector3(pos.x, pos.y - from_height, pos.z)
        var query := PhysicsRayQueryParameters3D.create(from, to)
        var hit: Dictionary = space.intersect_ray(query)
        if hit.has("position"):
            grounded.append(hit.position)
    return grounded
# Note: requires the world to already have colliders — run after terrain is built.
```

### Reject-And-Retry (Constraint Satisfaction)
When you have multiple constraints: min distance from "enemies", max distance from "path", on walkable tile, etc.

```gdscript
func find_valid_position(candidate_gen: Callable, constraints: Array[Callable], max_tries: int = 200) -> Variant:
    # candidate_gen: Callable that returns Vector2/Vector3
    # constraints: Array of Callables — each takes the candidate, returns bool
    for i in max_tries:
        var pos = candidate_gen.call()
        var all_ok := true
        for c in constraints:
            if not c.call(pos):
                all_ok = false
                break
        if all_ok:
            return pos
    return null  # couldn't satisfy constraints
```

Usage:
```gdscript
var pos = find_valid_position(
    func(): return Vector2(randf_range(0, 1920), randf_range(0, 1080)),
    [
        func(p: Vector2): return p.distance_to(player_start) > 300.0,
        func(p: Vector2): return p.distance_to(player_start) < 1200.0,
        func(p: Vector2): return p.y < 900.0,
    ]
)
if pos == null:
    push_warning("No valid spawn position found after 200 tries")
```

## Heuristics for Common Patterns

### Cover Shooter — Cover Between Spawn and Sight Lines
```gdscript
# Place cover objects roughly perpendicular to sight-lines from player to enemy clusters
for enemy_group in enemy_groups:
    var mid: Vector3 = (player_start + enemy_group.center) * 0.5
    var sight_dir: Vector3 = (enemy_group.center - player_start).normalized()
    var perp: Vector3 = sight_dir.cross(Vector3.UP).normalized()
    for i in 3:
        var cover_pos: Vector3 = mid + perp * randf_range(-4.0, 4.0) + sight_dir * randf_range(-2.0, 2.0)
        place_cover(cover_pos)
```

### RPG — Loot Density Curve
Fewer high-value items as distance from start decreases (reward for exploration).

```gdscript
func loot_density_at(pos: Vector2, home: Vector2) -> float:
    var dist: float = pos.distance_to(home)
    return clamp((dist - 500.0) / 2000.0, 0.05, 0.8)
```

### Platformer — Reachability Check
Ensure spawned platforms are within jump distance of each other.

```gdscript
const MAX_JUMP_HORIZONTAL := 180.0  # pixels
const MAX_JUMP_VERTICAL := 120.0

func reachable_from(prev: Vector2, next: Vector2) -> bool:
    var dx: float = abs(next.x - prev.x)
    var dy: float = prev.y - next.y  # positive when going up
    return dx <= MAX_JUMP_HORIZONTAL and dy <= MAX_JUMP_VERTICAL
```

## When NOT to Use

- For a single hand-placed hero prop, just set `position` directly.
- For procedural terrain, use `FastNoiseLite` + marching cubes — not constraint placement.
- For UI element positioning, use containers — not this file.

## Validation

After placing, audit via the runtime bridge:
```bash
python "${CLAUDE_SKILL_DIR}/bridge/bridge_client.py" audit
```
Checks for overlapping colliders, null shape resources, non-uniform physics body scales, and geometry at origin.
