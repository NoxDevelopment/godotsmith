# {Game Title} — Game Design Document

## 1. Concept
**Pitch:** {One-sentence hook — "A [genre] where you [core verb] to [goal]".}

**Inspiration:** {1–3 reference games, in what way.}

**Target player:** {Who plays this and why.}

## 2. Core Loop
{What the player does minute-to-minute. Usually 3–5 verbs with a feedback cycle.}

Example:
1. Explore → discover resources
2. Collect → upgrade gear
3. Fight → earn experience
4. Return to step 1 with more power

## 3. Mechanics
| Mechanic | Description | Implementation reference |
|----------|-------------|--------------------------|
| {Name} | {What it does} | {`scripts/...` or pattern from `game-systems.md`} |

## 4. Progression
**Short-term (per session):** {What keeps the player engaged in a single play.}
**Long-term (across sessions):** {What brings them back.}

## 5. Win / Lose Conditions
- **Win:** {Specific, measurable.}
- **Lose:** {Specific, measurable.}
- **Fail-forward:** {What happens on failure — permadeath? retry? meta-progression?}

## 6. World & Characters
{World setting in one paragraph. Named characters in a table.}

| Character | Role | Visual hook |
|-----------|------|-------------|
| {Name} | {Role} | {Distinguishing visual trait} |

## 7. Controls
| Action | Keyboard/Mouse | Gamepad |
|--------|----------------|---------|
| {action_name} | {Key} | {Button} |

## 8. Edge Cases & Constraints
{Unusual situations the design must handle. Each bullet is a rule.}

- What happens if {edge case}?
- Balance constraint: {rule}
- Performance budget: {limit}
