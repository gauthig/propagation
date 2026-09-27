---
name: project-overview
description: "What the HF Propagation app is, its stack and repo layout, and infra facts that aren't obvious from the code"
metadata:
  node_type: memory
  type: project
  originSessionId: 01d8b071-b683-4806-9b45-7401f7b7e97b
  modified: 2026-09-27T18:07:53.608Z
---

Single-page HF propagation heatmap for hams: pick a band, QTH and antenna; see where the band is
open now. Live at https://propagation.ggcloud.us, repo github.com/gauthig/propagation (public,
GPL-3.0). Owner/user: [[user-profile]].

**Stack:** Flask on AWS Lambda (Function URL, Python 3.14, custom WSGI adapter — no Mangum) behind
CloudFront (+ WAF) with Cloudflare DNS-only CNAME; DynamoDB `hf_solar` + `hf_users`; numpy model;
D3 frontend in one template. Terraform manages all infra (imported 2026-07-18; local state).

**Repo layout**
- `app.py` routes/auth/DynamoDB/WSGI · `propagation.py` model · `templates/index.html` UI
- `antennas/*.json` — NEC2++/reference gain tables, **packaged with the Lambda**
- `tools/validate/` ionosonde + WSPR scoring kit · `tools/antenna/` table generators (dev-only)
- `terraform/` infra · `CLAUDE.md` rules, build script, decision log · `.claude/memory/` shared notes

**Local dev:** `.\venv\Scripts\python.exe app.py`. The venv was recreated 2026-09-27 on
`C:\Program Files\Python314` (Python moved from `C:\Python314`, which broke the old venv) with
`requirements.txt` + `requirements-dev.txt` (ruff, boto3). `.claude/launch.json` defines the
`propagation-local` preview server (port 5000).

**Non-obvious infra facts**
- ACM cert must live in us-east-1; CloudFront origin = bare Function URL hostname with origin
  request policy AllViewerExceptHostHeader (Lambda rejects a foreign Host). A CNAME straight to the
  Function URL never works. Cloudflare proxy must stay OFF (grey cloud).
- IAM role keeps its console name `hf-propagation-role-x6khsb2n` (roles can't be renamed); the WAF
  web ACL and TLS 1.3 minimum are declared in `cloudfront.tf` — must never show as removals.
- Real Terraform vars (e.g. `ses_sender_email`) are in gitignored `terraform/terraform.tfvars`.

Related: [[api-routes]], [[propagation-model]], [[feedback-lambda-packaging]].
