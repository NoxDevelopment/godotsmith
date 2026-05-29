# Path-Scoped Coding Rules

Standards enforced based on where a file lives in the project. When generating code, pick the rules that match the target path.

## `scripts/` (runtime game code)

General rules for all runtime scripts:
- Static typing required on all public function signatures (`func foo(x: int) -> void`)
- `@onready` for child node refs; never call `get_node()` in `_process()`
- Connect signals in `_ready()`, never in scene builders
- Emit signals for state changes; let UI layer listen rather than polling

## `scripts/gameplay/`, `scripts/entities/`, `scripts/ai/`

Hot-path code. Performance-conscious:
- Zero allocations in `_process()` / `_physics_process()` (no `.new()`, no `[]` literals, no `"" + str()`)
- Cache lookups in `_ready()`: groups, node refs, child arrays
- Use `Input.get_vector()` not 4 separate `is_action_pressed()` calls
- No UI references (gameplay should not import Control nodes or call UI methods directly — emit signals instead)
- Pool bullets, particles, damage numbers — see `game-systems.md` ObjectPool
- Data-driven values via `@export` — no magic numbers

## `scripts/ui/`, `scenes/ui/`

- No game state ownership — UI reads from models, writes via signals/commands
- Accessibility: every interactive Control must have `focus_mode = FOCUS_ALL` and valid focus neighbors
- Text on any dynamic-value label must avoid format strings that can fail (`"%d" % null` → runtime error)
- Layout via containers, not manual position/size
- `mouse_filter = MOUSE_FILTER_IGNORE` on non-interactive overlays
- "scalable_text" group membership for text scaling support

## `scripts/core/`, `scripts/autoload/`

Long-lived singletons:
- API stability — methods used across the codebase should not break without cross-codebase updates
- Thread safety when using `WorkerThreadPool` or file I/O
- No scene-specific assumptions — autoloads outlive scene changes
- Idempotent startup — `_ready()` must be safe on reload

## `scripts/network/`, `scripts/multiplayer/`

- Server-authoritative by default
- Validate all RPC inputs — never trust client data
- Version message schemas so old clients fail gracefully
- Use `MultiplayerSynchronizer` / `MultiplayerSpawner` for replicated state
- Rate-limit high-frequency RPCs

## `scenes/`

- Build via `.gd` scene builders (headless), not manual `.tscn` editing
- Root node's script matches scaffold-declared type
- Every Node has a `.name` set (required for predictable `@onready` resolution)
- Collision layers use named constants, not raw bitmasks — `project.godot` `[layer_names]` must define them
- No signal connections in `.tscn` for signals whose receiver script isn't attached at build-time

## `test/`

- Test files named `test_{task_id}.gd`
- Each prints `ASSERT PASS:` or `ASSERT FAIL:` lines to stdout
- Camera pre-positioned in `_initialize()` (frame-0 timing — see `quirks.md`)
- No network calls; no persistent state mutations outside the test's own scene
- Clean up: `free()` scenes before reloading same name

## `assets/`

- Images: `.png` for sprites/UI, `.webp` if compression matters
- Audio: `.ogg` for music/dialogue, `.wav` for short SFX
- 3D: `.glb` with origin at bottom-center (characters) or geometric center (props)
- No source files (`.psd`, `.blend`, `.aseprite`) committed — export and check in the game-ready form
- Filenames: snake_case, no spaces

## `addons/`

- Only battle-tested addons; version-pin via git submodule or explicit version in README
- Don't modify addon code — if a fix is needed, fork upstream or wrap in a thin adapter in `scripts/`

## `export/`

- `.gitignore`d — build artifacts only, never committed
- Regenerated via `tools/build_export.py`

## General Anti-Patterns (any path)

See `code-quality.md` for the full list. Key ones:
- No `preload()` for paths that may not exist at parse time — use `load()`
- No `:=` with polymorphic math functions — use explicit type
- No physics state changes inside `body_entered`/`area_entered` callbacks — use `set_deferred()`
- No `get_tree().get_nodes_in_group()` in `_process()` — cache on spawn/death signals
