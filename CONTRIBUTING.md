# Contributing

Thanks for considering a contribution. This repository holds agent skills, which are a slightly unusual artifact: the "code" is mostly instructions read by a model, and the quality bar is *does it change the agent's behavior for the better*, not *does it read well*.

## Setup

There is no build and no install step.

```bash
git clone https://github.com/ksypinro/puppet-master.git
cd puppet-master
python3 tools/doctor.py               # what can run on this machine
python3 tools/validate_skills.py      # spec conformance
```

You need macOS, Python 3.9+, and full Xcode. Nothing from PyPI — see [requirements.txt](requirements.txt).

To test your changes live, install with symlinks so edits take effect on the agent's next restart:

```bash
./install.sh          # symlinks by default
```

## Before you open a pull request

```bash
python3 tools/validate_skills.py --strict    # must pass; CI enforces it
/usr/bin/python3 -m py_compile $(find skills tools -name '*.py')   # 3.9 floor
bash -n install.sh uninstall.sh
```

## Changing a skill

Read [ARCHITECTURE.md](ARCHITECTURE.md) first — particularly *The evidence model*. Most rejected changes are rejected because they break one of those invariants, not because of style.

The rules that matter:

**Do not weaken the evidence discipline.** Unavailable data is `unknown`, never `0` or `false`. A dispatched action is not a completed action. Observation and inference stay separately labeled. If a change makes a skill report something it did not actually observe, it will not be merged regardless of how much more convenient the output looks.

**Do not invent commands.** `simctl` has no `tap`, `swipe`, or `hierarchy` verb. If a capability needs a tool the user may not have, detect it and report its absence.

**Keep `SKILL.md` under 500 lines.** It is loaded in full on activation. Detail belongs in `references/`, loaded on demand, one level deep. The validator warns past the limit.

**Keep scripts stdlib-only and 3.9-compatible.** A new third-party dependency needs a strong argument in the PR description; the default answer is no.

**Descriptions are routing, not marketing.** The `description` field is the only text an agent sees when deciding whether to activate. Describe the real capability and when it applies. Add an exclusion only where it prevents a likely misroute — `ios-instruments-profiler`'s "Do not use for ordinary functional UI testing" is the model to follow. Avoid capability lists and catchalls.

**Scope authority narrowly.** Inspection does not imply permission to edit source, erase a simulator, reset app data, write memory, or kill a process. New capabilities that mutate state must require explicit authorization and say so in `SKILL.md`.

## Adding a skill

1. `skills/<name>/SKILL.md` with `name` (matching the directory), `description`, `license`, `compatibility`, and `metadata`.
2. `references/` for detail, `scripts/` for deterministic helpers, `agents/openai.yaml` for Codex metadata.
3. State how it composes with the existing four, and add it to the routing table in [README.md](README.md) and to `SKILL_REQUIREMENTS` in [tools/doctor.py](tools/doctor.py).
4. Run `python3 tools/validate_skills.py --strict`.

A new skill needs to justify being separate. If it shares a failure mode and an authority boundary with an existing skill, it is probably a `references/` file in that skill instead.

## Style

- Python: 4-space indent, 100-column soft limit, type hints on public functions, docstrings that explain *why*.
- Markdown: sentence case headings, tables where structure helps, no decorative emoji.
- Shell: `set -euo pipefail`, `bash -n` clean, quote everything.
- Commits: imperative mood, one logical change. Conventional Commits welcome but not required.

## Reporting bugs

Open an issue with the template. Include the output of `python3 tools/doctor.py`, your Xcode version, and — most usefully — the transcript fragment showing what the agent did and what you expected. A skill bug is usually "the agent took the wrong action given this evidence," and that is invisible without the transcript.

**Do not report security issues here.** See [SECURITY.md](SECURITY.md).

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
