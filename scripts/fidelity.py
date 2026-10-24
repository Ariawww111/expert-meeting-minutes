from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from common import (
    ANALYTICAL_WARNING_RE,
    CHINESE_DATA_NUMERAL_RE,
    OMISSION_REASONS,
    SCHEMA_VERSION,
    SUMMARY_MAX_CHARS,
    SUMMARY_MIN_CHARS,
    UNRESOLVED_MARKER_RE,
    extract_numeric_tokens,
    load_glossary,
    normalize_numeric_token,
    read_json,
    sha256_json,
    summary_character_count,
    text_without_titles,
    utc_now,
    write_json,
)


def _add_error(errors: List[Dict[str, str]], code: str, message: str) -> None:
    errors.append({"code": code, "message": message})


def _add_warning(warnings: List[Dict[str, str]], code: str, message: str) -> None:
    warnings.append({"code": code, "message": message})


def _validate_structure(
    minutes: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> None:
    summary = minutes.get("summary")
    qa = minutes.get("qa")
    omissions = minutes.get("omissions", [])
    if not isinstance(summary, list) or not (3 <= len(summary) <= 5):
        _add_error(errors, "summary_paragraphs", "会议内容汇总必须为 3 至 5 个自然段")
    elif any(not isinstance(value, str) or not value.strip() for value in summary):
        _add_error(errors, "summary_empty", "会议内容汇总存在空段落")
    elif any(re.match(r"^\s*(?:[-*•]|\d+[.)、])\s*", value) for value in summary):
        _add_error(errors, "summary_bullets", "会议内容汇总不得使用列表或分点")

    if not isinstance(qa, list) or not qa:
        _add_error(errors, "qa_missing", "Q&A 至少需要一条问答")
    else:
        for index, item in enumerate(qa, start=1):
            if not isinstance(item, dict):
                _add_error(errors, "qa_item", "Q&A 第 {} 项不是对象".format(index))
                continue
            expected = "Q{}".format(index)
            if item.get("id") != expected:
                _add_error(
                    errors,
                    "qa_numbering",
                    "Q&A 顺序错误：期望 {}，实际 {}".format(expected, item.get("id")),
                )
            if not str(item.get("question", "")).strip():
                _add_error(errors, "question_empty", "{} 缺少问题".format(expected))
            answer = item.get("answer", [])
            if not isinstance(answer, list) or not answer or any(
                not isinstance(value, str) or not value.strip() for value in answer
            ):
                _add_error(errors, "answer_empty", "{} 缺少有效回答".format(expected))
            elif any(re.search(r"(^|\n)\s*A\s*[：:]", value) for value in answer):
                _add_error(errors, "answer_label", "{} 回答中不得出现 A：标签".format(expected))

    if not isinstance(omissions, list):
        _add_error(errors, "omissions_type", "omissions 必须为列表")
        return
    for item in omissions:
        if not isinstance(item, dict):
            _add_error(errors, "omission_item", "omissions 中存在非对象项")
            continue
        if item.get("reason") not in OMISSION_REASONS:
            _add_error(
                errors,
                "omission_reason",
                "省略片段 {} 的原因无效".format(item.get("segment_id")),
            )


def _evidence_ids(minutes: Dict[str, Any]) -> Set[str]:
    refs: Set[str] = set()
    summary_refs = minutes.get("summary_segment_ids", []) or []
    if not isinstance(summary_refs, list):
        return refs
    for segment_id in summary_refs:
        refs.add(str(segment_id))
    qa_items = minutes.get("qa", []) or []
    if not isinstance(qa_items, list):
        return refs
    for item in qa_items:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence_segment_ids", []) or []
        if not isinstance(evidence, list):
            continue
        for segment_id in evidence:
            refs.add(str(segment_id))
    return refs


def _validate_evidence(
    minutes: Dict[str, Any],
    transcript: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> None:
    segment_ids = {str(segment.get("id")) for segment in transcript.get("segments", [])}
    referenced = _evidence_ids(minutes)
    unknown = sorted(referenced - segment_ids)
    if unknown:
        _add_error(
            errors,
            "unknown_evidence",
            "引用了不存在的转写片段：{}".format(", ".join(unknown)),
        )

    omissions = minutes.get("omissions", []) or []
    omitted = {
        str(item.get("segment_id"))
        for item in omissions
        if isinstance(item, dict) and item.get("segment_id")
    }
    unknown_omissions = sorted(omitted - segment_ids)
    if unknown_omissions:
        _add_error(
            errors,
            "unknown_omission",
            "省略了不存在的转写片段：{}".format(", ".join(unknown_omissions)),
        )
    missing = sorted(segment_ids - referenced - omitted)
    if missing:
        _add_error(
            errors,
            "segment_unaccounted",
            "以下转写片段未进入纪要，也未说明省略原因：{}".format(", ".join(missing[:30])),
        )


def _validate_numbers(
    minutes: Dict[str, Any],
    transcript: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> None:
    source_tokens: Dict[str, List[str]] = {}
    for segment in transcript.get("segments", []):
        for token in extract_numeric_tokens(str(segment.get("text", ""))):
            source_tokens.setdefault(normalize_numeric_token(token), []).append(
                str(segment.get("id"))
            )
    final_tokens = {
        normalize_numeric_token(token)
        for token in extract_numeric_tokens(text_without_titles(minutes))
    }
    missing = sorted(set(source_tokens) - final_tokens)
    if missing:
        details = [
            "{} ({})".format(
                token,
                ", ".join(sorted(set(source_tokens[token]))[:5]),
            )
            for token in missing[:30]
        ]
        _add_error(
            errors,
            "numeric_coverage",
            "以下数字或单位未进入正式纪要：{}".format("; ".join(details)),
        )


def _validate_arabic_numeral_style(
    minutes: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> None:
    body = text_without_titles(minutes)
    matches = [match.group(0) for match in CHINESE_DATA_NUMERAL_RE.finditer(body)]
    if matches:
        unique = list(dict.fromkeys(matches))
        _add_error(
            errors,
            "arabic_numeral_style",
            "正式纪要中的数据应使用阿拉伯数字：{}".format("、".join(unique[:30])),
        )


def _validate_qa_voice(
    minutes: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> None:
    prefix_re = re.compile(r"^\s*(?:与会专家|专家)(?:表示|认为|判断|指出)")
    for item in minutes.get("qa", []):
        if not isinstance(item, dict):
            continue
        answer = item.get("answer", [])
        if isinstance(answer, str):
            answer = [answer]
        if not isinstance(answer, list):
            continue
        for paragraph in answer:
            if prefix_re.match(str(paragraph)):
                _add_error(
                    errors,
                    "qa_attribution_prefix",
                    "{} 的回答应直接陈述内容，不使用“专家表示/专家认为”等前置语".format(
                        item.get("id")
                    ),
                )
                break


def _validate_person_names(
    minutes: Dict[str, Any],
    glossary: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> None:
    body = text_without_titles(minutes)
    found = []
    for name in glossary.get("person_names", []):
        name = str(name).strip()
        if name and name in body:
            found.append(name)
    if found:
        _add_error(
            errors,
            "person_names",
            "正式纪要中不得出现人名：{}".format("、".join(found)),
        )


def _validate_review(
    review: Dict[str, Any],
    transcript: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> None:
    issues = review.get("issues", [])
    current_hash = sha256_json(transcript.get("segments", []))
    if review.get("transcript_sha256") != current_hash:
        _add_error(
            errors,
            "review_stale",
            "复核清单与当前转写不一致，请重新生成并确认复核清单",
        )
    segment_map = {
        str(segment.get("id")): segment
        for segment in transcript.get("segments", [])
        if segment.get("id")
    }
    unresolved = [
        str(issue.get("id"))
        for issue in issues
        if isinstance(issue, dict) and issue.get("status") != "confirmed"
    ]
    if unresolved:
        _add_error(
            errors,
            "review_open",
            "仍有未确认的待核项：{}".format(", ".join(unresolved[:30])),
        )
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("status") != "confirmed":
            continue
        if issue.get("kind") == "coverage_gap" and not str(issue.get("note", "")).strip():
            _add_error(
                errors,
                "coverage_note",
                "覆盖缺口 {} 缺少人工回听说明".format(issue.get("id")),
            )
            continue
        if issue.get("kind") == "coverage_gap":
            continue
        replacement = issue.get("replacement_text")
        if not isinstance(replacement, str) or not replacement.strip():
            _add_error(
                errors,
                "review_replacement",
                "已确认项 {} 缺少 replacement_text".format(issue.get("id")),
            )
            continue
        for segment_id in issue.get("segment_ids", []):
            segment = segment_map.get(str(segment_id))
            if segment and replacement.strip() != str(segment.get("text", "")).strip():
                _add_error(
                    errors,
                    "review_not_applied",
                    "已确认项 {} 的修正尚未应用，请先运行 prepare-review --apply".format(
                        issue.get("id")
                    ),
                )
                break


def validate_minutes(
    minutes_path: str,
    transcript_path: str,
    review_path: str,
    out_path: str,
    glossary_path: Optional[str] = None,
) -> Dict[str, Any]:
    minutes_file = Path(minutes_path).expanduser().resolve()
    transcript_file = Path(transcript_path).expanduser().resolve()
    review_file = Path(review_path).expanduser().resolve()
    output_file = Path(out_path).expanduser().resolve()
    minutes = read_json(minutes_file)
    transcript = read_json(transcript_file)
    review = read_json(review_file)
    glossary = load_glossary(Path(glossary_path).expanduser().resolve() if glossary_path else None)

    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    _validate_structure(minutes, errors)
    _validate_evidence(minutes, transcript, errors)
    _validate_numbers(minutes, transcript, errors)
    _validate_arabic_numeral_style(minutes, errors)
    _validate_qa_voice(minutes, errors)
    _validate_person_names(minutes, glossary, errors)
    _validate_review(review, transcript, errors)

    summary = minutes.get("summary", [])
    character_count = summary_character_count(summary if isinstance(summary, list) else [])
    if not SUMMARY_MIN_CHARS <= character_count <= SUMMARY_MAX_CHARS:
        _add_error(
            errors,
            "summary_length",
            "会议内容汇总为 {} 字，要求 {} 至 {} 字".format(
                character_count,
                SUMMARY_MIN_CHARS,
                SUMMARY_MAX_CHARS,
            ),
        )

    body = text_without_titles(minutes)
    marker = UNRESOLVED_MARKER_RE.search(body)
    if marker:
        _add_error(errors, "unresolved_marker", "正式纪要仍包含待核标记：{}".format(marker.group(0)))
    for match in ANALYTICAL_WARNING_RE.finditer(body):
        _add_warning(
            warnings,
            "analysis_language",
            "检测到可能带有分析或评价色彩的措辞：{}。若属于专家原意，应使用中性归因并保留来源片段。".format(
                match.group(0)
            ),
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "ok": not errors,
        "summary_character_count": character_count,
        "errors": errors,
        "warnings": warnings,
        "inputs": {
            "minutes": {
                "path": str(minutes_file),
                "sha256": sha256_json(minutes),
            },
            "transcript": {
                "path": str(transcript_file),
                "sha256": sha256_json(transcript),
            },
            "review": {
                "path": str(review_file),
                "sha256": sha256_json(review),
            },
        },
    }
    write_json(output_file, result)
    return result
