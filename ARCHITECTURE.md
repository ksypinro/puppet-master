# Architecture

This document explains the decisions behind the repository shape. It is written for someone deciding whether to extend, fork, or copy the approach. For what the skills *do*, read their `SKILL.md` files; for how to install them, read [docs/INSTALL.md](docs/INSTALL.md).

## The shape of the problem

An agent debugging an iOS app needs four distinct capabilities that look similar from the outside and are completely different underneath:

1. **Reach a screen and act on it.** Requires an input driver and a way to confirm the input landed.
2. **Explain what is drawn.** Requires the native view tree, geometry in the right coordinate space, and constraints.
3. **Explain what a value is.** Requires a debugger stopped at the right moment on the right thread.
4. **Explain how long something took.** Requires sampling or metric instrumentation, and statistics.

These are not four flavors of one thing. Each has its own failure modes, its own authority requirements, and its own way of lying to you. An accessibility node is not a native view. A stack sample is not elapsed time. A paused screenshot is not a rendering bug. Collapsing them into a single "iOS debugging" skill would produce a skill that is wrong in four different directions.

So: four skills. But they share a substrate, and that is what shapes the repo.

## Why one repository, one plugin

The four skills form a dependency graph, not a flat set:

```
                    ios-simulator-driver
                   (reach the screen, act, verify)
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  view-hierarchy       lldb-code-state      instruments
```

Each of the three diagnostic skills needs the driver to reproduce a scenario. Shipped separately, every one of those references has to be conditional — "use `ios-simulator-driver` *if available*" — and the composition degrades silently when it is not. Shipped together and versioned together, the reference is a guarantee.

That is the whole argument for the plugin manifests: they make a dependency that already exists in the instructions into a dependency the installer enforces.

## Why there is no skill router

The obvious next move at four related skills is a dispatcher — a "find the right iOS skill" entry point. This repository deliberately does not have one.

