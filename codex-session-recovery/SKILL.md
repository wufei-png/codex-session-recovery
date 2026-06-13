---
name: codex-session-recovery
description: Find Codex session and thread IDs from read-only local Codex session history or copied fixtures, then produce CLI-first recovery instructions. Use when Codex history appears lost after account or provider changes, Codex Desktop does not show older threads, or the user asks to find, resume, fork, recover, pin, or make visible a prior Codex session. Optionally, when the current Codex environment exposes the required thread tools and the user explicitly requests Desktop visibility, create, title, and pin a helper thread.
---

# Codex Session Recovery

## Purpose

Recover practical access to local Codex session history without mutating live Codex state by default.

Default to CLI-first recovery:

- Find candidate local sessions from `CODEX_HOME`.
- Explain confidence and matching reasons.
- Output recovery suggestions such as `codex resume active-main`, `codex fork active-main`, and `codex://threads/active-main`.

Desktop visibility is optional. It is not inferred from being in a Codex Desktop context.

## Safety Rules

Do this by default:

- Read local Codex JSONL state only.
- Prefer copied fixtures or temporary copies for testing.
- Exclude archived sessions unless the user requests them.
- Exclude subagent sessions unless the user requests them.
- Print short prompt snippets only when useful; do not dump full transcripts by default.

Do not do this unless the user explicitly requests it:

- Include archived sessions.
- Include subagent sessions.
- Print longer transcript excerpts.
- Create, rename, pin, unpin, archive, or unarchive Desktop threads.

Never do this as part of this skill:

- Edit real `$CODEX_HOME`.
- Edit SQLite-backed state, including a local `state_5.sqlite` file if present.
- Copy rollout JSONL files into live Codex state.
- Import arbitrary JSONL history into Codex Desktop.
- Rewrite provider or account metadata.

## Scanner

Use the bundled scanner for deterministic discovery:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/codex-session-recovery/scripts/scan_codex_sessions.py" \
  --codex-home "${CODEX_HOME:-$HOME/.codex}" \
  --cwd "/Users/example/project" \
  --since "2026-06-10" \
  --timezone "Asia/Shanghai" \
  --format table
```

When using the skill from a development checkout, run:

```bash
python codex-session-recovery/scripts/scan_codex_sessions.py --codex-home /tmp/copied-codex-home --format json
```

Useful options:

- `--cwd PATH`: filter by session working directory.
- `--since DATE_OR_DATETIME`: include sessions at or after this time.
- `--until DATE_OR_DATETIME`: include sessions at or before this time.
- `--timezone NAME`: interpret date-only filters in this timezone.
- `--query TEXT`: match user prompts, paths, and summaries.
- `--include-archived`: include archived sessions.
- `--include-subagents`: include subagent sessions.
- `--show-prompts`: show short prompt snippets.
- `--format table|json`: choose human or automation output.

## Desktop Visibility Flow

Desktop actions are capability-gated. A Codex Desktop context is not enough.

Before any Desktop-visible action, call `tool_search` in the current conversation for the exact thread tools needed:

- `fork_thread`: create a Desktop-visible fork from the recovered thread id.
- `set_thread_title`: give the visible fork a clear recovery title.
- `set_thread_pinned`: pin the visible fork in the sidebar.
- `list_threads` or `read_thread`: verify the visible fork exists.

Desktop-visible recovery steps:

1. Select one candidate thread id from scanner output and keep the original id in the response.
2. Prepare a dry-run with the target id, proposed title, and pin action.
3. If the user already authorized Desktop visibility, call `fork_thread` for the selected thread id; otherwise show the dry-run first and wait.
4. Call `set_thread_title` on the new visible thread.
5. Call `set_thread_pinned` with pin enabled on the new visible thread.
6. Verify with `list_threads` or `read_thread`.
7. Report the visible thread id, original recovered thread id, and CLI fallbacks.

If any required tool is missing or `fork_thread` cannot access the recovered id, do not edit local state or SQLite-backed state. Fall back to CLI commands and deep links. Create a fresh pointer thread only when the user explicitly asks for that and `create_thread` is available in the current conversation.

Decision table:

| Runtime capability | User request | Action |
| --- | --- | --- |
| Missing required thread tools | Any request | Output CLI commands and deep links only. |
| Required tools available | User did not ask for Desktop visibility | Output CLI commands and mention Desktop visibility as optional. |
| Required tools available | User asked for Desktop visibility | Show the proposed fork/title/pin actions first, then execute only when authorized. Verify with `list_threads` or `read_thread`. |

When creating Desktop-visible helper threads, make titles explicit, for example:

```text
Recovered Codex session: upload flow investigation
```

Report that the helper thread is a visible fork or pointer, not a byte-for-byte import of JSONL history into Desktop state.

## Output Shape

For each likely session, report:

- thread id
- cwd
- updated time
- archived/subagent flags
- matching reasons
- confidence
- source JSONL path
- `codex resume active-main`
- `codex fork active-main`
- `codex://threads/active-main`

If no matches are found, report the exact filters used and suggest relaxing one filter at a time.
