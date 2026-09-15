# Cline routing rules

Eight standing rules that tell Cline which skill answers which symptom — and,
just as importantly, which raw command *not* to reach for instead.

## Why these exist

A skill is loaded on demand, and whether it gets loaded depends on the agent
matching the user's phrasing against the skill's `description`. That works when
the user names the problem in the skill's vocabulary and fails when they do not.

The failure that prompted these: asked why a button is not tappable, an agent
with a debugger already attached reaches for `po someView` in LLDB. That returns
a one-line description. The question needs the frame in the right coordinate
space, the screen-space rectangle, active constraints, hugging and compression
priorities, layer state, effective alpha, ancestor clipping and the owning
controller — all of which `ios-view-hierarchy-debugger` produces and none of
which `po` does. The agent was not wrong about the tool being available; it was
wrong about the tool being sufficient, and nothing in the moment told it so.

A rule sits in context *before* the skill choice is made, so it can.

## What is here

| File | Covers |
|---|---|
| `00-ios-toolkit.md` | The routing table: symptom → skill, for all seven |
| `10-view-hierarchy.md` | `ios-view-hierarchy-debugger` |
| `11-simulator-driver.md` | `ios-simulator-driver` |
| `12-lldb-code-state.md` | `lldb-code-state-debugger` |
| `13-instruments.md` | `ios-instruments-profiler` |
| `14-test-engineer.md` | `ios-test-engineer` |
| `15-memory-debugger.md` | `ios-memory-debugger` |
| `16-build-engineer.md` | `ios-build-engineer` |

Each per-skill rule carries the same two things: when to load that skill, and
the specific way the obvious shortcut lies. They are deliberately short — this
is standing context, paid for on every request that touches an iOS file, and a
rule nobody finishes reading routes nothing.

## Format

Cline reads `.md` and `.txt` files from `.clinerules/` at the project root and
from `~/Documents/Cline/Rules/` globally. Frontmatter is optional and supports
**one** key:

```yaml
---
paths:
  - "**/*.swift"
---
```

A rule activates if any pattern matches any file in the current context. Every
rule here is gated on iOS sources, so a project with no Swift, Objective-C or
Xcode files never loads them.

Numeric prefixes order the files. Cline does not require them, but `install.sh`
installs `NN-name.md` and nothing else, so this README is not pushed into anyone's
context as a rule. A new rule needs a two-digit prefix to be installed.

## Installing

```bash
./install.sh                   # → ~/Documents/Cline/Rules/
./install.sh --project         # → ./.clinerules/
./install.sh --agent cline     # rules and Cline skills, nothing else
./install.sh --force           # overwrite files already there
```

Project rules are committed with the project, so a teammate gets them on clone.
Use the global folder for a machine you work on alone.

## Removing, and editing

Each file ends with a provenance marker. `./uninstall.sh` removes only files
that still carry it.

Edit them freely — they are plain Markdown and the wording is not load-bearing.
If you rewrite one and want it to survive an uninstall, delete the marker line;
it will then be reported as yours and left alone.

## Adapting for another agent

The body of each file is runtime-neutral. Claude Code's equivalent surface is
`CLAUDE.md`, Cursor's is `.cursor/rules/`, Codex's is `AGENTS.md` — paste the
body in, drop the frontmatter (or translate it to that runtime's scoping). The
installer does not write those files: they are usually the user's own, and an
installer appending to them is a bad citizen.
