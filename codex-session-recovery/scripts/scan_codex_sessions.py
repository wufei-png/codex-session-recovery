#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


@dataclass
class MutableRecord:
    thread_id: str
    cwd: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    archived_sources: int = 0
    active_sources: int = 0
    subagent: bool = False
    source_paths: set[str] = field(default_factory=set)
    referenced_paths: set[str] = field(default_factory=set)
    evidence_types: set[str] = field(default_factory=set)
    user_prompts: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: int = 0
    matching_reasons: list[str] = field(default_factory=list)

    @property
    def archived(self) -> bool:
        return self.archived_sources > 0 and self.active_sources == 0

    def merge_source(self, source_path: Path, archived: bool, evidence_type: str) -> None:
        self.source_paths.add(str(source_path))
        self.evidence_types.add(evidence_type)
        if archived:
            self.archived_sources += 1
        else:
            self.active_sources += 1

    def absorb(self, other: "MutableRecord") -> None:
        if self.cwd is None and other.cwd is not None:
            self.cwd = other.cwd
        self.started_at = earlier(self.started_at, other.started_at)
        self.updated_at = later(self.updated_at, other.updated_at)
        self.archived_sources += other.archived_sources
        self.active_sources += other.active_sources
        self.subagent = self.subagent or other.subagent
        self.source_paths.update(other.source_paths)
        self.referenced_paths.update(other.referenced_paths)
        self.evidence_types.update(other.evidence_types)
        self.user_prompts.extend(other.user_prompts)
        self.summaries.extend(other.summaries)
        self.warnings.extend(other.warnings)


class ScannerInputError(ValueError):
    pass


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def local_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


def timezone_from_option(value: str | None) -> tzinfo:
    if value:
        try:
            return ZoneInfo(value)
        except Exception as exc:
            raise ScannerInputError(f"invalid timezone {value!r}") from exc
    return local_timezone()


