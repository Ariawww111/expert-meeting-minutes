from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import SCHEMA_VERSION, read_json, utc_now, write_json


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "assets" / "normalization-rules.json"

CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

YEAR_MAP = {
    "二一年": "2021年",
    "二二年": "2022年",
    "二三年": "2023年",
    "二六年": "2026年",
    "二八年": "2028年",
    "三三年": "2033年",
}

MONTH_RANGE_RULES = [
    (re.compile(r"四五六三个月"), "4月至6月", "连续月份口述"),
    (re.compile(r"十一十二月份"), "11月至12月", "连续月份口述"),
    (re.compile(r"([一二三四五六七八九])月?([一二三四五六七八九])月份"), None, "月份区间"),
]

CHINESE_DATE_RE = re.compile(r"([一二三四五六七八九十]{1,2})月([一二三四五六七八九十]{1,3})[号日]")
CHINESE_MONTH_RE = re.compile(r"(?<![一二三四五六七八九十百千万])([一二三四五六七八九十]{1,2})月(?![一二三四五六七八九十])")


def load_rules(path: Optional[str] = None) -> Dict[str, Any]:
    rules_path = Path(path).expanduser().resolve() if path else DEFAULT_RULES_PATH
    if not rules_path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "safe_regex_rules": [],
            "ambiguous_terms": [],
        }
    return read_json(rules_path)


def chinese_number_to_int(value: str) -> Optional[int]:
    if not value:
        return None
    if value in CN_DIGITS:
        return CN_DIGITS[value]
    if "十" not in value:
        return None
    left, right = value.split("十", 1)
    tens = CN_DIGITS.get(left, 1) if left else 1
    ones = CN_DIGITS.get(right, 0) if right else 0
    return tens * 10 + ones


def _safe_year_replacements(text: str, changes: List[Dict[str, str]]) -> str:
    for source, target in YEAR_MAP.items():
        if source not in text:
            continue
        context = text[max(0, text.find(source) - 8) : text.find(source) + len(source) + 4]
        if not re.search(r"专利|延长|到|至|在|是|为|年", context):
            continue
        text = text.replace(source, target)
        changes.append(
            {
                "rule": "year-normalization",
                "before": source,
                "after": target,
                "reason": "中文年份缩写规范为四位年份",
            }
        )
    return text


