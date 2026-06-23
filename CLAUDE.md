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
pip install flask requests -t $pkg --quiet
Copy-Item app.py, propagation.py $pkg
Copy-Item templates "$pkg\templates" -Recurse
if (Test-Path lambda.zip) { Remove-Item lambda.zip -Force }
Compress-Archive -Path "$pkg\*" -DestinationPath lambda.zip
$mb = [math]::Round((Get-Item lambda.zip).Length / 1MB, 1)
Write-Host "Done — lambda.zip is $mb MB"
```

Expected output: `Done — lambda.zip is ~3.1 MB`. `boto3` is intentionally excluded — it is pre-installed in the Lambda Python 3.14 runtime.

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
