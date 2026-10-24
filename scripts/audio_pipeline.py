from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from common import (
    MAX_AUDIO_SECONDS,
    SCHEMA_VERSION,
    SUPPORTED_AUDIO_EXTENSIONS,
    confirmed_hotwords,
    ensure_directory,
    format_timecode,
    get_data_root,
    load_glossary,
    sha256_file,
    sha256_json,
    utc_now,
    write_json,
)


MODEL_CONFIG = {
    "model": "paraformer-zh",
    "vad_model": "fsmn-vad",
    "punc_model": "ct-punc",
    "spk_model": "cam++",
    "spk_mode": "vad_segment",
    "device": "cpu",
    "chunk_seconds": 600,
    "chunk_padding_seconds": 2,
    "vad_max_segment_ms": 60000,
}

REPORTABLE_GAP_SECONDS = 1.5

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
AUDIO_STREAM_RE = re.compile(
    r"Stream #.*Audio:\s*([^,\n]+),\s*(\d+)\s*Hz,\s*([^,\n]+)",
    re.IGNORECASE,
)


class PipelineError(RuntimeError):
    pass


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def find_ffmpeg() -> Optional[str]:
    if module_available("imageio_ffmpeg"):
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


def parse_channels(value: str) -> int:
    lowered = value.strip().lower()
    if lowered == "mono":
        return 1
    if lowered == "stereo":
        return 2
    match = re.match(r"^(\d+)\s*channels?$", lowered)
    if match:
        return int(match.group(1))
    match = re.match(r"^(\d+)\.(\d+)", lowered)
    if match:
        return int(match.group(1)) + int(match.group(2))
    return 1


def chunk_count(duration_seconds: float, chunk_seconds: int) -> int:
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be positive")
    return max(1, int(math.ceil(float(duration_seconds) / float(chunk_seconds))))


def probe_audio(path: Path, ffmpeg: str) -> Dict[str, Any]:
    command = [ffmpeg, "-hide_banner", "-i", str(path)]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = result.stderr or ""
    duration_match = DURATION_RE.search(text)
    if not duration_match:
        raise PipelineError("无法读取音频时长：{}".format(path))
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    stream_match = AUDIO_STREAM_RE.search(text)
    if not stream_match:
        raise PipelineError("未找到可读取的音轨：{}".format(path))
    stream_name, sample_rate, channel_layout = stream_match.groups()
    channels = parse_channels(channel_layout.strip())
    return {
        "duration_seconds": duration,
        "sample_rate": int(sample_rate),
        "channels": channels,
        "codec": stream_name.strip(),
    }


def normalize_audio(
    source: Path,
    destination: Path,
    ffmpeg: str,
    channels: int,
    selected_channel: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
    ]
    if channels > 1 and selected_channel != "mix":
        channel_index = int(selected_channel)
        command.extend(["-af", "pan=mono|c0=c{}".format(channel_index)])
    else:
        command.extend(["-ac", "1"])
    command.extend(["-ar", "16000", "-c:a", "pcm_s16le", str(destination)])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not destination.exists():
        raise PipelineError("音频标准化失败：{}".format((result.stderr or "").strip()))


def slice_audio(
    source: Path,
    destination: Path,
    ffmpeg: str,
    start_seconds: float,
    duration_seconds: float,
) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "{:.3f}".format(start_seconds),
        "-t",
        "{:.3f}".format(duration_seconds),
        "-i",
        str(source),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not destination.exists():
        raise PipelineError("音频分片失败：{}".format((result.stderr or "").strip()))


def disk_free_gib(path: Path) -> float:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(str(probe))
    return usage.free / (1024 ** 3)


def data_root_writable(path: Path) -> bool:
    try:
        ensure_directory(path)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".write-check-",
            dir=str(path),
            delete=True,
        ):
            pass
        return True
    except OSError:
        return False


