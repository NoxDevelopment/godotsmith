# Runtime Bridge

Live inspection and control of a running Godot game via TCP. Useful when headless screenshots don't tell you enough — inspect the actual node tree, query properties, call methods, and simulate input against the real running process.

## When to Use

- Screenshots show the bug but you can't tell *why* (wrong property? missing signal wire? null reference?)
- A feature works in isolation but fails when integrated — need to query state mid-run
- You want to script complex input sequences for end-to-end testing
- You need to verify specific state after certain actions (post-condition testing)

For single-frame static captures, keep using the existing headless `--write-movie` pipeline — it's cheaper. Use the bridge when interactive inspection is genuinely needed.

## Installation (per-project, one-time)

1. Copy the addon into the project:
   ```bash
   mkdir -p addons/godotsmith_bridge
   cp "${CLAUDE_SKILL_DIR}/bridge/godotsmith_bridge.gd" addons/godotsmith_bridge/
   cp "${CLAUDE_SKILL_DIR}/bridge/plugin.cfg" addons/godotsmith_bridge/
   ```

2. Register as an autoload in `project.godot`:
   ```ini
   [autoload]
   GodotsmithBridge="*res://addons/godotsmith_bridge/godotsmith_bridge.gd"
   ```

3. Run the game normally. The bridge starts a TCP server on `127.0.0.1:6007` and logs `[bridge] listening on 127.0.0.1:6007`.

## CLI Usage

`bridge_client.py` (in `${CLAUDE_SKILL_DIR}/bridge/`) is a thin Python client.

```bash
BRIDGE="${CLAUDE_SKILL_DIR}/bridge/bridge_client.py"

# Is the game running?
python "$BRIDGE" ping

# Dump the scene tree
python "$BRIDGE" tree               # brief
python "$BRIDGE" tree --full        # with positions, scripts, groups

# Inspect a specific node
python "$BRIDGE" info /root/Main/Player

# Take a screenshot from the running viewport (not headless)
python "$BRIDGE" screenshot --path user://live_shot.png

# Set a property (JSON-encoded value)
python "$BRIDGE" set /root/Main/Player position '[100, 200]'
python "$BRIDGE" set /root/Main/Player visible 'true'

# Call a method
python "$BRIDGE" call /root/Main/Player take_damage '10'
python "$BRIDGE" call /root/Main/Enemy set_target '"player"'

# Simulate input actions
python "$BRIDGE" input jump               # press
python "$BRIDGE" input jump --release     # release

# Simulate mouse click
python "$BRIDGE" mouse 640 360 --button 1          # left-click at (640, 360)
python "$BRIDGE" mouse 640 360 --button 1 --release

# Check FPS / frame count
python "$BRIDGE" fps

# Evaluate a GDScript expression
python "$BRIDGE" eval "Engine.get_frames_drawn()"
python "$BRIDGE" eval "get_tree().get_nodes_in_group('enemies').size()"

# Gracefully quit the running game
python "$BRIDGE" quit
```

## Debugging Workflow

When a visual QA cycle fails and you can't identify the root cause:

1. Keep the game running (don't re-run headless).
2. `tree --full` → confirm expected nodes exist at expected paths.
3. `info /root/Main/Player` → check if properties match expectations (position, visible, script attached).
4. `eval "..."` → verify signal connections, group membership, script state.
5. `call` a method and then screenshot → isolate whether the method works.
6. `input` a sequence and screenshot between steps → find where state diverges.

## Integration Notes

- The bridge only runs when the game is running. A headless `--quit` validation run doesn't need it.
- The bridge autoload adds ~0.5ms per frame overhead. Remove from production builds.
- Port 6007 can be changed by editing `PORT` in `godotsmith_bridge.gd`.
- For CI or remote runs, use SSH port forwarding: `ssh -L 6007:localhost:6007 host`.
- Client closes the connection after each request (stateless). No long-lived connections needed.
