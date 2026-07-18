---
name: project-versioning
description: "Version number scheme YYMM.### — ### resets to 001 at each new month, bumps every build"
metadata:
  type: project
---

The HF Propagation app uses a build version in `APP_VERSION` (top of `app.py`), displayed in the Help/About modal as `Version {{ app_version }}`.

**Format: `YYMM.###`** — e.g. `2607.003` = 3rd build of July 2026.

- Increment `###` on **every build** (every lambda.zip repackage counts as a build).
- **`###` resets to `001` at each new month**, and `YYMM` advances (Aug 2026 starts at `2608.001`).
- Established 2026-07-18 at `2607.003`, seeded from the number of commits pushed to GitHub in July 2026.

Related: [[project-overview]], [[feedback-lambda-packaging]] (bump is Step 0 of the packaging rule in CLAUDE.md).
