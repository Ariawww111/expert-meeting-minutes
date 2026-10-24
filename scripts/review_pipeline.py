from __future__ import annotations

import copy
import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import (
    SCHEMA_VERSION,
    SELF_CORRECTION_RE,
    SUSPICIOUS_TERM_RE,
    extract_numeric_tokens,
    format_timecode,
    load_glossary,
    read_json,
    sha256_json,
    stable_issue_id,
    utc_now,
    write_json,
)
from normalization import ambiguous_term_matches, load_rules


KNOWN_TERMS = {
    "AI",
    "ASCO",
    "CDE",
    "CFTR",
    "CTLA",
    "CTDNA",
    "DNA",
    "EMA",
    "FDA",
    "GLP",
    "GRAIL",
    "GSK",
    "HR",
    "IND",
    "KEYTRUDA",
    "LNP",
    "MNC",
    "MRNA",
    "NMPA",
    "NSCLC",
    "OS",
    "PK",
    "RFS",
    "DMFS",
    "RNA",
    "US",
    "USA",
    "TMB",
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _known_term(observed: str, glossary: Dict[str, Any], text: str) -> bool:
    value = observed.strip().upper()
    if value in {"PD", "PK"} and re.search(
        r"(?:PD-?1|PK\s*/\s*PD)",
        text,
        re.IGNORECASE,
    ):
        return True
    if value in KNOWN_TERMS:
        return True
    for entry in glossary.get("terms", []):
        if not isinstance(entry, dict):
            continue
        variants = [entry.get("term", "")]
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            variants.extend(aliases)
        if any(str(variant).strip().upper() == value for variant in variants if variant):
            return True
    return False


def _issue_id(segment_id: str, kind: str) -> str:
    # Segment based identifiers survive transcript corrections and re-generation.
    return stable_issue_id("", segment_id, kind)


def _near_glossary_matches(
    text: str,
    glossary: Dict[str, Any],
) -> List[str]:
    compact_text = _compact(text)
    candidates = []
    for entry in glossary.get("terms", []):
        if not isinstance(entry, dict):
            continue
        variants = [entry.get("term", "")]
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            variants.extend(aliases)
        for variant in variants:
            variant = str(variant).strip()
            if not variant:
                continue
            compact_variant = _compact(variant)
            if compact_variant in compact_text:
                continue
            shortest = max(2, min(len(compact_variant), 12))
            windows = set()
            for length in range(shortest, min(len(compact_text), len(compact_variant) + 3) + 1):
                for start in range(0, max(0, len(compact_text) - length + 1)):
                    window = compact_text[start : start + length]
                    if difflib.SequenceMatcher(None, window, compact_variant).ratio() >= 0.82:
                        windows.add(window)
            candidates.extend(sorted(windows)[:2])
    return sorted(set(candidates))


def _review_segment_issue(
    transcript_hash: str,
    segment: Dict[str, Any],
    glossary: Dict[str, Any],
    normalization_rules: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    text = str(segment.get("text", ""))
    reasons: List[str] = []
    kinds: List[str] = []
    candidates: List[str] = []

    numeric = extract_numeric_tokens(text)
    if numeric:
        kinds.append("number")
        reasons.append("数字或单位需要人工确认")
        candidates.extend(numeric)

    glossary_candidates = _near_glossary_matches(text, glossary)
    if glossary_candidates:
        kinds.append("term")
        reasons.append("检测到疑似术语转写偏差")
        candidates.extend(glossary_candidates)

    suspicious_terms = [
        match.group(0)
        for match in SUSPICIOUS_TERM_RE.finditer(text)
        if not _known_term(match.group(0), glossary, text)
    ]
    if suspicious_terms:
        kinds.append("term")
        reasons.append("检测到专业缩写或行业术语")
        candidates.extend(suspicious_terms)

    ambiguous_terms = ambiguous_term_matches(text, normalization_rules)
    if ambiguous_terms:
        kinds.append("term")
        candidates.extend(
            candidate
            for entry in ambiguous_terms
            for candidate in entry.get("candidates", [])
        )
        reasons.extend(
            str(entry.get("reason", "术语存在多个候选，需要人工确认"))
            for entry in ambiguous_terms
        )

    if SELF_CORRECTION_RE.search(text):
        kinds.append("self_correction")
        reasons.append("专家出现自我更正或口误提示")

    if not kinds:
        return None
    kinds = sorted(set(kinds))
    kind = kinds[0] if len(kinds) == 1 else "mixed"
    return {
        "id": _issue_id(str(segment["id"]), kind),
        "kind": kind,
        "kinds": kinds,
        "segment_ids": [segment["id"]],
        "time_range": [segment["start"], segment["end"]],
        "quote": text,
        "candidates": sorted(set(candidates)),
        "reason": "；".join(dict.fromkeys(reasons)),
        "source_checks": [],
        "status": "open",
        "replacement_text": None,
        "note": None,
    }


def _coverage_issue(transcript_hash: str, gap: Dict[str, Any]) -> Dict[str, Any]:
    segment_id = "GAP-{:.3f}-{:.3f}".format(float(gap["start"]), float(gap["end"]))
    return {
        "id": _issue_id(segment_id, "coverage_gap"),
        "kind": "coverage_gap",
        "kinds": ["coverage_gap"],
        "segment_ids": [],
        "time_range": [gap["start"], gap["end"]],
        "quote": "",
        "candidates": [],
        "reason": "VAD 检测到有声区间，但该区间没有对应转写",
        "source_checks": [],
        "status": "open",
        "replacement_text": None,
        "note": None,
    }


def _issue_markdown(issues: List[Dict[str, Any]]) -> str:
    lines = [
        "# 人工复核清单",
        "",
        "将每一项 `status` 改为 `confirmed`。如转写有误，把 `replacement_text` 填为修正后的完整句子；如原文正确，将 `replacement_text` 设为与原引文相同。覆盖缺口需在 `note` 写明回听结论。",
        "",
    ]
    if any(issue.get("kind") == "coverage_gap" for issue in issues):
        lines.extend(
            [
                "覆盖缺口没有可替换的原文，不需要填写 `replacement_text`；必须在 `note` 中写明回听或补录结论。",
                "",
            ]
        )
    if not issues:
        lines.append("没有待核项。")
    for issue in issues:
        start, end = issue["time_range"]
        lines.extend(
            [
                "## {} {}".format(issue["id"], issue["kind"]),
                "",
                "- 时间：{} 至 {}".format(format_timecode(start), format_timecode(end)),
                "- 原因：{}".format(issue["reason"]),
                "- 原文：{}".format(issue["quote"] or "（无转写）"),
                "- 候选：{}".format("、".join(issue["candidates"]) or "无"),
                "- 状态：{}".format(issue["status"]),
                "",
            ]
        )
    lines.extend(
        [
            "## 来源核验记录格式",
            "",
            '在 `source_checks` 中填写：`{"query": "...", "url": "...", "evidence": "...", "retrieved_at": "..."}`。',
            "来源只用于确认术语或转写候选，不能向正式纪要添加上下文、评价或投资判断。",
            "",
        ]
    )
    return "\n".join(lines)


def _proposal_markdown(issues: List[Dict[str, Any]]) -> str:
    lines = [
        "# 人工复核提案",
        "",
        "在“建议”行填写整句修正。确认后运行 `apply-proposal`；未修改或保留原句的条目可按原转写确认。",
        "",
    ]
    for issue in issues:
        start, end = issue["time_range"]
        segment_id = (
            issue.get("segment_ids", [None])[0]
            if issue.get("segment_ids")
            else "COVERAGE-GAP"
        )
        suggestion = issue.get("quote", "") or "（此处需要回听后补录；覆盖缺口不填写整句替换）"
        lines.extend(
            [
                "### {} {} {}".format(
                    issue["id"],
                    segment_id,
                    format_timecode(start),
                ),
                "",
                "- 原句：{}".format(issue.get("quote", "") or "（无转写）"),
                "- 建议：{}".format(suggestion),
                "- 备注：{}".format(
                    "覆盖缺口需回听确认"
                    if issue.get("kind") == "coverage_gap"
                    else "待用户确认"
                ),
                "",
            ]
        )
    return "\n".join(lines)


def _merge_existing_confirmations(
    new_review: Dict[str, Any],
    previous_review: Optional[Dict[str, Any]],
) -> None:
    if not previous_review:
        return
    previous_by_id = {
        issue.get("id"): issue
        for issue in previous_review.get("issues", [])
        if isinstance(issue, dict) and issue.get("id")
    }
    for issue in new_review.get("issues", []):
        previous = previous_by_id.get(issue.get("id"))
        if not previous:
            continue
        for field in ("source_checks", "status", "replacement_text", "note"):
            if field in previous:
                issue[field] = copy.deepcopy(previous[field])


def _apply_confirmed_replacements(
    transcript: Dict[str, Any],
    review: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    segment_map = {
        segment["id"]: segment
        for segment in transcript.get("segments", [])
        if segment.get("id")
    }
    changed = 0
    for issue in review.get("issues", []):
        if issue.get("status") != "confirmed":
            continue
        replacement = issue.get("replacement_text")
        for segment_id in issue.get("segment_ids", []):
            segment = segment_map.get(segment_id)
            if not segment or not isinstance(replacement, str):
                continue
            if replacement.strip() and segment.get("text") != replacement:
                segment["text"] = replacement
                changed += 1
    transcript["updated_at"] = utc_now()
    return changed, transcript


def _update_glossary_from_review(
    glossary: Dict[str, Any],
    review: Dict[str, Any],
) -> Dict[str, Any]:
    updated = copy.deepcopy(glossary)
    by_term = {
        str(entry.get("term")): entry
        for entry in updated.get("terms", [])
        if isinstance(entry, dict) and entry.get("term")
    }
    for issue in review.get("issues", []):
        if issue.get("status") != "confirmed":
            continue
        for entry in issue.get("glossary_entries", []) or []:
            if not isinstance(entry, dict):
                continue
            term = str(entry.get("term", "")).strip()
            if not term:
                continue
            target = by_term.get(term)
            if target is None:
                target = {
                    "term": term,
                    "aliases": [],
                    "category": str(entry.get("category", "industry")),
                    "source": str(entry.get("source", "")),
                    "confirmed_at": utc_now(),
                }
                updated["terms"].append(target)
                by_term[term] = target
            aliases = target.setdefault("aliases", [])
            for alias in entry.get("aliases", []) if isinstance(entry.get("aliases", []), list) else []:
                alias = str(alias).strip()
                if alias and alias != term and alias not in aliases:
                    aliases.append(alias)
            target["confirmed_at"] = utc_now()
    return updated


def prepare_review(
    transcript_path: str,
    out_dir: str,
    glossary_path: Optional[str] = None,
    apply: bool = False,
    update_glossary: bool = False,
    normalization_rules_path: Optional[str] = None,
    confirm_open_as_is: bool = False,
) -> Path:
    transcript_file = Path(transcript_path).expanduser().resolve()
    transcript = read_json(transcript_file)
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    glossary_file = (
        Path(glossary_path).expanduser().resolve()
        if glossary_path
        else output / "glossary.json"
    )
    glossary = load_glossary(glossary_file)
    normalization_rules = load_rules(normalization_rules_path)
    previous_review = None
    previous_path = output / "review.json"
    if previous_path.exists():
        previous_review = read_json(previous_path)

    transcript_hash = sha256_json(transcript.get("segments", []))
    issues: List[Dict[str, Any]] = []
    for segment in transcript.get("segments", []):
        issue = _review_segment_issue(
            transcript_hash,
            segment,
            glossary,
            normalization_rules,
        )
        if issue:
            issues.append(issue)
    for gap in transcript.get("coverage", {}).get("gaps", []):
        issues.append(_coverage_issue(transcript_hash, gap))

    review = {
        "schema_version": SCHEMA_VERSION,
        "transcript_path": str(transcript_file),
        "transcript_sha256": transcript_hash,
        "generated_at": utc_now(),
        "status": "open" if issues else "ready",
        "issues": issues,
    }
    _merge_existing_confirmations(review, previous_review)
    if confirm_open_as_is:
        for issue in review["issues"]:
            if issue.get("status") == "confirmed":
                continue
            if issue.get("kind") == "coverage_gap":
                if not str(issue.get("note", "")).strip():
                    raise ValueError(
                        "覆盖缺口 {} 缺少回听说明，不能用批量确认".format(issue.get("id"))
                    )
            else:
                issue["replacement_text"] = issue.get("quote", "")
            issue["status"] = "confirmed"
            issue["note"] = "用户已明确确认其余复核项按原文保留。"
    review["status"] = (
        "ready"
        if all(issue.get("status") == "confirmed" for issue in review["issues"])
        else "open"
    )

    if apply:
        changed, transcript = _apply_confirmed_replacements(transcript, review)
        write_json(transcript_file, transcript)
        print("[review] applied {} confirmed segment replacements".format(changed))
        if update_glossary:
            glossary = _update_glossary_from_review(glossary, review)
            write_json(glossary_file, glossary)
        return prepare_review(
            transcript_path=str(transcript_file),
            out_dir=str(output),
            glossary_path=str(glossary_file),
            apply=False,
            update_glossary=False,
            normalization_rules_path=normalization_rules_path,
            confirm_open_as_is=False,
        )

    write_json(previous_path, review)
    (output / "review.md").write_text(_issue_markdown(review["issues"]), encoding="utf-8")
    (output / "review-proposal.md").write_text(
        _proposal_markdown(review["issues"]),
        encoding="utf-8",
    )
    if not glossary_file.exists():
        write_json(glossary_file, glossary)
    return previous_path