def check_environment(data_root: Optional[str] = None) -> Dict[str, Any]:
    root = get_data_root(data_root)
    writable = data_root_writable(root)
    ffmpeg = find_ffmpeg()
    model_root = root / "modelscope" / "models"
    expected_models = {
        "paraformer-zh": model_root
        / "iic"
        / "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "fsmn-vad": model_root
        / "iic"
        / "speech_fsmn_vad_zh-cn-16k-common-pytorch",
        "ct-punc": model_root
        / "iic"
        / "punc_ct-transformer_cn-en-common-vocab471067-large",
        "cam++": model_root
        / "iic"
        / "speech_campplus_sv_zh-cn_16k-common",
    }
    checks = {
        "python": {
            "ok": sys.version_info >= (3, 9),
            "version": sys.version.split()[0],
            "minimum": "3.9",
        },
        "data_root": {
            "ok": writable and (Path(root).drive != "C:" or disk_free_gib(root) >= 8),
            "path": str(root),
            "free_gib": round(disk_free_gib(root), 2),
            "writable": writable,
        },
        "ffmpeg": {"ok": bool(ffmpeg), "path": ffmpeg},
        "funasr": {"ok": module_available("funasr")},
        "torch": {"ok": module_available("torch")},
        "docx": {"ok": module_available("docx")},
        "models": {
            "ok": all(path.exists() and any(path.iterdir()) for path in expected_models.values()),
            "root": str(model_root),
            "expected": {name: path.exists() for name, path in expected_models.items()},
        },
    }
    checks["ok"] = all(item["ok"] for item in checks.values() if isinstance(item, dict))
    return checks


def _load_funasr():
    try:
        from funasr import AutoModel
    except Exception as exc:
        raise PipelineError(
            "FunASR 未安装或无法导入。请先运行 scripts/setup_env.ps1。原始错误：{}".format(exc)
        )
    return AutoModel


def _parse_vad_spans(result: Any) -> List[Tuple[float, float]]:
    spans: List[Tuple[float, float]] = []
    if not isinstance(result, list) or not result:
        return spans
    value = result[0].get("value", []) if isinstance(result[0], dict) else []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        start, end = item[0], item[1]
        if start is None or end is None or float(start) < 0 or float(end) <= float(start):
            continue
        spans.append((float(start) / 1000.0, float(end) / 1000.0))
    return spans


def _parse_sentences(result: Any, chunk_offset: float, chunk_index: int) -> List[Dict[str, Any]]:
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        return []
    sentences = result[0].get("sentence_info", [])
    parsed = []
    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        text = str(sentence.get("text") or sentence.get("sentence") or "").strip()
        text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        start_ms = sentence.get("start")
        end_ms = sentence.get("end")
        if not re.search(r"[\w\u3400-\u9fff]", text) or start_ms is None or end_ms is None:
            continue
        start = chunk_offset + float(start_ms) / 1000.0
        end = chunk_offset + float(end_ms) / 1000.0
        if end <= start:
            continue
        speaker = sentence.get("spk")
        speaker_label = "SPK?" if speaker is None else "C{:02d}-SPK{}".format(chunk_index + 1, speaker)
        parsed.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker": speaker_label,
                "text": text,
            }
        )
    return parsed


