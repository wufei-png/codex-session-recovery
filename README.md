# codex-session-recovery

![codex-session-recovery cover](docs/assets/codex-session-recovery-cover.png)

Reusable Codex skill for finding local Codex session history and producing safe, CLI-first recovery instructions.

## Recover Lost Codex Sessions Faster

When a Codex thread disappears after an account switch, provider change, or sidebar cleanup, `codex-session-recovery` helps you recover the session without touching live Codex state. It is especially useful when you switch accounts with tools such as `cc-switch` and older sessions stop showing up where you expect them.

## What It Helps You Do

- Find likely sessions by project path, time window, or prompt text.
- Turn recovery into concrete next steps such as `codex resume`, `codex fork`, and `codex://threads/...`.
- Keep the workflow safe with read-only scanning and no live state rewrites.

## Why This Skill Stands Out

- Many recovery skills stop at CLI output. This one also considers the Desktop path.
- When the required thread tools are available, it can help restore a recovered result into the Codex Desktop left sidebar as a visible, titleable, pinnable thread.
- It is designed for practical recovery after real workflow disruptions, including account switching with `cc-switch`.

## Install

One-line install:

```bash
curl -fsSL https://raw.githubusercontent.com/wufei-png/codex-session-recovery/main/install.sh | bash
```

This installs the skill into `${CODEX_HOME:-$HOME/.codex}/skills/codex-session-recovery`.

To install elsewhere:

```bash
curl -fsSL https://raw.githubusercontent.com/wufei-png/codex-session-recovery/main/install.sh \
  | CODEX_SESSION_RECOVERY_SKILL_DIR=/path/to/skills/codex-session-recovery bash
```

## Layout

- `codex-session-recovery/` is the installable skill folder.
- `codex-session-recovery/scripts/scan_codex_sessions.py` scans Codex JSONL state read-only.
- `tests/fixtures/codex_home/` contains copied fixture state for tests.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` hold design and implementation planning docs.

## Verify

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_scan_codex_sessions -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_install_script -v
python /Users/wufei2/.codex/skills/.system/skill-creator/scripts/quick_validate.py codex-session-recovery
```

## Example

```bash
python codex-session-recovery/scripts/scan_codex_sessions.py \
  --codex-home "${CODEX_HOME:-$HOME/.codex}" \
  --cwd "$PWD" \
  --timezone Asia/Shanghai \
  --format table
```

The scanner is read-only. Tests copy fixture state into a temporary directory and never operate on the user's real `$CODEX_HOME`.
