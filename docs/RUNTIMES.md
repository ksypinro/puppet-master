# Runtime support

These skills follow the [Agent Skills specification](https://agentskills.io/specification), an open format implemented by roughly 45 agent products. Nothing here is runtime-specific: a skill is a directory with a `SKILL.md`, and every supporting file is Markdown or standard-library Python.

`./install.sh` detects the agents below and installs into each one's discovery path.

## Discovery paths

| Agent | User scope | Project scope | Source |
|---|---|---|---|
| **Claude Code** | `~/.claude/skills/` | `.claude/skills/` | [docs](https://code.claude.com/docs/en/skills) |
| **Codex** | `~/.agents/skills/`, `$CODEX_HOME/skills` | `.agents/skills/` | [docs](https://learn.chatgpt.com/docs/build-skills) |
| **Cline** | `~/.cline/skills/` | `.cline/skills/`, `.clinerules/skills/`, `.claude/skills/` | [docs](https://docs.cline.bot/customization/skills) |
| **Cursor** | `~/.cursor/skills/` | `.cursor/skills/` | [docs](https://cursor.com/docs/context/skills) |
| **GitHub Copilot / VS Code** | `~/.config/github-copilot/skills/` | `.github/skills/` | [docs](https://code.visualstudio.com/docs/copilot/customization/agent-skills) |
| **Gemini CLI** | `~/.gemini/skills/` | `.gemini/skills/` | [docs](https://geminicli.com/docs/cli/skills/) |
| **OpenCode** | `~/.config/opencode/skills/` | `.opencode/skills/` | [docs](https://opencode.ai/docs/skills/) |
| **Goose** | `~/.config/goose/skills/` | `.goose/skills/` | [docs](https://block.github.io/goose/docs/guides/context-engineering/using-skills/) |

Two things worth knowing:

- **Cline reads `.claude/skills/`.** One project directory serves Claude Code and Cline together — `./install.sh --project` covers both.
- **Codex has two locations.** `~/.agents/skills/` is current; `$CODEX_HOME/skills` (default `~/.codex/skills`) is where its bundled `skill-installer` writes. `install.sh` targets the former, `uninstall.sh` cleans both.
- **Cline gets routing rules in addition to skills.** See below.

## Cline routing rules

Skills are loaded on demand, and whether one gets loaded depends on the agent matching the user's phrasing against the skill's `description`. That works well when the user names the problem in the skill's own vocabulary and badly when they do not: asked why a button is not tappable, an agent with a debugger already attached will reach for `po someView` in LLDB — which returns a one-line description that cannot answer the question — rather than loading `ios-view-hierarchy-debugger`.

Cline supports [standing rules](https://docs.cline.bot/features/cline-rules) for exactly this: short Markdown files that sit in context and steer behaviour before a skill is chosen. This repository ships eight of them in [`clinerules/`](../clinerules/) — a routing table plus one per skill.

| Location | Scope |
|---|---|
| `~/Documents/Cline/Rules/` | every project on the machine |
| `<project>/.clinerules/` | that project, committed with it |

`./install.sh` writes the first; `./install.sh --project` writes the second. `--agent cline` limits an install to Cline, and any other `--agent` value skips the rules entirely.

**Frontmatter.** Cline supports exactly one key, `paths:` — an array of globs. A rule activates if any pattern matches any file in the current context. Every rule here is gated on iOS sources (`**/*.swift`, `**/*.m`, `**/*.mm`, `**/*.h`, `**/*.xcodeproj/**`, `**/*.xcworkspace/**`, `**/Package.swift`), so a non-iOS project pays nothing for having them installed. Numeric filename prefixes are a convention for ordering, not a requirement.

**Removal.** Each file carries a provenance marker. `./uninstall.sh` removes only files that still carry it; strip the line and the file is yours, reported and left alone.

**Other runtimes.** Claude Code's equivalent is `CLAUDE.md`, Cursor's is `.cursor/rules/`, Codex's is `AGENTS.md`. These files are Markdown with a frontmatter key only Cline reads, so they can be adapted by hand, but `install.sh` does not write them — a rules file in one of those locations is the user's own, and an installer should not append to it.

## Bundle formats

Beyond plain skills, this repository ships as a plugin in both ecosystems. The repository root *is* the plugin in each case, so there is no duplicated skill tree.

### Claude Code plugin

`.claude-plugin/plugin.json` plus `.claude-plugin/marketplace.json` with `"source": "./"`, the documented [single-plugin-repository pattern](https://code.claude.com/docs/en/plugin-marketplaces). Installing the plugin gets every skill *and* the `/ios-doctor` command:

```
/plugin marketplace add ksypinro/puppet-master
/plugin install puppet-master@puppet-master
```

### Codex plugin and skills

`.codex-plugin/plugin.json` declares `"skills": "./skills/"` with `interface` metadata for the Codex UI. Each skill also carries `agents/openai.yaml`:

```yaml
interface:
  display_name: "iOS Simulator Driver"
  short_description: "Observe, drive, verify, and recover iOS Simulator UI"
  default_prompt: "Use $ios-simulator-driver to drive the selected iOS Simulator…"
policy:
  allow_implicit_invocation: true
```

Codex's bundled `skill-installer` can also pull individual skills straight from GitHub:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo ksypinro/puppet-master --path skills/ios-simulator-driver
```

## Adding a runtime

If your agent reads `SKILL.md` directories, it already works — link the skills into whatever path it scans:

```bash
ln -s "$PWD/skills/ios-simulator-driver" /path/to/agent/skills/
```

To have `install.sh` detect it automatically, add one line to the `AGENTS` array in [install.sh](../install.sh) and [uninstall.sh](../uninstall.sh):

```
"key|Display Name|$HOME/user/scope/path|project/scope/path"
```

and a case to `agent_present()` naming the config directory that proves the agent is installed. A pull request adding a runtime should cite the vendor's documentation for the path, as the table above does.

## Requirements are the same everywhere

Runtime support says nothing about capability. Every skill needs macOS, Python 3.9+, and full Xcode regardless of which agent drives it — see [DEPENDENCIES.md](DEPENDENCIES.md). An agent running on Linux or in a cloud sandbox without Xcode will load these skills and be unable to use them.
