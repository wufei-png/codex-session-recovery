# codex-session-recovery

Reusable Codex skill for finding local Codex session history and producing safe, CLI-first recovery instructions.

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