def timezone_label(value: str | None, resolved: tzinfo) -> str:
    return value or str(resolved)


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_boundary(value: str | None, tz: tzinfo, end_of_day: bool = False) -> datetime | None:
    if value is None:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
        parsed_time = time.max if end_of_day else time.min
        return datetime.combine(parsed_date, parsed_time, tzinfo=tz)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScannerInputError(f"invalid date or datetime {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed


def earlier(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def later(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def is_archived_path(path: Path) -> bool:
    return "archived_sessions" in path.parts


def candidate_paths(codex_home: Path, include_archived: bool) -> list[Path]:
    paths: list[Path] = []
    session_index = codex_home / "session_index.jsonl"
    if session_index.exists():
        paths.append(session_index)
    sessions_dir = codex_home / "sessions"
    if sessions_dir.exists():
        paths.extend(sorted(sessions_dir.glob("**/*.jsonl")))
    archived_dir = codex_home / "archived_sessions"
    if include_archived and archived_dir.exists():
        paths.extend(sorted(archived_dir.glob("*.jsonl")))
    return paths


def searched_paths(codex_home: Path, include_archived: bool) -> list[str]:
    paths = [
        str(codex_home / "session_index.jsonl"),
        str(codex_home / "sessions" / "**" / "*.jsonl"),
    ]
    if include_archived:
        paths.append(str(codex_home / "archived_sessions" / "*.jsonl"))
    return paths


def id_from_filename(path: Path) -> str | None:
    uuid_match = UUID_RE.search(path.name)
    if uuid_match:
        return uuid_match.group(0)
    match = re.search(r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)\.jsonl$", path.name)
    if match:
        return match.group(1)
    return None


def timestamp_from_filename(path: Path, tz: tzinfo) -> datetime | None:
    match = re.search(r"rollout-(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-", path.name)
    if not match:
        return None
    date_part, hour, minute, second = match.groups()
    try:
        parsed_date = datetime.strptime(date_part, "%Y-%m-%d").date()
    except ValueError:
        return None
    parsed_time = time(int(hour), int(minute), int(second))
    return datetime.combine(parsed_date, parsed_time, tzinfo=tz)


def apply_filename_timestamp(record: MutableRecord, path: Path, fallback_timezone: tzinfo) -> None:
    if record.started_at is not None or record.updated_at is not None:
        return
    filename_timestamp = timestamp_from_filename(path, fallback_timezone)
    if filename_timestamp is None:
        return
    record.started_at = filename_timestamp
    record.updated_at = filename_timestamp
    record.evidence_types.add("filename_timestamp")
    record.matching_reasons.append("filename fallback timestamp")


def extract_content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(part for part in parts if part).strip() or None
    return None


def is_subagent_source(source: Any) -> bool:
    if source == "subagent":
        return True
    if isinstance(source, dict):
        return bool(source.get("subagent"))
    return False


def record_from_index_line(
    obj: dict[str, Any], path: Path, line_number: int, warnings: list[str]
) -> MutableRecord | None:
    thread_id = obj.get("id") or obj.get("thread_id") or obj.get("session_id")
    if not isinstance(thread_id, str):
        warnings.append(f"{path}:{line_number}: missing thread id; skipped record")
        return None
    path_hint = obj.get("path")
    archived = isinstance(path_hint, str) and path_hint.startswith("archived_sessions/")
    record = MutableRecord(thread_id=thread_id)
    record.merge_source(path, archived, "index")
    if isinstance(path_hint, str):
        record.referenced_paths.add(path_hint)
    cwd = obj.get("cwd")
    if isinstance(cwd, str):
        record.cwd = cwd
    record.started_at = parse_timestamp(obj.get("created_at") or obj.get("started_at"))
    record.updated_at = parse_timestamp(obj.get("updated_at") or obj.get("timestamp"))
    record.subagent = is_subagent_source(obj.get("source"))
    summary = obj.get("summary") or obj.get("title")
    if isinstance(summary, str):
        record.summaries.append(summary)
    return record


def payload_for(obj: dict[str, Any]) -> dict[str, Any]:
    payload = obj.get("payload")
    if isinstance(payload, dict):
        return payload
    return obj


def note_naive_timestamp(
    record: MutableRecord | None, warnings: list[str], path: Path, line_number: int, stamp: datetime | None
) -> datetime | None:
    if stamp is None:
        return None
    if stamp.tzinfo is not None:
        return stamp
    warning = f"{path}:{line_number}: naive timestamp interpreted using filter timezone"
    warnings.append(warning)
    if record is not None:
        record.warnings.append(warning)
    return stamp


def normalize_event_timestamp(
    record: MutableRecord | None,
    warnings: list[str],
    path: Path,
    line_number: int,
    stamp: datetime | None,
    fallback_timezone: tzinfo,
) -> datetime | None:
    noted = note_naive_timestamp(record, warnings, path, line_number, stamp)
    if noted is not None and noted.tzinfo is None:
        return noted.replace(tzinfo=fallback_timezone)
    return noted


def parse_jsonl(
    path: Path, include_archived: bool, fallback_timezone: tzinfo
) -> tuple[list[MutableRecord], list[str]]:
    archived = is_archived_path(path)
    if archived and not include_archived:
        return [], []

    warnings: list[str] = []
    records: list[MutableRecord] = []
    current: MutableRecord | None = None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{path}: unreadable: {exc}"]

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"{path}:{line_number}: malformed JSON")
            continue
        if not isinstance(obj, dict):
            continue

        if path.name == "session_index.jsonl":
            indexed = record_from_index_line(obj, path, line_number, warnings)
            if indexed is not None and (include_archived or not indexed.archived):
                records.append(indexed)
            continue

        payload = payload_for(obj)
        event_time = parse_timestamp(obj.get("timestamp") or payload.get("timestamp"))
        event_time = normalize_event_timestamp(
            current, warnings, path, line_number, event_time, fallback_timezone
        )

        if obj.get("type") == "session_meta" or "cwd" in payload or "id" in payload:
            thread_id = payload.get("id") or payload.get("thread_id") or id_from_filename(path)
            if not isinstance(thread_id, str):
                warnings.append(f"{path}:{line_number}: missing thread id; skipped record")
                continue
            if current is None:
                current = MutableRecord(thread_id=thread_id)
                current.merge_source(path, archived, "transcript")
                if event_time is None:
                    apply_filename_timestamp(current, path, fallback_timezone)
            if payload.get("id") is None and payload.get("thread_id") is None:
                current.evidence_types.add("filename_identity")
            current.thread_id = thread_id
            cwd = payload.get("cwd")
            if isinstance(cwd, str):
                current.cwd = cwd
            current.started_at = earlier(current.started_at, event_time)
            current.updated_at = later(current.updated_at, event_time)
            current.subagent = current.subagent or is_subagent_source(payload.get("source"))
            continue

        if current is None:
            fallback_id = id_from_filename(path)
            if fallback_id is None:
                warnings.append(f"{path}:{line_number}: missing thread id; skipped record")
                continue
            current = MutableRecord(thread_id=fallback_id)
            current.merge_source(path, archived, "transcript")
            current.evidence_types.add("filename_identity")
            if event_time is None:
                apply_filename_timestamp(current, path, fallback_timezone)
        current.started_at = earlier(current.started_at, event_time)
        current.updated_at = later(current.updated_at, event_time)

        role = payload.get("role")
        if role == "user":
            text = extract_content_text(payload.get("content"))
            if text:
                current.user_prompts.append(text)

        summary = payload.get("summary") or payload.get("title")
        if isinstance(summary, str):
            current.summaries.append(summary)

    if current is not None:
        current.warnings.extend(warnings)
        records.append(current)
    elif warnings:
        fallback_id = id_from_filename(path)
        if fallback_id is not None:
            record = MutableRecord(thread_id=fallback_id)
            record.merge_source(path, archived, "transcript")
            record.evidence_types.add("filename_identity")
            apply_filename_timestamp(record, path, fallback_timezone)
            record.warnings.extend(warnings)
            records.append(record)
    return records, warnings


def merge_records(records: list[MutableRecord]) -> dict[str, MutableRecord]:
    merged: dict[str, MutableRecord] = {}
    for record in records:
        existing = merged.get(record.thread_id)
        if existing is None:
            merged[record.thread_id] = record
        else:
            existing.absorb(record)
    for record in merged.values():
        if record.active_sources and record.archived_sources:
            record.warnings.append("appears in active and archived sources")
    return merged


def normalize_path(value: str | None) -> str | None:
    if not value:
        return None
    return str(Path(value).expanduser())


def matches_cwd(record: MutableRecord, cwd: str | None) -> bool:
    if cwd is None:
        return True
    target = normalize_path(cwd)
    actual = normalize_path(record.cwd)
    return actual == target


def searchable_blob(record: MutableRecord) -> str:
    return "\n".join(
        [
            record.thread_id,
            record.cwd or "",
            "\n".join(record.user_prompts),
            "\n".join(record.summaries),
            "\n".join(record.source_paths),
        ]
    )


def matches_query(record: MutableRecord, query: str | None) -> bool:
    if query is None:
        return True
    return query.casefold() in searchable_blob(record).casefold()


def normalize_stamp(record: MutableRecord, stamp: datetime, fallback_timezone: tzinfo) -> datetime:
    if stamp.tzinfo is not None:
        return stamp
    warning = "naive timestamp interpreted using filter timezone"
    if warning not in record.warnings:
        record.warnings.append(warning)
    return stamp.replace(tzinfo=fallback_timezone)


def matches_dates(
    record: MutableRecord, since: datetime | None, until: datetime | None, fallback_timezone: tzinfo
) -> bool:
    stamp = record.updated_at or record.started_at
    if stamp is None:
        return True
    stamp = normalize_stamp(record, stamp, fallback_timezone)
    if since is not None and stamp < since:
        return False
    if until is not None and stamp > until:
        return False
    return True


def score_record(record: MutableRecord, cwd: str | None, query: str | None) -> None:
    score = 0
    reasons: list[str] = list(record.matching_reasons)
    has_primary_evidence = "transcript" in record.evidence_types
    if not has_primary_evidence:
        reasons.append("index-only evidence")
        if not any("index-only evidence" in warning for warning in record.warnings):
            record.warnings.append("index-only evidence; referenced transcript absent")
    if cwd is not None and matches_cwd(record, cwd):
        score += 60 if has_primary_evidence else 20
        reasons.append("cwd exact match")
    if not record.archived and has_primary_evidence:
        score += 10
        reasons.append("active source")
    if not record.subagent and has_primary_evidence:
        score += 10
        reasons.append("main session")
    if query is not None and matches_query(record, query):
        score += 20
        reasons.append("query match")
    if record.user_prompts:
        score += 5
        reasons.append("has user prompts")
    record.score = score
    record.matching_reasons = reasons


def short_prompt(record: MutableRecord, show_prompts: bool) -> tuple[str | None, str | None]:
    if not show_prompts or not record.user_prompts:
        return None, None
    first = record.user_prompts[0][:160]
    last = record.user_prompts[-1][:160]
    return first, last


def serialize_record(record: MutableRecord, show_prompts: bool) -> dict[str, Any]:
    first_prompt, last_prompt = short_prompt(record, show_prompts)
    return {
        "thread_id": record.thread_id,
        "cwd": record.cwd,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "archived": record.archived,
        "subagent": record.subagent,
        "source_paths": sorted(record.source_paths),
        "first_user_prompt": first_prompt,
        "last_user_prompt": last_prompt,
        "matching_reasons": record.matching_reasons,
        "confidence": record.score,
        "resume_command": f"codex resume {record.thread_id}",
        "fork_command": f"codex fork {record.thread_id}",
        "deep_link": f"codex://threads/{record.thread_id}",
        "warnings": record.warnings,
    }


def build_filters(
    options: dict[str, Any],
    resolved_timezone_label: str,
    include_archived: bool,
    include_subagents: bool,
    limit: int,
) -> dict[str, Any]:
    return {
        "codex_home": str(Path(options["codex_home"]).expanduser()),
        "cwd": options.get("cwd"),
        "since": options.get("since"),
        "until": options.get("until"),
        "timezone": resolved_timezone_label,
        "query": options.get("query"),
        "include_archived": include_archived,
        "include_subagents": include_subagents,
        "limit": limit,
    }


def scan(options: dict[str, Any]) -> dict[str, Any]:
    codex_home = Path(options["codex_home"]).expanduser()
    include_archived = bool(options.get("include_archived", False))
    include_subagents = bool(options.get("include_subagents", False))
    cwd = options.get("cwd")
    query = options.get("query")
    timezone_option = options.get("timezone")
    resolved_timezone = timezone_from_option(timezone_option)
    resolved_timezone_label = timezone_label(timezone_option, resolved_timezone)
    since = parse_boundary(options.get("since"), resolved_timezone)
    until = parse_boundary(options.get("until"), resolved_timezone, end_of_day=True)
    limit = int(options.get("limit") or 20)
    show_prompts = bool(options.get("show_prompts", False))
    filters = build_filters(
        options, resolved_timezone_label, include_archived, include_subagents, limit
    )

    warnings: list[str] = []
    if not codex_home.exists():
        return {
            "codex_home": str(codex_home),
            "records": [],
            "warnings": [f"{codex_home} does not exist"],
            "filters": filters,
            "searched_paths": searched_paths(codex_home, include_archived),
        }

    parsed_records: list[MutableRecord] = []
    for path in candidate_paths(codex_home, include_archived):
        records, path_warnings = parse_jsonl(path, include_archived, resolved_timezone)
        parsed_records.extend(records)
        warnings.extend(path_warnings)

    merged = merge_records(parsed_records)
    filtered: list[MutableRecord] = []
    for record in merged.values():
        if record.archived and not include_archived:
            continue
        if record.subagent and not include_subagents:
            continue
        if not matches_cwd(record, cwd):
            continue
        if not matches_query(record, query):
            continue
        if not matches_dates(record, since, until, resolved_timezone):
            continue
        score_record(record, cwd, query)
        filtered.append(record)

    floor = datetime.min.replace(tzinfo=resolved_timezone)
    filtered.sort(
        key=lambda item: (
            item.score,
            item.updated_at or item.started_at or floor,
            item.thread_id,
        ),
        reverse=True,
    )
    selected = filtered[:limit]
    return {
        "codex_home": str(codex_home),
        "records": [serialize_record(record, show_prompts) for record in selected],
        "warnings": warnings,
        "filters": filters,
        "searched_paths": searched_paths(codex_home, include_archived),
    }


def format_table(result: dict[str, Any]) -> str:
    lines = [f"codex_home: {result['codex_home']}"]
    for index, record in enumerate(result["records"], start=1):
        flags = []
        if record["archived"]:
            flags.append("archived")
        if record["subagent"]:
            flags.append("subagent")
        if not flags:
            flags.append("active-main")
        if index > 1:
            lines.append("")
        lines.extend(
            [
                f"thread_id: {record['thread_id']}",
                f"confidence: {record['confidence']}",
                f"flags: {', '.join(flags)}",
                f"cwd: {record['cwd'] or ''}",
                f"started_at: {record['started_at'] or ''}",
                f"updated_at: {record['updated_at'] or ''}",
                f"matching reasons: {', '.join(record['matching_reasons']) or 'none'}",
                "source paths:",
            ]
        )
        lines.extend(f"- {source_path}" for source_path in record["source_paths"])
        lines.extend(
            [
                f"resume: {record['resume_command']}",
                f"fork: {record['fork_command']}",
                f"deep link: {record['deep_link']}",
            ]
        )
        if record.get("first_user_prompt") is not None:
            lines.append(f"first prompt: {record['first_user_prompt']}")
        if record.get("last_user_prompt") is not None:
            lines.append(f"last prompt: {record['last_user_prompt']}")
        if record["warnings"]:
            lines.append("record warnings:")
            lines.extend(f"- {warning}" for warning in record["warnings"])
    if result["warnings"]:
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    if not result["records"]:
        lines.append("")
        lines.append("searched paths:")
        lines.extend(f"- {path}" for path in result.get("searched_paths", []))
        lines.append("")
        lines.append("No matching sessions found. Relax cwd, date, archive, subagent, or query filters.")
        lines.append("Manual check: codex resume --all")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find local Codex sessions safely.")
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--cwd")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--timezone", default=None)
    parser.add_argument("--query")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--include-subagents", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.add_argument("--show-prompts", action="store_true")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser_argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        args = parser.parse_args(parser_argv)
        result = scan(vars(args))
    except ScannerInputError as exc:
        parser.error(str(exc))
        return 2
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_table(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