def _interval_union(intervals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted((max(0.0, a), max(0.0, b)) for a, b in intervals if b > a)
    merged: List[Tuple[float, float]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1] + 0.05:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _coverage_gaps(
    vad_spans: Sequence[Tuple[float, float]],
    segments: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    speech_intervals = _interval_union(vad_spans)
    text_intervals = _interval_union(
        [(float(segment["start"]), float(segment["end"])) for segment in segments]
    )
    speech_total = sum(end - start for start, end in speech_intervals)
    covered_total = 0.0
    raw_gaps: List[Tuple[float, float]] = []
    tolerance = 0.05
    for speech_start, speech_end in speech_intervals:
        cursor = speech_start
        for text_start, text_end in text_intervals:
            if text_end <= cursor:
                continue
            if text_start >= speech_end:
                break
            if text_start > cursor + tolerance:
                raw_gaps.append(
                    (cursor, min(text_start, speech_end))
                )
            cursor = max(cursor, min(text_end, speech_end))
            if cursor >= speech_end:
                break
        if cursor < speech_end - tolerance:
            raw_gaps.append((cursor, speech_end))
        for text_start, text_end in text_intervals:
            covered_total += max(
                0.0,
                min(speech_end, text_end) - max(speech_start, text_start),
            )
    coverage_ratio = 1.0 if speech_total <= 0 else covered_total / speech_total
    ignored = [
        (start, end)
        for start, end in raw_gaps
        if end - start <= REPORTABLE_GAP_SECONDS
    ]
    gaps = [
        {
            "start": round(start, 3),
            "end": round(end, 3),
            "reason": "speech_without_transcript",
        }
        for start, end in raw_gaps
        if end - start > REPORTABLE_GAP_SECONDS
    ]
    return {
        "status": "pass" if coverage_ratio >= 0.98 and not gaps else "gaps",
        "speech_seconds": round(speech_total, 3),
        "transcribed_seconds": round(covered_total, 3),
        "coverage_ratio": round(min(1.0, coverage_ratio), 4),
        "gaps": gaps,
        "ignored_gap_count": len(ignored),
        "ignored_gap_seconds": round(sum(end - start for start, end in ignored), 3),
    }


def _cache_paths(data_root: Path, audio_hash: str, config_hash: str) -> Dict[str, Path]:
    root = data_root / "cache" / audio_hash / config_hash
    return {
        "root": root,
        "normalized": root / "normalized.wav",
        "chunks": root / "chunks",
        "transcript": root / "transcript.json",
    }


def _write_run_manifest(
    output: Path,
    transcript: Dict[str, Any],
    config_hash: str,
    cache_root: Path,
    chunk_total: int,
) -> None:
    write_json(
        output / "run-manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": transcript.get("created_at") or utc_now(),
            "audio_sha256": transcript["audio"]["sha256"],
            "config_sha256": config_hash,
            "cache_dir": str(cache_root),
            "chunk_count": chunk_total,
            "selected_channel": transcript.get("audio", {}).get("selected_channel", "unknown"),
            "coverage_status": transcript["coverage"]["status"],
        },
    )


def _transcription_config(
    selected_channel: str,
    hotwords: Sequence[str],
) -> Dict[str, Any]:
    config = dict(MODEL_CONFIG)
    config["selected_channel"] = selected_channel
    config["hotwords"] = list(hotwords)
    return config


def transcribe_audio(
    audio_path: str,
    out_dir: str,
    selected_channel: Optional[str] = None,
    glossary_path: Optional[str] = None,
    data_root: Optional[str] = None,
    force: bool = False,
) -> Path:
    source = Path(audio_path).expanduser().resolve()
    if not source.exists():
        raise PipelineError("录音文件不存在：{}".format(source))
    if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        raise PipelineError(
            "不支持的文件格式 {}，请使用 {}".format(
                source.suffix,
                ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS)),
            )
        )
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise PipelineError("未找到 FFmpeg。请先运行 scripts/setup_env.ps1。")

    output = ensure_directory(Path(out_dir).expanduser().resolve())
    root = ensure_directory(get_data_root(data_root))
    glossary = load_glossary(Path(glossary_path).expanduser().resolve() if glossary_path else None)
    audio_hash = sha256_file(source)
    probe = probe_audio(source, ffmpeg)
    if probe["duration_seconds"] > MAX_AUDIO_SECONDS + 1:
        raise PipelineError(
            "录音超过 90 分钟限制：{}".format(format_timecode(probe["duration_seconds"]))
        )
    channels = int(probe["channels"])
    if channels > 1 and selected_channel is None:
        raise PipelineError(
            "检测到 {} 个声道。请用 --channel mix 或 --channel 0/1... 明确选择，不能静默只处理第一轨。".format(
                channels
            )
        )
    channel_choice = "0" if channels == 1 else str(selected_channel)
    if channel_choice != "mix":
        channel_index = int(channel_choice)
        if channel_index < 0 or channel_index >= channels:
            raise PipelineError("声道编号 {} 超出范围 0-{}".format(channel_index, channels - 1))
    if disk_free_gib(root) < 8:
        raise PipelineError("D 盘可用空间不足 8GB，无法安全运行本地转写。")

    config = _transcription_config(channel_choice, confirmed_hotwords(glossary))
    config_hash = sha256_json(config)
    paths = _cache_paths(root, audio_hash, config_hash)
    ensure_directory(paths["root"])
    duration = float(probe["duration_seconds"])
    number_of_chunks = chunk_count(duration, int(MODEL_CONFIG["chunk_seconds"]))

    if paths["transcript"].exists() and not force:
        result = json.loads(paths["transcript"].read_text(encoding="utf-8"))
        write_json(output / "transcript.json", result)
        _write_run_manifest(output, result, config_hash, paths["root"], number_of_chunks)
        return output / "transcript.json"

    normalized = paths["normalized"]
    if force or not normalized.exists():
        normalize_audio(source, normalized, ffmpeg, channels, channel_choice)

    os.environ.setdefault("MODELSCOPE_CACHE", str(root / "modelscope"))
    os.environ.setdefault("HF_HOME", str(root / "huggingface"))

    AutoModel = _load_funasr()
    ncpu = max(1, min(8, os.cpu_count() or 1))
    hotword = " ".join("{} 10".format(word) for word in config["hotwords"])
    try:
        vad_model = AutoModel(
            model=MODEL_CONFIG["vad_model"],
            device="cpu",
            ncpu=ncpu,
            disable_update=True,
            trust_remote_code=False,
        )
        vad_result = vad_model.generate(input=str(normalized))
        vad_spans = _parse_vad_spans(vad_result)
        if not vad_spans:
            vad_spans = [(0.0, float(probe["duration_seconds"]))]

        asr_model = AutoModel(
            model=MODEL_CONFIG["model"],
            vad_model=MODEL_CONFIG["vad_model"],
            punc_model=MODEL_CONFIG["punc_model"],
            spk_model=MODEL_CONFIG["spk_model"],
            spk_mode=MODEL_CONFIG["spk_mode"],
            vad_kwargs={"max_single_segment_time": MODEL_CONFIG["vad_max_segment_ms"]},
            device="cpu",
            ncpu=ncpu,
            disable_update=True,
            trust_remote_code=False,
        )
    except Exception as exc:
        raise PipelineError(
            "FunASR 模型加载失败。请检查模型下载与 D 盘空间。原始错误：{}".format(exc)
        )

    chunk_seconds = int(MODEL_CONFIG["chunk_seconds"])
    padding = float(MODEL_CONFIG["chunk_padding_seconds"])
    ensure_directory(paths["chunks"])
    merged_segments: List[Dict[str, Any]] = []

    for chunk_index in range(number_of_chunks):
        core_start = chunk_index * chunk_seconds
        core_end = min(duration, core_start + chunk_seconds)
        clip_start = max(0.0, core_start - padding)
        clip_end = min(duration, core_end + padding)
        chunk_wav = paths["chunks"] / "chunk_{:03d}.wav".format(chunk_index)
        chunk_json = paths["chunks"] / "chunk_{:03d}.json".format(chunk_index)
        print(
            "[transcribe] chunk {}/{} {} - {}".format(
                chunk_index + 1,
                number_of_chunks,
                format_timecode(core_start),
                format_timecode(core_end),
            ),
            file=sys.stderr,
        )
        if force or not chunk_wav.exists():
            slice_audio(
                normalized,
                chunk_wav,
                ffmpeg,
                clip_start,
                clip_end - clip_start,
            )
        if chunk_json.exists() and not force:
            raw_result = json.loads(chunk_json.read_text(encoding="utf-8"))
        else:
            generate_args: Dict[str, Any] = {
                "input": str(chunk_wav),
                "sentence_timestamp": True,
                "batch_size_s": 300,
                "batch_size_threshold_s": 60,
            }
            if hotword:
                generate_args["hotword"] = hotword
            try:
                raw_result = asr_model.generate(**generate_args)
            except Exception as exc:
                raise PipelineError("第 {} 个音频分片转写失败：{}".format(chunk_index + 1, exc))
            write_json(chunk_json, raw_result)

        parsed = _parse_sentences(raw_result, clip_start, chunk_index)
        for segment in parsed:
            midpoint = (segment["start"] + segment["end"]) / 2.0
            if core_start <= midpoint < core_end or (
                chunk_index == number_of_chunks - 1 and midpoint >= core_start
            ):
                merged_segments.append(segment)

    merged_segments.sort(key=lambda item: (item["start"], item["end"]))
    for index, segment in enumerate(merged_segments, start=1):
        segment["id"] = "S{:06d}".format(index)
    ordered_segments = [
        {
            "id": segment["id"],
            "start": segment["start"],
            "end": segment["end"],
            "speaker": segment["speaker"],
            "text": segment["text"],
        }
        for segment in merged_segments
    ]
    coverage = _coverage_gaps(vad_spans, ordered_segments)
    transcript = {
        "schema_version": SCHEMA_VERSION,
        "audio": {
            "source_path": str(source),
            "sha256": audio_hash,
            "duration_seconds": round(duration, 3),
            "source_channels": channels,
            "sample_rate": probe["sample_rate"],
            "codec": probe["codec"],
            "selected_channel": channel_choice,
            "normalized_path": str(normalized),
        },
        "engine": {
            "name": "FunASR",
            "model": MODEL_CONFIG["model"],
            "vad_model": MODEL_CONFIG["vad_model"],
            "punc_model": MODEL_CONFIG["punc_model"],
            "speaker_model": MODEL_CONFIG["spk_model"],
            "spk_mode": MODEL_CONFIG["spk_mode"],
            "device": "cpu",
            "config_sha256": config_hash,
            "hotwords_count": len(config["hotwords"]),
        },
        "coverage": coverage,
        "segments": ordered_segments,
        "created_at": utc_now(),
    }
    write_json(paths["transcript"], transcript)
    write_json(output / "transcript.json", transcript)
    _write_run_manifest(
        output,
        transcript,
        config_hash,
        paths["root"],
        number_of_chunks,
    )
    return output / "transcript.json"