**The runtime is already the router.** Every skill's `name` and `description` is loaded into the agent's context at startup (~100 tokens each, per the [progressive disclosure model](https://agentskills.io/specification#progressive-disclosure)). Routing happens at zero tool-call cost. A dispatcher would add a round-trip and would have to make the same decision from the same descriptions with *less* context than the model already has.

**Routers pay for themselves at scale, and this is not scale.** The cost a router amortizes is the startup context of many descriptions. At ~50+ skills across unrelated domains that becomes real. Four descriptions in one domain cost roughly 400 tokens total.

**The real problem is disambiguation, not discovery.** "The button doesn't work" maps plausibly onto three of the four skills. A router does not solve that — it relocates the same ambiguous judgment behind a tool call where it is harder to observe and harder to correct. The fix is better boundaries in the descriptions and an explicit handoff rule, both of which live where the model already looks.

**What replaces it** is [`tools/doctor.py`](tools/doctor.py) and the `/ios-doctor` command: a deliberate, user-invoked capability probe that reports which skills can actually run and writes a machine-readable manifest. That is more useful than a router, because the hard question in practice is not *which skill* but *which skill can work here*.

## The evidence model

Every skill in this repository follows the same discipline, and it is the reason they can be composed.

**A dispatched action is not a completed action.** Input commands are event dispatch. `simctl boot` returning is not readiness; a tap being sent is not a tap being handled; an app launching is not an app having rendered. Each skill defines a postcondition and observes it.

**Observation is separated from inference.** Reports name what was captured and what was concluded, as different things. A property that could not be read is `unknown` — never `0`, `false`, or `nil`. Truncation, capture errors, and node limits stay in the evidence rather than being smoothed away.

**Evidence sources are not interchangeable.** AX nodes, `UIView`s, `CALayer`s, SwiftUI's logical tree, and pixels are five different views of a screen that routinely disagree. An AX child is not necessarily a native subview. A hosting view is not the SwiftUI tree. When sources disagree, the skills take a fresh bounded checkpoint or report temporal uncertainty — they do not pick a winner.

**Context is bounded by deterministic code, not by the model.** Traces, XML, HAR files, and logs are exported, redacted, normalized, and reduced by scripts before anything reaches the model. This is why `scripts/` exists in every skill: the reduction has to be reproducible and auditable, and a model summarizing a two-gigabyte trace is neither.

**Authority is scoped to diagnosis.** Inspection does not imply permission to edit source, erase a simulator, reset app data, write memory, send transactions, or kill a running process. Each skill states its boundary explicitly, and expanding it requires the user asking for that expansion.

## Repository layout

```
skills/<name>/           canonical Agent Skills tree — the product
  SKILL.md               frontmatter + routing, under 500 lines
  references/*.md        loaded on demand, one level deep
  scripts/*.py           deterministic helpers, stdlib only
  agents/openai.yaml     Codex metadata; other runtimes ignore it
  assets/                fixtures and templates

commands/                Claude Code slash commands
tools/                   repo-level validator and capability probe
.claude-plugin/          Claude Code plugin + marketplace manifests
.codex-plugin/           Codex plugin manifest
docs/                    install, runtime matrix, dependency audit, research
```

### Why `skills/` is at the top level

Three consumers want different things from the layout, and this one satisfies all of them without duplication:

- The **Agent Skills spec** and the installer want a directory of skill directories.
- **Codex's `skill-installer`** installs by repo path: `--path skills/<name>`. A short path is a usable one.
- **Claude Code plugins** discover `skills/` at the plugin root — and [`"source": "./"`](https://code.claude.com/docs/en/plugin-marketplaces) makes the repository root itself the plugin.

So the repository root *is* the plugin, `skills/` *is* the canonical tree, and the manifests are thin files pointing at it. No symlinks, no vendoring, no build step, nothing to drift.

### Why the adapters are thin

`agents/openai.yaml` is four lines of display metadata and an invocation policy. It is additive: runtimes that do not understand it ignore it. That is the only concession any runtime gets.

The alternative — per-runtime bundles generated by a build step — was rejected. It creates a compile step between editing a skill and testing it, and it produces N copies of every instruction that can silently diverge. The spec is portable enough that adapters should stay ornamental. **If a runtime ever needs a real fork of the instructions, that is a signal the instructions are wrong, not that the build system is missing.**

## Dependency posture

The skills are Markdown plus Python that imports **only the standard library**, verified against macOS system Python 3.9.6 — the interpreter that ships with the Xcode Command Line Tools.

This is a deliberate constraint, not a coincidence. An agent skill that requires `pip install` has a failure mode before it has a chance to be useful: sandboxed agents, restricted environments, and fresh machines all hit it. Keeping to the standard library means `install.sh` never touches the network and never needs a package manager.

The real dependencies are external binaries — `xcrun`, `simctl`, `xctrace`, `lldb`, and optionally `axe` or `idb`. Those cannot be vendored, so they are *detected* and reported instead, by [`tools/doctor.py`](tools/doctor.py). See [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) for the full audit.

## Known gaps

Honest limits, in rough priority order:

- **Session state lives in the conversation, not on disk.** Each skill instructs the agent to preserve UDID, bundle ID, PID, driver session, and run directory across steps. That instruction is load-bearing for composition and is the first thing lost to context compaction. A `session.json` handoff file written by `ios-simulator-driver` and read by the other three would make it durable. This is the highest-value planned change.
- **Shared substrate is duplicated as prose.** Target binding, run-directory conventions, and redaction rules are restated in each `SKILL.md`. Tolerable at four skills; it will drift at eight.
- **No automated end-to-end suite.** The skills have been validated against real apps by hand, and `tools/validate_skills.py` enforces the spec in CI, but there is no fixture app exercising all four in one run.
- **Simulator-first.** Physical-device coverage is real but narrower, and each skill documents which of its claims need a device.

## References

- [Agent Skills specification](https://agentskills.io/specification)
- [Claude Code — skills](https://code.claude.com/docs/en/skills) · [plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Codex — building skills](https://learn.chatgpt.com/docs/build-skills)
- [Cline — skills](https://docs.cline.bot/customization/skills)
