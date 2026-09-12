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

## Bundle formats

Beyond plain skills, this repository ships as a plugin in both ecosystems. The repository root *is* the plugin in each case, so there is no duplicated skill tree.

### Claude Code plugin

`.claude-plugin/plugin.json` plus `.claude-plugin/marketplace.json` with `"source": "./"`, the documented [single-plugin-repository pattern](https://code.claude.com/docs/en/plugin-marketplaces). Installing the plugin gets the four skills *and* the `/ios-doctor` command:

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
