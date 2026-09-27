---
name: feedback-lambda-packaging
description: "Rebuild lambda.zip (bump APP_VERSION first) after any change to app.py, propagation.py, templates/ or antennas/ — plus build/commit gotchas"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e2ad7436-0bf3-4f57-a856-01ffc6389bab
  modified: 2026-09-27T18:06:53.660Z
---

After editing `app.py`, `propagation.py`, `templates/` or `antennas/`, bump `APP_VERSION`
(YYMM.###, see [[project-versioning]]) and rebuild `lambda.zip` with the script in CLAUDE.md
rule 1 before reporting done. The script is the source of truth — don't keep a copy here.

**Why:** Lambda runs the zip, not the working tree. numpy must be manylinux `.so` wheels
(`--platform manylinux_2_28_x86_64`), never Windows `.pyd`; `antennas/*.json` must be inside or
`/heatmap` 500s for the elevated GP / soil. Expected size ≈22 MB.

**How to apply (gotchas from 2026-09-27):**
- A PreToolUse hook blocks `Remove-Item` when the same command also has a variable path or a
  wildcard (`$pkg`, `lambda_package\*` in `Compress-Archive`). Run the cleanup
  (`Remove-Item .\lambda_package -Recurse -Force` + temp zip) as its own command, then build.
- Verify after build: `APP_VERSION` in the package, `.so` count > 0 / `.pyd` = 0, antennas present.
- Commit messages: PowerShell here-string piped to `git commit -F -` fails (message treated as a
  pathspec) — write the message to a scratchpad file and `git commit -F <file>`.
- Deploy = `terraform -chdir=terraform plan -out=tfplan` → expect exactly one in-place change
  (Lambda `source_code_hash`) → `apply tfplan` → check live version with `?nocache=<random>`.