def refresh_coverage(
    transcript_path: str,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    transcript_file = Path(transcript_path).expanduser().resolve()
    transcript = json.loads(transcript_file.read_text(encoding="utf-8"))
    normalized = Path(transcript["audio"]["normalized_path"])
    if not normalized.exists():
        raise PipelineError("标准化音频缓存不存在，无法只刷新覆盖：{}".format(normalized))
    root = ensure_directory(get_data_root(data_root))
    os.environ.setdefault("MODELSCOPE_CACHE", str(root / "modelscope"))
    os.environ.setdefault("HF_HOME", str(root / "huggingface"))
    AutoModel = _load_funasr()
    ncpu = max(1, min(8, os.cpu_count() or 1))
    try:
        vad_model = AutoModel(
            model=MODEL_CONFIG["vad_model"],
            device="cpu",
            ncpu=ncpu,
            disable_update=True,
            trust_remote_code=False,
        )
        vad_result = vad_model.generate(input=str(normalized))
    except Exception as exc:
        raise PipelineError("覆盖刷新失败：{}".format(exc))
    coverage = _coverage_gaps(_parse_vad_spans(vad_result), transcript.get("segments", []))
    transcript["coverage"] = coverage
    transcript["updated_at"] = utc_now()
    write_json(transcript_file, transcript)
    return coverage
