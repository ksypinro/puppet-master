#!/usr/bin/env bash
#
# Puppet Master — install the iOS agent skills into every coding agent on this machine.
#
#   ./install.sh                      detect installed agents, install into each
#   ./install.sh --list               show what would be installed, change nothing
#   ./install.sh --agent claude       install for one agent only
#   ./install.sh --project [DIR]      install into a project instead of the home directory
#   ./install.sh --copy               copy files instead of symlinking
#   ./install.sh --force              overwrite existing skills of the same name
#
# Installs nothing from the network and requires no package manager: the skills
# are plain Markdown plus stdlib-only Python. This script verifies the system
# dependencies, then links the skill directories into each agent's discovery path.
#
# It also copies the Cline routing rules in clinerules/ -- into a project's
# .clinerules/ under --project, or into ~/Documents/Cline/Rules otherwise. They
# tell Cline which skill answers which symptom, and are scoped by a `paths:`
# glob so they are inert outside an iOS project.
#
# By default it symlinks, so `git pull` updates every agent at once. Use --copy
# for a detached snapshot (needed if an agent sandbox cannot follow symlinks).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"
RULES_DIR="$REPO_ROOT/clinerules"

MODE="link"          # link | copy
SCOPE="user"         # user | project
PROJECT_DIR=""
ONLY_AGENT=""
FORCE=0
LIST_ONLY=0

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
err()  { printf '  %s✗%s %s\n' "$RED" "$RESET" "$*" >&2; }
die()  { printf '%sError:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; $d'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list|-l)    LIST_ONLY=1; shift ;;
    --copy)       MODE="copy"; shift ;;
    --force|-f)   FORCE=1; shift ;;
    --agent|-a)   ONLY_AGENT="${2:?--agent needs a name}"; shift 2 ;;
    --project|-p)
      SCOPE="project"
      if [[ ${2:-} && ${2:0:1} != "-" ]]; then PROJECT_DIR="$2"; shift 2
      else PROJECT_DIR="$PWD"; shift; fi ;;
    --help|-h)    usage ;;
    *)            die "unknown option: $1  (try --help)" ;;
  esac
done

# ---------------------------------------------------------------------------
# Agent registry
#
# Each entry is  key|Display Name|user-scope path|project-scope path
# Paths are the directories the agent scans for skills. A project path of "-"
# means that agent has no documented project-level skill directory.
#
# Sources:
#   Claude Code  https://code.claude.com/docs/en/skills
#   Codex        https://learn.chatgpt.com/docs/build-skills
#   Cline        https://docs.cline.bot/customization/skills
#   Cursor       https://cursor.com/docs/context/skills
#   Copilot/VSC  https://code.visualstudio.com/docs/copilot/customization/agent-skills
#   Gemini CLI   https://geminicli.com/docs/cli/skills/
#   OpenCode     https://opencode.ai/docs/skills/
#   Goose        https://block.github.io/goose/docs/guides/context-engineering/using-skills/
# ---------------------------------------------------------------------------
AGENTS=(
  "claude|Claude Code|$HOME/.claude/skills|.claude/skills"
  "codex|Codex|$HOME/.agents/skills|.agents/skills"
  "cline|Cline|$HOME/.cline/skills|.cline/skills"
  "cursor|Cursor|$HOME/.cursor/skills|.cursor/skills"
  "copilot|GitHub Copilot / VS Code|$HOME/.config/github-copilot/skills|.github/skills"
  "gemini|Gemini CLI|$HOME/.gemini/skills|.gemini/skills"
  "opencode|OpenCode|$HOME/.config/opencode/skills|.opencode/skills"
  "goose|Goose|$HOME/.config/goose/skills|.goose/skills"
)

# An agent is "present" if its config root exists. Codex additionally honours
# $CODEX_HOME/skills (default ~/.codex/skills), which predates ~/.agents/skills.
agent_present() {
  case "$1" in
    claude)   [[ -d "$HOME/.claude"   ]] ;;
    codex)    [[ -d "${CODEX_HOME:-$HOME/.codex}" || -d "$HOME/.agents" ]] ;;
    cline)    [[ -d "$HOME/.cline" || -d "$HOME/Documents/Cline" ]] ;;
    cursor)   [[ -d "$HOME/.cursor"   ]] ;;
    copilot)  [[ -d "$HOME/.config/github-copilot" ]] ;;
    gemini)   [[ -d "$HOME/.gemini"   ]] ;;
    opencode) [[ -d "$HOME/.config/opencode" ]] ;;
    goose)    [[ -d "$HOME/.config/goose" ]] ;;
    *)        return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
