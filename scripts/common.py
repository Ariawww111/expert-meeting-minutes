from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = "1.0"
MAX_AUDIO_SECONDS = 90 * 60
SUMMARY_MIN_CHARS = 1000
SUMMARY_MAX_CHARS = 1200
DEFAULT_TITLE = "专家会议纪要"

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".mp4"}
OMISSION_REASONS = {
    "greeting",
    "filler",
    "duplicate",
    "non_substantive",
}

ARABIC_NUMBER_RE = re.compile(
    r"(?<![\d.])"
    r"(?:\d+(?:,\d{3})*(?:\.\d+)?"
    r"(?:\s*(?:至|到|-|–)\s*\d+(?:,\d{3})*(?:\.\d+)?)?)"
    r"(?:\s*(?:%|％|个百分点|多亿元|多万元|亿元|万元|元|万吨|吨|万片|亿片|万粒|亿粒|"
    r"mg|μg|ug|g|ml|mL|毫克|微克|克|毫升|片|粒|例|岁|天|小时|个月|"
    r"万|亿|GW|GWh|MW|MWh|kWh|台|辆|家|人|年|月|日|季度|Q[1-4]))?"
)
CHINESE_NUMBER_RE = re.compile(
    r"(?:百分之[零一二三四五六七八九十百千万亿点两\d]+"
    r"|[零一二三四五六七八九十百千万亿两][零一二三四五六七八九十百千万亿两点]*(?:"
    r"个百分点|多亿元|多万元|亿元|万元|万吨|万片|亿片|万粒|亿粒|毫克|微克|毫升|"
    r"年半|"
    r"成|年|月|日|吨|元|万|亿|片|粒|例|岁|天|小时|个月))"
)
SELF_CORRECTION_RE = re.compile(
    r"(?:不是.{0,30}(?:而是|是)|我(?:刚才|前面)说错|更正一下|准确地说|口误)"
)
SUSPICIOUS_TERM_RE = re.compile(
    r"(?<![A-Za-z])(?:[A-Z]{2,8}(?:\+\+)?|[\u3400-\u9fff]{2,12}(?:芯|硅|锂|钠|氢|光刻|封装|模组|电池|电极|良率))(?![A-Za-z])"
)
UNRESOLVED_MARKER_RE = re.compile(r"\[(?:待核|待确认|听不清|转写待核|\?)\]")
ANALYTICAL_WARNING_RE = re.compile(
    r"投资建议|建议关注|值得关注|风险提示|我们认为|综合判断|由此可见|利好|利空|有望|预计将"
)
CHINESE_DATA_NUMERAL_RE = re.compile(
    r"百分之[零一二三四五六七八九十百千万亿点两\d]+"
    r"|[零一二三四五六七八九两][零一二三四五六七八九十百千万亿点两]*"
    r"(?:%|％|个百分点|亿元|万元|多万元|多亿元|元|万吨|万片|亿片|万粒|亿粒|"
    r"毫克|微克|毫升|个月|小时|季度|成|片|粒|例|岁|天|年|月|日|吨|万|亿|人|家|个)"
)

