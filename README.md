# Puppet Master

**Seven composable [Agent Skills](https://agentskills.io) that let a coding agent build, run, drive, test, inspect, debug, and profile iOS apps — with evidence instead of guesses.**

[![CI](https://github.com/ksypinro/puppet-master/actions/workflows/ci.yml/badge.svg)](https://github.com/ksypinro/puppet-master/actions/workflows/ci.yml)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-spec%20compliant-6b46c1)](https://agentskills.io/specification)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#requirements)

Most agent iOS tooling stops at "the command exited 0." These skills are built on the opposite premise: **a dispatched action is not a completed action, and a successful command is not a correct result.** Every skill closes its loop — observe, act, verify — and reports what it actually saw separately from what it inferred.

```bash
git clone https://github.com/ksypinro/puppet-master.git
cd puppet-master
./install.sh
```

That detects every coding agent on your machine and installs into each. It downloads nothing and installs no packages — see [Requirements](#requirements).

---

## The skills

| Skill | Answers | Core evidence |
|---|---|---|
| **[ios-build-engineer](skills/ios-build-engineer)** | "Did it build, and is it actually running?" | Structured build diagnostics, resolved products, verified liveness |
| **[ios-simulator-driver](skills/ios-simulator-driver)** | "Does this flow work?" | Accessibility snapshots, screenshots, verified postconditions |
| **[ios-view-hierarchy-debugger](skills/ios-view-hierarchy-debugger)** | "Why does it *look* wrong?" | Native UIKit tree, geometry, constraints, layer state |
| **[lldb-code-state-debugger](skills/lldb-code-state-debugger)** | "Why is the *value* wrong?" | Breakpoints, stopped stacks, stored variables, watchpoints |
| **[ios-instruments-profiler](skills/ios-instruments-profiler)** | "Why is it *slow*?" | xctrace recordings, XCTest metrics, bounded reductions |
| **[ios-memory-debugger](skills/ios-memory-debugger)** | "Why is this *still alive*?" | Reference graph, dominator tree, retained size |
| **[ios-test-engineer](skills/ios-test-engineer)** | "Did it pass, and is that failure real?" | Result bundles, flake classification, region-aware coverage |

They are one toolkit, not seven independent tools. `ios-build-engineer` produces the running app every other skill assumes; `ios-simulator-driver` is the actuator, and the diagnostic skills call into it to reach a screen and reproduce a scenario.

```
                    ios-build-engineer
                 (build it, run it, prove
                    it is actually alive)
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
   ios-test-engineer            ios-simulator-driver
   (run the suite, read           (reach the screen,
    the verdict honestly)          act, verify)
            │                            │
            └──────────┬─────────────────┘
                       │
     ┌───────────┬─────┴─────┬───────────┐
     ▼           ▼           ▼           ▼
view-hierarchy  lldb    instruments    memory
wrong pixels  wrong values wrong timing  still alive
```

### Which one do I need?

You do not choose — your agent does, from the `description` in each skill. But the routing rule is deliberately simple, and it is the same rule each skill uses when handing off:

| Symptom | Skill |
|---|---|
| Build it, sign it, package it, or get it running | `ios-build-engineer` |
| Can't reach the screen; need to tap, type, swipe, navigate | `ios-simulator-driver` |
| Misplaced, clipped, overlapping, mis-styled, untappable view | `ios-view-hierarchy-debugger` |
| Wrong text, wrong number, wrong branch, stale model state | `lldb-code-state-debugger` |
| Slow launch, jank, hitches, leaks, memory growth, battery | `ios-instruments-profiler` |
| Run the suite, read a result bundle, is this failure real, coverage | `ios-test-engineer` |
| Why an object is still alive, what retains it, where the bytes went | `ios-memory-debugger` |

## What makes these different

- **Evidence, not assertions.** Unavailable properties are reported `unknown`, never `0` or `false`. Observed values are named separately from inference. Truncation and errors stay in the record.
- **No invented commands.** `simctl` has no `tap` verb, so these skills never pretend it does — they require a real UI driver and say so when one is missing.
- **Bounded context.** Multi-gigabyte traces and unbounded XML never reach the model. Deterministic reducers export, redact, normalize, and summarize first.
- **Explicit capability limits.** SwiftUI opacity, Xcode View Debugger parity, device-only instruments, and AX-vs-native divergence are documented as limits rather than papered over.
- **Authority is scoped.** Diagnosis permits inspection, not source edits, data deletion, memory writes, or killing a running app.

## Installation

### One command, every agent

```bash
./install.sh
```

| Flag | Effect |
|---|---|
| `--list` | Show what would be installed; change nothing |
| `--agent claude` | Install for one agent only |
| `--project [DIR]` | Install into a project instead of your home directory |
| `--copy` | Copy instead of symlink (for sandboxes that can't follow links) |
| `--force` | Overwrite existing skills of the same name |

By default it **symlinks**, so `git pull` updates every agent at once. Remove with `./uninstall.sh` — it only deletes installations that came from this repository and leaves same-named skills from other sources alone.

### Per-runtime install

<details>
<summary><b>Claude Code</b> — as a plugin, or as skills</summary>

As a plugin (gets the skills plus the `/ios-doctor` command):

```
/plugin marketplace add ksypinro/puppet-master
/plugin install puppet-master@puppet-master
```

As skills only:

```bash
./install.sh --agent claude          # ~/.claude/skills/
./install.sh --agent claude --project # .claude/skills/
```
</details>

<details>
<summary><b>Codex</b> — via skill-installer, or directly</summary>

Ask Codex, which uses its built-in `skill-installer`:

> Install the skills from `ksypinro/puppet-master`

Or run it yourself:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo ksypinro/puppet-master \
  --path skills/ios-simulator-driver \
  --path skills/ios-view-hierarchy-debugger \
  --path skills/lldb-code-state-debugger \
  --path skills/ios-instruments-profiler \
  --path skills/ios-test-engineer
```

Or use this repo's installer, which writes to `~/.agents/skills/`:

```bash
./install.sh --agent codex
```

Each skill carries an `agents/openai.yaml` with Codex display metadata and invocation policy.
</details>

<details>
<summary><b>Cline</b></summary>

```bash
./install.sh --agent cline           # ~/.cline/skills/
./install.sh --agent cline --project # .cline/skills/
```

Cline also reads `.claude/skills/`, so `./install.sh --project` covers Cline and Claude Code with one directory. Manage them from the Skills tab (scale icon, bottom of the Cline panel).
</details>

<details>
<summary><b>Cursor, Copilot / VS Code, Gemini CLI, OpenCode, Goose, and others</b></summary>

These skills follow the [Agent Skills specification](https://agentskills.io/specification), which ~45 agent products implement. `./install.sh` knows the discovery path for the agents listed in [docs/RUNTIMES.md](docs/RUNTIMES.md) and installs into any it detects.

For an agent not yet in that table, copy or link the skill directories into whatever path it scans:

```bash
ln -s "$PWD/skills/ios-simulator-driver" /path/to/agent/skills/
```

Nothing in these skills is runtime-specific — they are Markdown plus stdlib Python.
</details>

## Requirements

**`install.sh` installs no software.** It verifies what you have and links the skills. What the skills themselves need at run time:

| | Requirement | Needed for |
|---|---|---|
| ✅ | **macOS** | everything |
| ✅ | **Python 3.9+** | everything — ships with the Xcode Command Line Tools |
| ✅ | **Full Xcode** | `xcrun`, `simctl`, `lldb`, `xcodebuild` |
| ⚠️ | **Full Xcode, not just Command Line Tools** | `ios-instruments-profiler` — `xctrace` is not in the CLT package |
| ⚠️ | **A UI driver** — [AXe](https://github.com/cameroncooke/AXe), [idb](https://fbidb.io), Appium/WDA, or [XcodeBuildMCP](https://github.com/cameroncooke/XcodeBuildMCP) | `ios-simulator-driver` input; `simctl` cannot synthesize taps |
| ⚠️ | **A physical Apple device** | real CPU, GPU, thermal, energy, and power claims |

**Zero third-party Python packages.** Every script imports the standard library only; verified against macOS system Python 3.9.6. See [requirements.txt](requirements.txt) and [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).

Check your machine at any time:

```bash
python3 tools/doctor.py
```

It reports which of the four skills can actually run here and what is missing for the rest. In Claude Code, `/ios-doctor` does the same.

## Repository layout

```
puppet-master/
├── skills/                      # ← canonical Agent Skills tree (the product)
│   ├── ios-simulator-driver/
│   │   ├── SKILL.md             #   frontmatter + routing, under 500 lines
│   │   ├── references/          #   loaded on demand, not at startup
│   │   ├── scripts/             #   deterministic helpers, stdlib only
│   │   └── agents/openai.yaml   #   Codex display metadata (other runtimes ignore it)
│   └── …
├── commands/ios-doctor.md       # Claude Code slash command
├── tools/
│   ├── doctor.py                # capability probe → machine-readable manifest
│   └── validate_skills.py       # Agent Skills spec validator (runs in CI)
├── .claude-plugin/              # Claude Code plugin + marketplace manifests
├── .codex-plugin/               # Codex plugin manifest
├── install.sh  uninstall.sh
└── docs/                        # install, runtimes, dependencies, research
```

One skill tree, three distribution manifests over it, no duplication and no build step.

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Why a toolkit and not four skills; why no skill router; the evidence model |
| [ROADMAP.md](ROADMAP.md) | Coverage against the CLI research baseline, and the five planned skills |
| [docs/INSTALL.md](docs/INSTALL.md) | Every install path, verification, troubleshooting |
| [docs/RUNTIMES.md](docs/RUNTIMES.md) | Discovery paths per agent, with sources |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | Full dependency audit and rationale |
| [docs/RESEARCH.md](docs/RESEARCH.md) | The deep-research reports behind each skill |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Adding or changing a skill |
| [SECURITY.md](SECURITY.md) | Threat model and reporting |

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Every change must pass:

```bash
python3 tools/validate_skills.py --strict
```

## License

[MIT](LICENSE) © Kazi Samin Yeaser