preflight() {
  say "${BOLD}Checking dependencies${RESET}"

  [[ "$(uname -s)" == "Darwin" ]] || die "these skills require macOS (found $(uname -s))"
  ok "macOS $(sw_vers -productVersion 2>/dev/null || echo '')"

  command -v python3 >/dev/null 2>&1 || die "python3 not found. Install the Xcode Command Line Tools: xcode-select --install"
  local pyver; pyver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "Python 3.9+ required (found $pyver)"
  ok "Python $pyver  ${DIM}(no third-party packages needed)${RESET}"

  if xcodebuild -version >/dev/null 2>&1; then
    ok "$(xcodebuild -version | head -1)  ${DIM}$(xcode-select -p)${RESET}"
  else
    warn "full Xcode not selected — ios-instruments-profiler will not work"
    say  "    ${DIM}sudo xcode-select -s /Applications/Xcode.app/Contents/Developer${RESET}"
  fi

  local drivers=()
  for d in axe idb appium; do command -v "$d" >/dev/null 2>&1 && drivers+=("$d"); done
  if ((${#drivers[@]})); then
    ok "UI driver(s): ${drivers[*]}"
  else
    warn "no UI driver on PATH — ios-simulator-driver can observe but not tap"
    say  "    ${DIM}brew install cameroncooke/axe/axe   # or idb, Appium, XcodeBuildMCP${RESET}"
  fi
  say ""
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
install_into() {
  local display="$1" dest="$2" installed=0 skipped=0

  mkdir -p "$dest"

  for skill_path in "$SKILLS_DIR"/*/; do
    [[ -f "$skill_path/SKILL.md" ]] || continue
    local skill target
    skill="$(basename "$skill_path")"
    target="$dest/$skill"

    if [[ -e "$target" || -L "$target" ]]; then
      if (( FORCE )); then
        rm -rf "$target"
      else
        skipped=$((skipped + 1))
        continue
      fi
    fi

    if [[ "$MODE" == "link" ]]; then
      ln -s "${skill_path%/}" "$target"
    else
      cp -R "${skill_path%/}" "$target"
      # Drop bytecode caches so a copied install stays clean.
      find "$target" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    fi
    installed=$((installed + 1))
  done

  local verb; [[ "$MODE" == "link" ]] && verb="linked" || verb="copied"
  if (( installed )); then
    ok "$display — $verb $installed skill(s) into $dest"
  fi
  if (( skipped )); then
    warn "$display — skipped $skipped already present ${DIM}(--force to overwrite)${RESET}"
  fi
}

# Cline reads standing rules from two places: `.clinerules/` at a project root,
# and a global rules folder at ~/Documents/Cline/Rules. Both take the same
# Markdown files.
#
# These rules are routing hints -- which skill answers which symptom, and which
# raw command not to reach for instead. Each carries a `paths:` glob (the only
# frontmatter key Cline supports) so a rule activates only when an iOS source
# file is in context, and costs nothing on a project that has none.
#
# Always copied, never symlinked. Project rules are committed alongside the
# project, where a symlink into one developer's clone is useless to everyone
# else; the global folder is scanned by an editor extension that should not be
# made to follow links out of it.
install_rules() {
  local display="$1" dest="$2" installed=0 skipped=0
  [[ -d "$RULES_DIR" ]] || return 0
  mkdir -p "$dest"
  # NN-name.md only: the directory also holds its own README, which is
  # documentation for a human reading the repository, not standing context to
  # push into every Cline request.
  for rule in "$RULES_DIR"/[0-9][0-9]-*.md; do
    [[ -f "$rule" ]] || continue
    local base target
    base="$(basename "$rule")"
    target="$dest/$base"
    if [[ -e "$target" ]] && (( ! FORCE )); then
      skipped=$((skipped + 1))
      continue
    fi
    cp "$rule" "$target"
    installed=$((installed + 1))
  done
  if (( installed )); then
    ok "$display — copied $installed rule file(s) into $dest"
  fi
  if (( skipped )); then
    warn "$display — skipped $skipped rule file(s) already present ${DIM}(--force to overwrite)${RESET}"
  fi
}

# Where the rules go for the scope being installed. Echoes nothing when there is
# no destination: --agent naming something other than cline is a request for
# that agent alone, and user scope only writes the global folder when Cline is
# actually installed here.
rules_dest() {
  [[ -z "$ONLY_AGENT" || "$ONLY_AGENT" == "cline" ]] || return 0
  if [[ "$SCOPE" == "project" ]]; then
    printf '%s\n' "$PROJECT_DIR/.clinerules"
  elif agent_present cline; then
    printf '%s\n' "$HOME/Documents/Cline/Rules"
  fi
}

main() {
  say ""
  say "${BOLD}Puppet Master${RESET} ${DIM}— iOS agent skills installer${RESET}"
  say "${DIM}$REPO_ROOT${RESET}"
  say ""

  [[ -d "$SKILLS_DIR" ]] || die "no skills/ directory at $SKILLS_DIR"

  say "${BOLD}Validating skills${RESET}"
  python3 "$REPO_ROOT/tools/validate_skills.py" >/dev/null \
    || die "skill validation failed. Run: python3 tools/validate_skills.py"
  ok "$(find "$SKILLS_DIR" -maxdepth 2 -name SKILL.md | wc -l | tr -d ' ') skills conform to the Agent Skills spec"
  say ""

  (( LIST_ONLY )) || preflight

  if [[ "$SCOPE" == "project" ]]; then
    PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
    say "${BOLD}Installing into project${RESET} ${DIM}$PROJECT_DIR${RESET}"
  else
    say "${BOLD}Installing for detected agents${RESET}"
  fi

  local any=0
  for entry in "${AGENTS[@]}"; do
    IFS='|' read -r key display user_path project_path <<< "$entry"

    [[ -z "$ONLY_AGENT" || "$ONLY_AGENT" == "$key" ]] || continue

    local dest
    if [[ "$SCOPE" == "project" ]]; then
      [[ "$project_path" == "-" ]] && continue
      dest="$PROJECT_DIR/$project_path"
      # In project scope, install for every agent that has a documented path:
      # a repo is shared, and teammates may use a different agent.
    else
      if ! agent_present "$key" && [[ -z "$ONLY_AGENT" ]]; then
        continue
      fi
      dest="$user_path"
    fi

    if (( LIST_ONLY )); then
      say "  ${DIM}would install:${RESET} $display → $dest"
      any=1
      continue
    fi

    install_into "$display" "$dest"
    any=1
  done

  if (( ! any )); then
    say ""
    warn "no supported agent detected on this machine"
    say  "    ${DIM}Install for one explicitly:  ./install.sh --agent claude${RESET}"
    say  "    ${DIM}Or into a project:           ./install.sh --project${RESET}"
    say ""
    exit 0
  fi

  local rules_to
  rules_to="$(rules_dest)"

  if (( LIST_ONLY )); then
    if [[ -n "$rules_to" && -d "$RULES_DIR" ]]; then
      say "  ${DIM}would install:${RESET} Cline routing rules → $rules_to"
    fi
    say ""
    say "${DIM}Nothing was changed. Re-run without --list to install.${RESET}"
    say ""
    exit 0
  fi

  if [[ -n "$rules_to" ]]; then
    install_rules "Cline rules" "$rules_to"
  fi

  say ""
  say "${BOLD}Next${RESET}"
  say "  1. Restart your agent so it rescans its skills directory."
  say "  2. Run the capability probe:  ${BOLD}python3 tools/doctor.py${RESET}"
  if [[ "$MODE" == "link" ]]; then
    say "  3. Skills are symlinked — ${BOLD}git pull${RESET} updates every agent at once."
  else
    say "  3. Skills were copied — re-run this script after ${BOLD}git pull${RESET}."
  fi
  say ""
}

main "$@"
