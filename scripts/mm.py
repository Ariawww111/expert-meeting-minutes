from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audio_pipeline import check_environment, refresh_coverage, transcribe_audio
from docx_renderer import render_docx
from fidelity import validate_minutes
from normalization import apply_proposal_markdown, normalize_transcript
from review_pipeline import prepare_review


def _json_print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mm.py",
        description="本地券商专家会议纪要与 Q&A 工作流",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup-check", help="检查本地依赖、磁盘和模型环境")
    setup.add_argument("--data-root", help="模型和缓存目录，默认 D:/CodexData/expert-meeting-minutes")
    setup.add_argument("--json", action="store_true", help="输出 JSON")

    transcribe = subparsers.add_parser("transcribe", help="本地录音转写")
    transcribe.add_argument("audio", help="mp3/m4a/wav/mp4 文件")
    transcribe.add_argument("--out", required=True, help="输出目录")
    transcribe.add_argument(
        "--channel",
        help="多声道时必填：mix 或 0/1/2...；单声道可省略",
    )
    transcribe.add_argument("--glossary", help="已确认术语表 JSON")
    transcribe.add_argument("--data-root", help="模型和缓存目录")
    transcribe.add_argument("--force", action="store_true", help="忽略已完成缓存")

    coverage = subparsers.add_parser(
        "refresh-coverage",
        help="复用已有转写，仅重跑 VAD 并刷新覆盖审计",
    )
    coverage.add_argument("transcript", help="transcript.json")
    coverage.add_argument("--data-root", help="模型和缓存目录")

    review = subparsers.add_parser("prepare-review", help="生成或应用人工复核清单")
    review.add_argument("transcript", help="transcript.json")
    review.add_argument("--out", required=True, help="任务输出目录")
    review.add_argument("--glossary", help="术语表 JSON")
    review.add_argument("--apply", action="store_true", help="应用已确认的 replacement_text")
    review.add_argument(
        "--update-glossary",
        action="store_true",
        help="把 confirmed issue 中的 glossary_entries 写入术语表",
    )
    review.add_argument("--rules", help="术语与安全规范化规则 JSON")
    review.add_argument(
        "--confirm-open-as-is",
        action="store_true",
        help="用户明确确认其余项按原文保留后，批量设为 confirmed",
    )

    normalize = subparsers.add_parser(
        "normalize-transcript",
        help="自动修正确定的年份、日期、重复数字和标准缩写",
    )
    normalize.add_argument("transcript", help="transcript.json")
    normalize.add_argument("--out", required=True, help="任务输出目录")
    normalize.add_argument("--rules", help="规范化规则 JSON")

    proposal = subparsers.add_parser(
        "apply-proposal",
        help="应用用户在 review-proposal.md 中确认的整句修正",
    )
    proposal.add_argument("transcript", help="transcript.json")
    proposal.add_argument("--proposal-md", required=True, help="用户确认后的提案 Markdown")
    proposal.add_argument("--out", required=True, help="任务输出目录")

    validate = subparsers.add_parser("validate", help="校验纪要、覆盖和复核门禁")
    validate.add_argument("minutes", help="minutes.json")
    validate.add_argument("--transcript", required=True, help="transcript.json")
    validate.add_argument("--review", required=True, help="review.json")
    validate.add_argument("--out", required=True, help="validation.json")
    validate.add_argument("--glossary", help="术语表 JSON")

    render = subparsers.add_parser("render-docx", help="在校验通过后生成正式 DOCX")
    render.add_argument("minutes", help="minutes.json")
    render.add_argument("--validation", required=True, help="validation.json")
    render.add_argument("--transcript", required=True, help="transcript.json")
    render.add_argument("--review", required=True, help="review.json")
    render.add_argument("--out", required=True, help="输出 DOCX")
    render.add_argument("--force", action="store_true", help="覆盖已有 DOCX")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "setup-check":
            result = check_environment(args.data_root)
            if args.json:
                _json_print(result)
            else:
                print("环境检查：{}".format("通过" if result["ok"] else "未通过"))
                for name, value in result.items():
                    if isinstance(value, dict) and "ok" in value:
                        print("  {}: {}".format(name, "OK" if value["ok"] else "MISSING"))
                print("数据目录：{}".format(result["data_root"]["path"]))
            return 0 if result["ok"] else 2

        if args.command == "transcribe":
            result = transcribe_audio(
                audio_path=args.audio,
                out_dir=args.out,
                selected_channel=args.channel,
                glossary_path=args.glossary,
                data_root=args.data_root,
                force=args.force,
            )
            print(result)
            return 0

        if args.command == "prepare-review":
            result = prepare_review(
                transcript_path=args.transcript,
                out_dir=args.out,
                glossary_path=args.glossary,
                apply=args.apply,
                update_glossary=args.update_glossary,
                normalization_rules_path=args.rules,
                confirm_open_as_is=args.confirm_open_as_is,
            )
            print(result)
            return 0

        if args.command == "normalize-transcript":
            result = normalize_transcript(
                transcript_path=args.transcript,
                out_dir=args.out,
                rules_path=args.rules,
            )
            _json_print(result)
            return 0

        if args.command == "apply-proposal":
            result = apply_proposal_markdown(
                transcript_path=args.transcript,
                proposal_path=args.proposal_md,
                out_dir=args.out,
            )
            _json_print(result)
            return 0

        if args.command == "refresh-coverage":
            result = refresh_coverage(
                transcript_path=args.transcript,
                data_root=args.data_root,
            )
            _json_print(result)
            return 0 if result.get("status") == "pass" else 1

        if args.command == "validate":
            result = validate_minutes(
                minutes_path=args.minutes,
                transcript_path=args.transcript,
                review_path=args.review,
                out_path=args.out,
                glossary_path=args.glossary,
            )
            _json_print(result)
            return 0 if result["ok"] else 1

        if args.command == "render-docx":
            result = render_docx(
                minutes_path=args.minutes,
                validation_path=args.validation,
                transcript_path=args.transcript,
                review_path=args.review,
                out_path=args.out,
                force=args.force,
            )
            print(result)
            return 0
    except Exception as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1
    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
