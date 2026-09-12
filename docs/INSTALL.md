# Installation

```bash
git clone https://github.com/ksypinro/puppet-master.git
cd puppet-master
./install.sh
```

That is the whole thing. The installer detects every supported agent on your machine, verifies your toolchain, and links the four skills into each agent's discovery path. **It downloads nothing and installs no packages** — the skills are Markdown plus standard-library Python.

## What install.sh does

1. **Validates** every skill against the [Agent Skills spec](https://agentskills.io/specification) — refusing to install something malformed.
2. **Preflights** macOS, Python 3.9+, full Xcode, and optional UI drivers, warning rather than failing on the optional ones.
3. **Detects** installed agents by looking for their config directories.
4. **Links** each skill into each agent's skills directory.

```
./install.sh --list       # show the plan, change nothing
```

## Options

| Flag | Effect |
|---|---|
| `--list`, `-l` | Dry run: print what would happen |
| `--agent NAME`, `-a` | One agent only: `claude`, `codex`, `cline`, `cursor`, `copilot`, `gemini`, `opencode`, `goose` |
| `--project [DIR]`, `-p` | Install into a project (default: current directory) rather than your home directory |
| `--copy` | Copy files instead of symlinking |
| `--force`, `-f` | Overwrite skills of the same name |
| `--help`, `-h` | Usage |

### Symlink or copy

The default is **symlinks**, so `git pull` updates every agent at once and editing a skill takes effect on the agent's next restart. That is what you want while developing.

Use `--copy` when the agent runs in a sandbox that cannot follow symlinks out of its working tree, when you are installing onto a machine that will not keep the clone, or when you want a pinned snapshot that a later `git pull` cannot change. After `--copy`, re-run the installer to pick up updates.

### User scope or project scope

**User scope** (default) installs into your home directory and applies to every project.

**Project scope** (`--project`) installs into the repository you are working in, so the skills travel with the code and your teammates get them on clone. Because project scope is about the repository rather than your machine, it installs for every agent with a documented project path — your teammates may not use your agent.

```bash
cd ~/code/my-ios-app
/path/to/puppet-master/install.sh --project --copy
```

Use `--copy` for project scope if you intend to commit the skills; a symlink to a path on your machine is useless to everyone else.

## Verify

```bash
python3 tools/doctor.py
```

```
  ✓ Python 3.13.7  (need 3.9+, stdlib only)
  ✓ macOS 26.5.1 (arm64)
  ✓ Xcode 27.0
  ✓ 11 Simulator device(s) available, 1 booted
  ! No standalone UI driver on PATH

Skills
  ✓ ios-simulator-driver
      note: no UI driver found …
  ✓ ios-view-hierarchy-debugger
  ✓ lldb-code-state-debugger
  ✓ ios-instruments-profiler

4/4 skills operational.
```

`--json` emits a machine-readable capability manifest; `-o PATH` writes it to a file. In Claude Code, `/ios-doctor` runs the same probe.

Then restart your agent and ask it something a skill covers — "why is this button untappable on the current screen?" — and confirm it activates the skill rather than improvising.

## Uninstall

```bash
./uninstall.sh            # shows the plan, asks before deleting
./uninstall.sh --list     # plan only
./uninstall.sh --yes      # skip confirmation
```

It removes only entries that are symlinks into this repository or directories whose `SKILL.md` carries this repository's metadata. A same-named skill from another source is reported and left alone. The clone itself is never touched.

## Troubleshooting

**The agent does not see the skills.** Restart it — most agents scan their skills directory at startup. Confirm the install landed where that agent actually looks (`./install.sh --list`, and the table in [RUNTIMES.md](RUNTIMES.md)). If the agent runs sandboxed, try `--copy`: some sandboxes will not follow a symlink out of the working tree.

**`xctrace` not found / `ios-instruments-profiler` blocked.** You have the standalone Command Line Tools selected, not full Xcode:

```bash
xcode-select -p    # should be inside Xcode.app
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

**The driver skill can observe but not tap.** Expected with no UI driver installed. `simctl` has no `tap` verb. Install one — `brew install cameroncooke/axe/axe` is the shortest path. See [DEPENDENCIES.md](DEPENDENCIES.md#ui-drivers--pick-one).

**"skill validation failed".** Run `python3 tools/validate_skills.py` for the specific violation. On an unmodified clone this should not happen — please open an issue with the output.

**Skills already present.** The installer skips existing entries rather than clobbering them. `--force` overwrites.

**Python too old.** `python3 --version` must be 3.9+. macOS ships 3.9.6 at `/usr/bin/python3` with the Command Line Tools; if your PATH `python3` is older, something unusual is shadowing it.