def _safe_date_replacements(text: str, changes: List[Dict[str, str]]) -> str:
    for pattern, replacement, reason in MONTH_RANGE_RULES:
        if replacement is None:
            def replace_range(match: re.Match[str]) -> str:
                first = chinese_number_to_int(match.group(1))
                second = chinese_number_to_int(match.group(2))
                if first and second:
                    return "{}月至{}月".format(first, second)
                return match.group(0)

            new_text = pattern.sub(replace_range, text)
        else:
            new_text = pattern.sub(replacement, text)
        if new_text != text:
            changes.append(
                {
                    "rule": "month-range-normalization",
                    "before": pattern.pattern,
                    "after": replacement or "numeric month range",
                    "reason": reason,
                }
            )
            text = new_text

    duplicate_date_re = re.compile(
        r"([一二三四五六七八九十]{1,2})月\1月([一二三四五六七八九十]{1,3})[号日]"
    )

    def replace_duplicate_date(match: re.Match[str]) -> str:
        month = chinese_number_to_int(match.group(1))
        day = chinese_number_to_int(match.group(2))
        if month and day:
            return "{}月{}日".format(month, day)
        return match.group(0)

    new_text = duplicate_date_re.sub(replace_duplicate_date, text)
    if new_text != text:
        changes.append(
            {
                "rule": "duplicate-date-normalization",
                "before": duplicate_date_re.pattern,
                "after": "numeric date",
                "reason": "去除重复月份并规范日期",
            }
        )
        text = new_text

    duplicate_month_end_re = re.compile(r"([一二三四五六七八九十]{1,2})月\1月底")

    def replace_duplicate_month_end(match: re.Match[str]) -> str:
        month = chinese_number_to_int(match.group(1))
        if month:
            return "{}月底".format(month)
        return match.group(0)

    new_text = duplicate_month_end_re.sub(replace_duplicate_month_end, text)
    if new_text != text:
        changes.append(
            {
                "rule": "duplicate-month-normalization",
                "before": duplicate_month_end_re.pattern,
                "after": "numeric month end",
                "reason": "去除重复月份",
            }
        )
        text = new_text

    number_part = r"[一二三四五六七八九十]{1,2}|\d{1,2}"
    mixed_duplicate_date_re = re.compile(
        r"({})月({})月({})日".format(number_part, number_part, number_part)
    )

    def replace_mixed_duplicate_date(match: re.Match[str]) -> str:
        first = chinese_number_to_int(match.group(1)) or int(match.group(1))
        second = chinese_number_to_int(match.group(2)) or int(match.group(2))
        day = chinese_number_to_int(match.group(3)) or int(match.group(3))
        if first == second and first and day:
            return "{}月{}日".format(first, day)
        return match.group(0)

    new_text = mixed_duplicate_date_re.sub(replace_mixed_duplicate_date, text)
    if new_text != text:
        changes.append(
            {
                "rule": "mixed-duplicate-date-normalization",
                "before": mixed_duplicate_date_re.pattern,
                "after": "numeric date",
                "reason": "去除重复数字月份",
            }
        )
        text = new_text

    mixed_duplicate_month_end_re = re.compile(
        r"({})月({})月底".format(number_part, number_part)
    )

    def replace_mixed_duplicate_month_end(match: re.Match[str]) -> str:
        first = chinese_number_to_int(match.group(1)) or int(match.group(1))
        second = chinese_number_to_int(match.group(2)) or int(match.group(2))
        if first == second and first:
            return "{}月底".format(first)
        return match.group(0)

    new_text = mixed_duplicate_month_end_re.sub(
        replace_mixed_duplicate_month_end,
        text,
    )
    if new_text != text:
        changes.append(
            {
                "rule": "mixed-duplicate-month-normalization",
                "before": mixed_duplicate_month_end_re.pattern,
                "after": "numeric month end",
                "reason": "去除重复数字月份",
            }
        )
        text = new_text

    shorthand_context = re.search(r"六三零", text)
    if shorthand_context:
        nearby = text[max(0, shorthand_context.start() - 12) : shorthand_context.end() + 12]
        if re.search(r"之前|拿到|获批|批文|截止", nearby):
            text = text.replace("六三零", "6月30日")
            changes.append(
                {
                    "rule": "date-630",
                    "before": "六三零",
                    "after": "6月30日",
                    "reason": "上下文明确为6月30日节点",
                }
            )

    def replace_date(match: re.Match[str]) -> str:
        month = chinese_number_to_int(match.group(1))
        day = chinese_number_to_int(match.group(2))
        if month and day:
            return "{}月{}日".format(month, day)
        return match.group(0)

    new_text = CHINESE_DATE_RE.sub(replace_date, text)
    if new_text != text:
        changes.append(
            {
                "rule": "date-normalization",
                "before": CHINESE_DATE_RE.pattern,
                "after": "numeric date",
                "reason": "中文日期规范为数字日期",
            }
        )
        text = new_text

    def replace_month(match: re.Match[str]) -> str:
        month = chinese_number_to_int(match.group(1))
        if month:
            return "{}月".format(month)
        return match.group(0)

    new_text = CHINESE_MONTH_RE.sub(replace_month, text)
    if new_text != text:
        changes.append(
            {
                "rule": "month-normalization",
                "before": CHINESE_MONTH_RE.pattern,
                "after": "numeric month",
                "reason": "中文月份规范为数字月份",
            }
        )
        text = new_text
    return text


