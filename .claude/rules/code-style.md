# Code style guide

House style, chosen 2026-07-18: **PEP 8 base with deliberate relaxations, enforced by
Ruff lint only — no auto-formatter.** Black/strict PEP 8 was rejected to avoid a large
one-time reformat and to keep the aligned-column readability below. Prettier was
rejected for the frontend because it would explode the compact CSS and reformat a
consistent 1,800-line file for no benefit.

## Python (`app.py`, `propagation.py`)

- PEP 8 defaults unless listed here. Max line length **110**.
- **Single quotes** for strings; double quotes only to avoid escaping.
- `snake_case` functions, `UPPER_SNAKE` module constants, `_leading_underscore` for
  module-private helpers (which is most of them — only Flask routes and `handler` are public).
- **Aligned assignments are encouraged** where consecutive lines form a visual table
  (`REFRESH_INTERVAL   = 900`). Ruff E221/E241 are disabled for this. Keep alignment
  when editing such a block; don't introduce alignment where none exists.
- Section banners use the em-dash style: `# ── Section name ──────…` padded toward
  column ~80. Group related routes/helpers under one banner.
- Docstrings: one-liner (or short paragraph) on any function whose purpose or
  contract isn't obvious from the name; no Args/Returns boilerplate. Comments explain
  *why* (model constants, AWS gotchas), not *what*.
- No mandatory type hints. Add them only where they genuinely clarify.
- Error handling is **fail-soft by design**: external I/O (DynamoDB, SES, solar
  fetches) is wrapped in `try/except` that logs via `log.warning`/`log.debug` with a
  `[tag]` prefix (`[auth]`, `[dynamo]`, `[refresh]`, `[hamqsl]`…) and returns a safe
  fallback. Broad `except Exception` is acceptable there; don't "fix" it.
- Logging: module logger `log = logging.getLogger('hf...')`, %-style lazy formatting,
  never f-strings inside log calls.
- Lambda constraints: Python 3.14 runtime, stdlib `urllib` (no `requests`), `boto3`
  comes from the runtime — never add it to `requirements.txt` or the zip.

### Lint

```powershell
.\venv\Scripts\python.exe -m ruff check app.py propagation.py
```

Config lives in `ruff.toml` (rules E, W, F, B, Q; single-quote enforcement; E221/E241
off). Lint must pass before a task is reported done. Install dev tools with
`pip install -r requirements-dev.txt` (ruff is dev-only — never packaged).

## Frontend (`templates/index.html` — single-file app)

- Everything (CSS, JS, markup) stays in this one Jinja template; no build step, no
  bundler. Libraries load from jsDelivr CDN pinned to a major version.
- **2-space indent** throughout HTML, CSS, and JS.
- CSS: compact one-line rules (`#hamburger:hover { border-color:#38bdf8; color:#38bdf8; }`),
  no space after `:` in property values is fine; group rules under `/* ── Section ── */`
  banners; colors as hex/rgba literals matching the existing slate/sky palette.
- JS: `const`/`let` (never `var`), camelCase functions, arrow functions for callbacks,
  template literals for HTML/SVG assembly, semicolons required. Data tables
  (`BAND_PLAN`, `SOLAR_TIPS`, city lists) use compact literal formatting — one logical
  record per line even if long.
- Inline `onclick="..."` handlers in markup are the established pattern; keep it.
- Small inline `style="..."` attributes are acceptable for one-off modal sizing;
  anything reused belongs in the `<style>` block.

## Terraform (`terraform/`)

- Standard HCL style: run `terraform fmt` after edits. One resource concern per file
  (`lambda.tf`, `dynamodb.tf`, `iam.tf`, …).

## Markdown / docs

- Sentence-case headings, tables for enumerable facts, PowerShell fenced blocks for
  commands (this is a Windows-first repo).