CN_DIGIT_VALUES = {
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
CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
NUMERIC_UNITS = [
    "个百分点",
    "多亿元",
    "多万元",
    "亿元",
    "万元",
    "万吨",
    "万片",
    "亿片",
    "万粒",
    "亿粒",
    "毫克",
    "微克",
    "毫升",
    "个月",
    "年半",
    "小时",
    "季度",
    "成",
    "块钱",
    "万吨",
    "片",
    "粒",
    "例",
    "岁",
    "天",
    "吨",
    "块",
    "元",
    "万",
    "亿",
    "人",
    "家",
    "个",
    "年",
    "月",
    "日",
    "%",
    "％",
]
UNIT_CANON = {
    "％": "%",
    "亿元": "亿",
    "万元": "万",
    "块钱": "元",
    "块": "元",
    "个": "个",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object in {}".format(path))
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def get_data_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("EXPERT_MEETING_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    d_drive = Path("D:/CodexData/expert-meeting-minutes")
    if Path("D:/").exists():
        return d_drive
    return (Path.home() / ".codex-data" / "expert-meeting-minutes").resolve()


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_copy_text(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(source.read_bytes())
    temporary.replace(destination)


def format_timecode(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60
    if hours:
        return "{:02d}:{:02d}:{:06.3f}".format(hours, minutes, remaining)
    return "{:02d}:{:06.3f}".format(minutes, remaining)


def chinese_number_to_int(value: str) -> Optional[int]:
    if not value:
        return None
    if all(char in CN_DIGIT_VALUES for char in value) and len(value) > 1:
        return int("".join(str(CN_DIGIT_VALUES[char]) for char in value))
    total = 0
    section = 0
    number = 0
    for char in value:
        if char in CN_DIGIT_VALUES:
            number = CN_DIGIT_VALUES[char]
            continue
        if char in CN_SMALL_UNITS:
            if number == 0:
                number = 1
            section += number * CN_SMALL_UNITS[char]
            number = 0
            continue
        if char == "万":
            section = (section + number) * 10000
            total += section
            section = 0
            number = 0
            continue
        if char == "亿":
            section = (section + number) * 100000000
            total += section
            section = 0
            number = 0
            continue
        return None
    return total + section + number


def _format_number(number: float) -> str:
    if abs(number - int(number)) < 1e-9:
        return str(int(number))
    return ("{:.8f}".format(number)).rstrip("0").rstrip(".")


def _parse_chinese_number(value: str) -> Optional[str]:
    special_ranges = {
        "七八": "7-8",
        "五六": "5-6",
        "六七": "6-7",
        "三四": "3-4",
        "一两": "1-2",
        "二三十": "20-30",
        "三四十": "30-40",
        "五六十": "50-60",
        "七八十": "70-80",
        "一百三四十": "130-140",
        "三四百": "300-400",
        "五六百": "500-600",
    }
    if value in special_ranges:
        return special_ranges[value]
    if "点" in value:
        integer_part, fractional = value.split("点", 1)
        integer = chinese_number_to_int(integer_part) if integer_part else 0
        fractional_digits = "".join(str(CN_DIGIT_VALUES[char]) for char in fractional if char in CN_DIGIT_VALUES)
        if integer is None or not fractional_digits:
            return None
        return _format_number(float("{}.{}".format(integer, fractional_digits)))
    number = chinese_number_to_int(value)
    return _format_number(number) if number is not None else None


def normalize_numeric_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace(",", "").replace(" ", "").lower()
    percent_match = re.fullmatch(r"百分之(.+)", normalized)
    if percent_match and not normalized.endswith("%"):
        number = _parse_chinese_number(percent_match.group(1))
        if number is not None:
            return "{}%".format(number)
    if re.fullmatch(r"q[1-4]", normalized):
        return normalized
    number_part = normalized
    unit = ""
    for candidate in NUMERIC_UNITS:
        if normalized.endswith(candidate) and len(normalized) > len(candidate):
            number_part = normalized[: -len(candidate)]
            unit = candidate
            break
    number = _parse_chinese_number(number_part)
    if number is None:
        number = number_part
    unit = UNIT_CANON.get(unit, unit)
    if unit == "年半" and re.fullmatch(r"\d+(?:\.\d+)?", str(number)):
        return "{}年".format(_format_number(float(number) + 0.5))
    if unit == "成" and re.fullmatch(r"\d+(?:\.\d+)?", str(number)):
        return "{}%".format(_format_number(float(number) * 10))
    return "{}{}".format(number, unit)


def extract_numeric_tokens(text: str) -> List[str]:
    matches = []
    for regex in (ARABIC_NUMBER_RE, CHINESE_NUMBER_RE):
        for match in regex.finditer(text):
            matches.append(match.group(0).strip())
    return matches


def summary_character_count(paragraphs: Iterable[str]) -> int:
    count = 0
    for paragraph in paragraphs:
        for char in paragraph:
            category = unicodedata.category(char)
            if (
                "\u3400" <= char <= "\u9fff"
                or char.isascii()
                and char.isalnum()
            ):
                count += 1
            elif category.startswith("L") or category.startswith("N"):
                count += 1
    return count


def text_without_titles(minutes: Dict[str, Any]) -> str:
    pieces = list(minutes.get("summary", []))
    for item in minutes.get("qa", []):
        if not isinstance(item, dict):
            continue
        pieces.append(str(item.get("question", "")))
        answer = item.get("answer", [])
        if isinstance(answer, list):
            pieces.extend(str(value) for value in answer)
        else:
            pieces.append(str(answer))
    return "\n".join(pieces)


def load_glossary(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "terms": [],
            "person_names": [],
        }
    glossary = read_json(path)
    glossary.setdefault("schema_version", SCHEMA_VERSION)
    glossary.setdefault("terms", [])
    glossary.setdefault("person_names", [])
    if not isinstance(glossary["terms"], list):
        raise ValueError("glossary.terms must be a list")
    if not isinstance(glossary["person_names"], list):
        raise ValueError("glossary.person_names must be a list")
    return glossary


def confirmed_hotwords(glossary: Dict[str, Any]) -> List[str]:
    words = []
    for term in glossary.get("terms", []):
        if not isinstance(term, dict):
            continue
        canonical = str(term.get("term", "")).strip()
        if canonical:
            words.append(canonical)
        aliases = term.get("aliases", [])
        if isinstance(aliases, list):
            words.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    return sorted(set(words))


def temporary_directory(data_root: Path, prefix: str) -> tempfile.TemporaryDirectory:
    ensure_directory(data_root)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=str(data_root))


def find_segment(transcript: Dict[str, Any], segment_id: str) -> Optional[Dict[str, Any]]:
    for segment in transcript.get("segments", []):
        if segment.get("id") == segment_id:
            return segment
    return None


def segment_text_map(transcript: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(segment.get("id")): segment
        for segment in transcript.get("segments", [])
        if segment.get("id")
    }


def stable_issue_id(transcript_hash: str, segment_id: str, kind: str) -> str:
    digest = hashlib.sha256(
        "{}:{}:{}".format(transcript_hash, segment_id, kind).encode("utf-8")
    ).hexdigest()[:10].upper()
    return "R{}".format(digest)
