#!/usr/bin/env bash
set -euo pipefail

SKILL_NAME="codex-session-recovery"
REPO="${CODEX_SESSION_RECOVERY_REPO:-wufei-png/codex-session-recovery}"
BRANCH="${CODEX_SESSION_RECOVERY_BRANCH:-main}"
RAW_BASE="${CODEX_SESSION_RECOVERY_RAW_BASE:-https://raw.githubusercontent.com/${REPO}/${BRANCH}}"
SOURCE_DIR="${CODEX_SESSION_RECOVERY_SOURCE_DIR:-}"
TARGET_DIR="${CODEX_SESSION_RECOVERY_SKILL_DIR:-${CODEX_HOME:-$HOME/.codex}/skills/${SKILL_NAME}}"

FILES=(
  "codex-session-recovery/SKILL.md:SKILL.md"
  "codex-session-recovery/agents/openai.yaml:agents/openai.yaml"
  "codex-session-recovery/scripts/scan_codex_sessions.py:scripts/scan_codex_sessions.py"
)

tmp_dir=""
backup_dir=""
target_moved=0

cleanup() {
  local status=$?
  if [[ $status -ne 0 && $target_moved -eq 1 && ! -e "$TARGET_DIR" && -e "$backup_dir/current" ]]; then
    mv "$backup_dir/current" "$TARGET_DIR" || true
  fi
  if [[ -n "$tmp_dir" ]]; then
    rm -rf "$tmp_dir"
  fi
  if [[ -n "$backup_dir" ]]; then
    rm -rf "$backup_dir"
  fi
  exit "$status"
}
trap cleanup EXIT

copy_or_download() {
  local source_path="$1"
  local target_path="$2"
  local destination="${tmp_dir}/${target_path}"

  mkdir -p "$(dirname "$destination")"

  if [[ -n "$SOURCE_DIR" ]]; then
    local local_source="${SOURCE_DIR%/}/${source_path}"
    if [[ ! -f "$local_source" ]]; then
      echo "Missing source file: ${local_source}" >&2
      return 1
    fi
    cp "$local_source" "$destination"
    return
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required for remote installation" >&2
    return 1
  fi

  local url="${RAW_BASE}/${source_path}"
  curl -fsSL "$url" -o "$destination"
}

echo "Installing ${SKILL_NAME} skill..."
echo "  Target: ${TARGET_DIR}"

target_parent="$(dirname "$TARGET_DIR")"
mkdir -p "$target_parent"
tmp_dir="$(mktemp -d "${target_parent}/.${SKILL_NAME}.tmp.XXXXXX")"

for entry in "${FILES[@]}"; do
  source_path="${entry%%:*}"
  target_path="${entry#*:}"
  echo "  Installing ${target_path}"
  copy_or_download "$source_path" "$target_path"
done

chmod +x "${tmp_dir}/scripts/scan_codex_sessions.py"

if [[ -e "$TARGET_DIR" || -L "$TARGET_DIR" ]]; then
  backup_dir="$(mktemp -d "${target_parent}/.${SKILL_NAME}.backup.XXXXXX")"
  mv "$TARGET_DIR" "$backup_dir/current"
  target_moved=1
fi

mv "$tmp_dir" "$TARGET_DIR"
tmp_dir=""

if [[ -n "$backup_dir" ]]; then
  rm -rf "$backup_dir"
  backup_dir=""
  target_moved=0
fi

echo ""
echo "Installation complete."
echo "  Installed: ${TARGET_DIR}"
echo "Restart Codex to load newly installed skills."
