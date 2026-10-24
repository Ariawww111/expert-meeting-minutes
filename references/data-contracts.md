# 数据契约

所有 JSON 使用 UTF-8、对象根节点和 `schema_version: "1.0"`。

## transcript.json

```json
{
  "schema_version": "1.0",
  "audio": {
    "source_path": "C:/audio/meeting.m4a",
    "sha256": "...",
    "duration_seconds": 3600.0,
    "source_channels": 2,
    "sample_rate": 44100,
    "codec": "aac",
    "selected_channel": "mix",
    "normalized_path": "D:/CodexData/expert-meeting-minutes/cache/..../normalized.wav"
  },
  "engine": {
    "name": "FunASR",
    "model": "paraformer-zh",
    "vad_model": "fsmn-vad",
    "punc_model": "ct-punc",
    "speaker_model": "cam++",
    "device": "cpu",
    "config_sha256": "...",
    "hotwords_count": 0
  },
  "coverage": {
    "status": "pass",
    "speech_seconds": 3500.0,
    "transcribed_seconds": 3500.0,
    "coverage_ratio": 1.0,
    "gaps": []
  },
  "segments": [
    {
      "id": "S000001",
      "start": 0.0,
      "end": 8.2,
      "speaker": "C01-SPK1",
      "text": "……"
    }
  ],
  "created_at": "2026-10-23T12:00:00+00:00"
}
```

说话人编号仅在当前录音和分片内匿名有效，不是实名身份。

## review.json

```json
{
  "schema_version": "1.0",
  "transcript_sha256": "...",
  "status": "ready",
  "issues": [
    {
      "id": "RABCDEF1234",
      "kind": "mixed",
      "kinds": ["number", "term"],
      "segment_ids": ["S000042"],
      "time_range": [612.4, 631.9],
      "quote": "原始转写句",
      "candidates": ["候选术语", "20%"],
      "reason": "数字或单位需要人工确认；检测到疑似术语转写偏差",
      "source_checks": [
        {
          "query": "公司 产品 官方名称",
          "url": "https://example.com/source",
          "evidence": "页面支持候选写法和单位",
          "retrieved_at": "2026-10-23T12:00:00+00:00"
        }
      ],
      "status": "confirmed",
      "replacement_text": "人工确认后的完整句子",
      "note": "用户已回听确认",
      "glossary_entries": []
    }
  ]
}
```

`status` 只允许 `open` 或 `confirmed`。覆盖缺口必须填写 `note`。普通原始段落不要主动写 `glossary_entries`；只有用户明确确认某个术语值得沉淀时才填写：

```json
{"term": "标准术语", "aliases": ["转写别名"], "category": "industry", "source": "用户确认"}
```

## minutes.json

```json
{
  "schema_version": "1.0",
  "title": "专家会议纪要",
  "summary": ["第一段", "第二段", "第三段"],
  "summary_segment_ids": ["S000001", "S000002"],
  "qa": [
    {
      "id": "Q1",
      "question": "问题",
      "answer": ["回答第一段", "回答第二段"],
      "evidence_segment_ids": ["S000010", "S000011"]
    }
  ],
  "omissions": [
    {
      "segment_id": "S000003",
      "reason": "greeting"
    }
  ]
}
```

覆盖规则：

- 每个 `segments[]` 必须出现在 `summary_segment_ids`、任一 `qa[].evidence_segment_ids` 或 `omissions[].segment_id` 中。
- `omissions.reason` 只允许 `greeting`、`filler`、`duplicate`、`non_substantive`。
- 问答编号必须从 `Q1` 连续递增。
- 数字覆盖按规范化后的数字和单位检查。原文出现的数字必须在正式正文中出现；若多个片段重复同一数字，只需正文至少保留一次。
- 术语表中的 `person_names` 不得出现在正式正文。
- 专家判断必须进入 `summary` 或 `qa` 的证据范围，不得以 `non_substantive` 省略。需要保留的判断包括策略取舍、开发优先级、适应症/靶点/患者人群选择、临床设计、成功概率、成本与竞争判断，以及“应做/不应做”的建议。
- 判断型内容可以没有外部来源，但不能改写成客观事实或公司确认。若判断与公开资料冲突，保留原判断及中性归因，并在复核审计中记录冲突证据。