def normalize_text(text: str, rules: Dict[str, Any]) -> tuple[str, List[Dict[str, str]]]:
    changes: List[Dict[str, str]] = []
    normalized = _safe_year_replacements(text, changes)
    normalized = _safe_date_replacements(normalized, changes)
    for rule in rules.get("safe_regex_rules", []):
        pattern = str(rule.get("pattern", ""))
        replacement = str(rule.get("replacement", ""))
        if not pattern:
            continue
        context_pattern = str(rule.get("context", ""))
        matches = list(re.finditer(pattern, normalized))
        if not matches:
            continue
        for match in reversed(matches):
            if context_pattern:
                nearby = normalized[
                    max(0, match.start() - 16) : min(len(normalized), match.end() + 16)
                ]
                if not re.search(context_pattern, nearby):
                    continue
            before = match.group(0)
            if before == replacement:
                continue
            normalized = normalized[: match.start()] + replacement + normalized[match.end() :]
            changes.append(
                {
                    "rule": str(rule.get("id", "safe-rule")),
                    "before": before,
                    "after": replacement,
                    "reason": str(rule.get("reason", "")),
                }
            )
    return normalized, changes


def normalize_transcript(
    transcript_path: str,
    out_dir: str,
    rules_path: Optional[str] = None,
) -> Dict[str, Any]:
    transcript_file = Path(transcript_path).expanduser().resolve()
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    transcript = read_json(transcript_file)
    rules = load_rules(rules_path)
    audit = []
    for segment in transcript.get("segments", []):
        before = str(segment.get("text", ""))
        after, changes = normalize_text(before, rules)
        if after == before:
            continue
        segment["text"] = after
        audit.append(
            {
                "segment_id": segment.get("id"),
                "time_range": [segment.get("start"), segment.get("end")],
                "before": before,
                "after": after,
                "changes": changes,
            }
        )
    if audit:
        transcript["updated_at"] = utc_now()
    write_json(transcript_file, transcript)
    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "transcript_sha256": transcript.get("audio", {}).get("sha256"),
        "changed_segments": len(audit),
        "changes": audit,
    }
    write_json(output / "normalization-audit.json", result)
    return result


def ambiguous_term_matches(text: str, rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    matches = []
    for entry in rules.get("ambiguous_terms", []):
        if not isinstance(entry, dict):
            continue
        observed = str(entry.get("observed", ""))
        if observed and observed in text:
            matches.append(entry)
    return matches


def apply_proposal_markdown(
    transcript_path: str,
    proposal_path: str,
    out_dir: str,
) -> Dict[str, Any]:
    transcript_file = Path(transcript_path).expanduser().resolve()
    proposal_file = Path(proposal_path).expanduser().resolve()
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    transcript = read_json(transcript_file)
    segment_map = {
        str(segment.get("id")): segment for segment in transcript.get("segments", [])
    }
    text = proposal_file.read_text(encoding="utf-8")
    section_pattern = re.compile(
        r"^###\s+\S+\s+(S\d+)\s+.*?\n(.*?)(?=^###\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    recommendation_pattern = re.compile(r"^- 建议：(.*)$", re.MULTILINE)
    applied = []
    for section in section_pattern.finditer(text):
        segment_id = section.group(1)
        recommendation = recommendation_pattern.search(section.group(2))
        if not recommendation:
            continue
        replacement = recommendation.group(1).strip()
        segment = segment_map.get(segment_id)
        if not segment or not replacement:
            continue
        before = str(segment.get("text", ""))
        if before == replacement:
            continue
        segment["text"] = replacement
        applied.append(
            {
                "segment_id": segment_id,
                "time_range": [segment.get("start"), segment.get("end")],
                "before": before,
                "after": replacement,
            }
        )
    if applied:
        transcript["updated_at"] = utc_now()
    write_json(transcript_file, transcript)
    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "proposal_path": str(proposal_file),
        "changed_segments": len(applied),
        "changes": applied,
    }
    write_json(output / "proposal-application.json", result)
    return result
