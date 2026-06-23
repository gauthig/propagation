---
name: feedback-lambda-packaging
description: "Always repackage lambda.zip after any change to app.py, propagation.py, or templates/"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e2ad7436-0bf3-4f57-a856-01ffc6389bab
---

Always rebuild and repackage `lambda.zip` after making any change to `app.py`, `propagation.py`, or anything under `templates/`.

**Why:** The deployed Lambda runs from the zip — changes to source files on disk have no effect until the zip is rebuilt and re-uploaded.

**How to apply:** Run this PowerShell block from the repo root immediately after editing any of those files, before reporting the task as done:

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

Expected output: `Done — lambda.zip is ~3.1 MB`

`boto3` is intentionally excluded — it is pre-installed in the Lambda Python 3.14 runtime.
