# Security Policy

## Reporting a vulnerability

Report privately through [GitHub Security Advisories](https://github.com/ksypinro/puppet-master/security/advisories/new). Please do not open a public issue for a security problem.

Include the affected skill or script, the conditions required, and what an attacker gains. You should get an initial response within 7 days.

## Threat model

These skills give a coding agent the ability to drive a simulator, attach a debugger, execute code inside an app under diagnosis, and record traces. That is a meaningful amount of authority, so it is worth being precise about where the boundaries are.

### What the skills are designed to do

- Operate on a target the user explicitly identified (UDID, bundle ID, PID).
- Read runtime state: view hierarchies, variables, stacks, accessibility trees, traces.
- Dispatch UI input and control execution on an authorized target.
- Write evidence to a run directory supplied by the caller.

### What they are designed *not* to do

- Bypass app protections, signing, entitlements, or platform security. A target that is not debuggable stays not debuggable; the skills report the error rather than routing around it.
- Edit application source, delete data, erase a simulator, reset app data, write memory, or send real transactions — without the user asking for that specific action.
- Install software, change signing, or modify system or security settings.
- Compete for a process another debugger owns.

### Known-sharp edges

These are inherent to the capability, documented in the relevant `SKILL.md`, and worth understanding before you run anything:

- **Expression evaluation executes code in the target.** `p`, `po`, breakpoint conditions, descriptions, and formatters can all run app code and mutate state. Unwinding an expression is not a rollback. The opt-in flags in `lldb-code-state-debugger` document authority; they are not a security sandbox.
- **The view-hierarchy probe runs inside the app.** `ui_capture --compiled-probe` compiles a collector and executes it in the authorized target process. Read `references/lldb-capture.md` before using it.
- **Captured evidence can contain secrets.** View hierarchies hold on-screen text; traces hold URLs, headers, bodies, and file paths; logs hold whatever the app logged. The skills instruct redaction before anything reaches a model, but **the run directory itself is unencrypted on disk** — treat it as sensitive and do not commit it. The `.gitignore` excludes `run/`, `*.trace`, and `*.xcresult` for this reason.
- **A model reading captured evidence is reading untrusted input.** Screen contents, log lines, and network bodies are data, not instructions. If an app displays text that looks like a command to the agent, a well-behaved agent should not act on it.

### Scope

In scope: anything in `skills/`, `tools/`, `install.sh`, `uninstall.sh`, and the manifests — for example a script that escapes its run directory, a helper that executes attacker-controlled input, an installer that writes outside its declared paths, or evidence handling that leaks secrets into model context contrary to the documented redaction.

Out of scope: vulnerabilities in Xcode, LLDB, `simctl`, `xctrace`, or third-party drivers (report those upstream); the inherent capability of a debugger to inspect a process you already control; and social-engineering an agent into requesting authorization that the user then grants.

## Supported versions

The latest release on `main` receives fixes. There are no long-term support branches.
