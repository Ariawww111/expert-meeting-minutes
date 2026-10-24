# Expert Meeting Minutes

This repository provides a local Agent Skill for Chinese expert-meeting recordings.

When a user provides an audio recording:

1. Read `SKILL.md` completely before starting.
2. Ask for the company or industry if it was not provided.
3. Use the shared local pipeline through `scripts\run_mm.cmd` or `scripts\run_mm.ps1`.
4. Never replace the local transcript with a cloud transcription or an invented summary.
5. Stop at the human-review gate until the user confirms terminology, numbers, self-corrections, and coverage gaps.
6. Use the provided validator and DOCX renderer; do not hand-write `validation.json` or bypass a failed gate.

The core workflow, writing rules, and privacy constraints are defined only in `SKILL.md` and its linked references.
