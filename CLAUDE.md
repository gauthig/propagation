# Claude Code — Project Guide

This file is read automatically by [Claude Code](https://claude.ai/code) whenever you open this project. It gives Claude the context needed to work on the HF Propagation Map effectively from any machine.

---

## First-time setup on a new machine

After cloning the repo, install the project memory files so Claude has full context across sessions:

```powershell
# Run once from the repo root (Windows PowerShell)
.\.claude\install-memory.ps1
```

This copies the files from `.claude/memory/` to the correct Claude projects directory (`~/.claude/projects/.../memory/`) where Claude Code reads them automatically.

---

## Project overview

Flask single-page app that displays a real-time HF skywave propagation heatmap for amateur radio operators.

| Layer | Technology |
|---|---|
| Backend | Python 3.14, Flask, custom Lambda WSGI adapter |
| Database | AWS DynamoDB — `hf_solar` (solar cache) and `hf_users` (visitor tracking) |
| Frontend | D3 v7, Winkel Tripel projection, HTML5 Canvas heatmap |
| Hosting | AWS Lambda (Function URL) → CloudFront → Cloudflare DNS |
| IaC | Terraform (`terraform/`) |

**Production URL:** https://propagation.ggcloud.us

---

## Memory files

Detailed context is stored in `.claude/memory/`. Claude loads these automatically after running `install-memory.ps1`.

| File | Contents |
|---|---|
| `project_overview.md` | Architecture, stack, CloudFront/DNS gotchas, DynamoDB tables |
| `api_routes.md` | All Flask routes, DynamoDB schema, IAM requirements |
| `propagation_model.md` | foF2/MUF model, antenna factors, known limitations |
| `frontend_map.md` | D3 map layers, canvas heatmap, localStorage persistence |
| `ui_features.md` | Panel layout, modals, session tracking helpers |
| `feedback_lambda_packaging.md` | **Must-follow rule** — always repackage `lambda.zip` after code changes |

---

## Rules Claude must always follow

### 1. Repackage lambda.zip after every code change

Any edit to `app.py`, `propagation.py`, or `templates/` requires rebuilding the zip before the task is reported as done:

```powershell
$pkg = "lambda_package"
if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $pkg | Out-Null

# numpy ships COMPILED binaries — a normal `pip install -t` on Windows would
# package Windows .pyd files that crash on Lambda. Fetch the Linux (manylinux)
# wheels instead. Lambda's Python 3.14 runs on Amazon Linux 2023 (glibc 2.34),
# so the manylinux_2_28 numpy wheel is the right one. flask is pure-Python and
# satisfies any platform under --only-binary.
pip install --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.14 `
            --only-binary=:all: --target $pkg flask numpy --quiet

Copy-Item app.py, propagation.py $pkg
Copy-Item templates "$pkg\templates" -Recurse

# OneDrive locks lambda.zip mid-sync — build in TEMP, then copy into the repo.
$tmp = "$env:TEMP\lambda_build.zip"
if (Test-Path $tmp) { Remove-Item $tmp -Force }
Compress-Archive -Path "$pkg\*" -DestinationPath $tmp
Copy-Item $tmp lambda.zip -Force
$mb = [math]::Round((Get-Item lambda.zip).Length / 1MB, 1)
Write-Host "Done — lambda.zip is $mb MB"
```

Expected output: `Done — lambda.zip is ~22 MB` (numpy's compiled libraries are the
bulk; still well under Lambda's 50 MB direct-upload / 250 MB unzipped limits).
`requests` is no longer a dependency (replaced by stdlib `urllib`). `boto3` is
intentionally excluded — it is pre-installed in the Lambda Python 3.14 runtime.

⚠️ **Verify the numpy binaries are Linux, not Windows**, after building:
`Get-ChildItem $pkg\numpy\_core\*.so` should list `.so` files (Linux). If you see
`.pyd` files instead, the `--platform` flags were dropped and the zip will fail
on Lambda with `ImportError: ... _multiarray_umath`.

### 2. Keep memory files in sync

When making changes that affect architecture, routes, or deployment, update both:
- The canonical memory file at `~/.claude/projects/.../memory/<file>.md`
- The repo copy at `.claude/memory/<file>.md`

### 3. Python runtime

Lambda is running **Python 3.14**. Do not use syntax or stdlib features that require a newer version. boto3 is available in the Lambda environment without being in `requirements.txt`.

---

## Key development commands

**Run locally:**
```powershell
.\venv\Scripts\python.exe app.py
```
Must use the venv — system Python 3.14 has a Flask/Werkzeug incompatibility.

**Deploy (Terraform):**
```bash
cd terraform && terraform apply
```

**Deploy (manual zip upload):**
Lambda console → Code tab → Upload from → .zip file → select `lambda.zip` → Save.

---

## Architecture diagram

![AWS Architecture](hf_propagation_aws_architecture.svg)
