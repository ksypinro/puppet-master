#!/usr/bin/env bash
#
# Puppet Master — remove the iOS agent skills from this machine.
#
#   ./uninstall.sh                remove from every agent (asks first)
#   ./uninstall.sh --list         show what would be removed, change nothing
#   ./uninstall.sh --agent claude remove from one agent only
#   ./uninstall.sh --project DIR  remove from a project instead of the home directory
#   ./uninstall.sh --yes          skip the confirmation prompt
#
# Only removes entries whose name matches a skill in this repository, and only
# when the entry is a symlink into this repository or a directory whose SKILL.md
# carries this repository's metadata. A skill of the same name from another
# source is reported and left alone.
#
# The same rule governs the Cline routing rules in .clinerules/ and
# ~/Documents/Cline/Rules: a rule file is removed only if it still carries the
# provenance marker this repository writes into it. A file someone has taken
# over and stripped that line from is theirs, and is left alone.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"
RULES_DIR="$REPO_ROOT/clinerules"
MARKER="github.com/ksypinro/puppet-master"

SCOPE="user"; PROJECT_DIR=""; ONLY_AGENT=""; LIST_ONLY=0; ASSUME_YES=0

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '%sError:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; $d'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list|-l)  LIST_ONLY=1; shift ;;
    --yes|-y)   ASSUME_YES=1; shift ;;
    --agent|-a) ONLY_AGENT="${2:?--agent needs a name}"; shift 2 ;;
    --project|-p)
      SCOPE="project"
      if [[ ${2:-} && ${2:0:1} != "-" ]]; then PROJECT_DIR="$2"; shift 2
      else PROJECT_DIR="$PWD"; shift; fi ;;
    --help|-h)  usage ;;
    *)          die "unknown option: $1  (try --help)" ;;
  esac
done

AGENTS=(
  "claude|Claude Code|$HOME/.claude/skills|.claude/skills"
  "codex|Codex|$HOME/.agents/skills|.agents/skills"
  "codex-home|Codex (CODEX_HOME)|${CODEX_HOME:-$HOME/.codex}/skills|-"
  "cline|Cline|$HOME/.cline/skills|.cline/skills"
  "cursor|Cursor|$HOME/.cursor/skills|.cursor/skills"
  "copilot|GitHub Copilot / VS Code|$HOME/.config/github-copilot/skills|.github/skills"
  "gemini|Gemini CLI|$HOME/.gemini/skills|.gemini/skills"
  "opencode|OpenCode|$HOME/.config/opencode/skills|.opencode/skills"
  "goose|Goose|$HOME/.config/goose/skills|.goose/skills"
)

# Is $1 an installation that came from this repository?
ours() {
  local target="$1"
  if [[ -L "$target" ]]; then
    local resolved; resolved="$(cd "$(dirname "$target")" && readlink "$target")"
    [[ "$resolved" == "$SKILLS_DIR"/* ]] && return 0
    return 1
  fi
  [[ -f "$target/SKILL.md" ]] && grep -q "$MARKER" "$target/SKILL.md" 2>/dev/null
}

# Collect the removal plan so the user sees everything before anything is deleted.
PLAN_PATHS=(); PLAN_LABELS=(); FOREIGN=()

for entry in "${AGENTS[@]}"; do
  IFS='|' read -r key display user_path project_path <<< "$entry"
  [[ -z "$ONLY_AGENT" || "$ONLY_AGENT" == "$key" ]] || continue

  if [[ "$SCOPE" == "project" ]]; then
    [[ "$project_path" == "-" ]] && continue
    dest="$(cd "$PROJECT_DIR" && pwd)/$project_path"
  else
    dest="$user_path"
  fi
  [[ -d "$dest" ]] || continue

  for skill_path in "$SKILLS_DIR"/*/; do
    [[ -f "$skill_path/SKILL.md" ]] || continue
    skill="$(basename "$skill_path")"
    target="$dest/$skill"
    [[ -e "$target" || -L "$target" ]] || continue

    if ours "$target"; then
      PLAN_PATHS+=("$target"); PLAN_LABELS+=("$display: $skill")
    else
      FOREIGN+=("$display: $skill  ${DIM}($target — not from this repository)${RESET}")
    fi
  done
done

# Rule files, wherever install.sh could have put them for this scope.
if [[ -z "$ONLY_AGENT" || "$ONLY_AGENT" == "cline" ]] && [[ -d "$RULES_DIR" ]]; then
  if [[ "$SCOPE" == "project" ]]; then
    rules_dest="$(cd "$PROJECT_DIR" && pwd)/.clinerules"
  else
    rules_dest="$HOME/Documents/Cline/Rules"
  fi
  if [[ -d "$rules_dest" ]]; then
    for rule in "$RULES_DIR"/[0-9][0-9]-*.md; do
      [[ -f "$rule" ]] || continue
      name="$(basename "$rule")"
      target="$rules_dest/$name"
      [[ -f "$target" ]] || continue
      if grep -q "$MARKER" "$target" 2>/dev/null; then
        PLAN_PATHS+=("$target"); PLAN_LABELS+=("Cline rule: $name")
      else
        FOREIGN+=("Cline rule: $name  ${DIM}($target — marker removed, treated as yours)${RESET}")
      fi
    done
  fi
fi

say ""
say "${BOLD}Puppet Master${RESET} ${DIM}— uninstall${RESET}"
say ""

if ((${#PLAN_PATHS[@]} == 0)); then
  warn "nothing installed from this repository was found"
  ((${#FOREIGN[@]})) && { say ""; say "${BOLD}Left alone${RESET}"; for f in "${FOREIGN[@]}"; do warn "$f"; done; }
  say ""
  exit 0
fi

say "${BOLD}Will remove ${#PLAN_PATHS[@]} installed item(s)${RESET}"
for i in "${!PLAN_PATHS[@]}"; do
  say "  ${PLAN_LABELS[$i]}"
  say "    ${DIM}${PLAN_PATHS[$i]}${RESET}"
done

if ((${#FOREIGN[@]})); then
  say ""
  say "${BOLD}Left alone${RESET} ${DIM}(same name, different source)${RESET}"
  for f in "${FOREIGN[@]}"; do warn "$f"; done
fi

if (( LIST_ONLY )); then
  say ""
  say "${DIM}Nothing was changed. Re-run without --list to remove.${RESET}"
  say ""
  exit 0
fi

if (( ! ASSUME_YES )); then
  say ""
  read -r -p "Remove these? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { say "Cancelled."; exit 0; }
fi

say ""
for i in "${!PLAN_PATHS[@]}"; do
  rm -rf "${PLAN_PATHS[$i]}"
  ok "removed ${PLAN_LABELS[$i]}"
done

say ""
say "${DIM}This repository itself was not touched.${RESET}"
say ""
