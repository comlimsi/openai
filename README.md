# Codex Token Usage Report

A small, dependency-free Python script for summarizing local Codex token usage from
your `~/.codex` data directory.

The script reads Codex session JSONL files, totals token usage, optionally estimates
credits from built-in or custom per-1M-token rates, and can emit either a readable
terminal report or JSON for further processing.

## Important Security Note

Do not upload your entire `~/.codex` directory to GitHub.

That directory may contain private prompts, local file paths, session history,
SQLite state, and authentication material such as `auth.json`. If publishing this
tool, copy only these project files into a clean repository:

- `token_usage_report.py`
- `README.md`
- optionally a `.gitignore`

A safe `.gitignore` for a repository that contains this script is:

```gitignore
auth.json
*.sqlite
*.sqlite-shm
*.sqlite-wal
sessions/
archived_sessions/
logs/
cache/
__pycache__/
*.pyc
```

## Requirements

- Python 3.10+
- No third-party Python packages

The script uses only the Python standard library.

## Quick Start

From the directory containing `token_usage_report.py`:

```bash
python3 token_usage_report.py
```

By default, the script reads:

```text
~/.codex
```

You can point it at another Codex data directory with `--root`:

```bash
python3 token_usage_report.py --root /path/to/.codex
```

## Common Usage

Show usage from the last 7 days:

```bash
python3 token_usage_report.py --since-days 7
```

Show the top 10 highest-token query events:

```bash
python3 token_usage_report.py --top 10
```

Show more daily buckets:

```bash
python3 token_usage_report.py --daily-top 30
```

Show session-level rollups:

```bash
python3 token_usage_report.py --session-top 10
```

Emit JSON instead of text:

```bash
python3 token_usage_report.py --json
```

Show latest usage-limit metadata found in Codex logs, if available:

```bash
python3 token_usage_report.py --show-limits
```

## Credit Estimates

Token totals are read from local Codex logs. Credit estimates are calculated from
per-1M-token rates.

List the built-in pricing presets:

```bash
python3 token_usage_report.py --list-models
```

Use a built-in model preset:

```bash
python3 token_usage_report.py --model gpt-5.5
```

The script also tries to auto-detect the model from Codex logs. If it cannot
detect a supported model, pass `--model` or provide custom rates.

Use custom rates:

```bash
python3 token_usage_report.py \
  --input-credits-per-1m 5 \
  --cached-input-credits-per-1m 0.5 \
  --output-credits-per-1m 30
```

The built-in pricing table is intentionally editable. Update
`MODEL_PRICING_PRESETS` in `token_usage_report.py` if your account uses different
rates or newer model names.

## Data Sources

The script looks under the selected root directory for:

- `sessions/**/*.jsonl`
- `archived_sessions/**/*.jsonl`
- `state_5.sqlite`

Session JSONL files provide per-event token usage from `token_count` events.
`state_5.sqlite` is used as a fallback source for saved thread aggregate token
totals and recent thread metadata.

## Output

The text report includes:

- number of session files read
- detected or selected model
- event count
- total, input, cached input, output, and reasoning output tokens
- estimated credits, when rates are available
- saved thread token totals from `state_5.sqlite`
- optional latest usage-limit metadata
- optional top query events
- daily token breakdown
- optional session breakdown

The JSON output includes the same information in machine-readable form.

## Limitations

- This is a local log parser, not an official billing report.
- Credit estimates depend on the pricing rates supplied to the script.
- Local Codex log formats may change over time.
- Query previews come from local session logs and may contain private text.
- Missing or unpublished rates can make estimated credits display as `n/a`.

## Example

```bash
python3 token_usage_report.py --since-days 14 --model gpt-5.5 --top 5 --session-top 5
```

This reads the last 14 days of Codex session data, estimates credits using the
`gpt-5.5` preset, shows the top 5 query events, and prints the 5 largest session
rollups.
