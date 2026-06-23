# AWS Deployment Guide

This guide covers deploying the HF Propagation Map to AWS Lambda with DynamoDB for storage and (optionally) CloudFront for a custom domain.

---

## Architecture overview

```
Browser → CloudFront (optional) → Lambda Function URL → Flask app → DynamoDB
```

- **Lambda** runs the Flask app via a custom WSGI adapter — no server to manage
- **DynamoDB** stores the solar cache and visitor records — shared across all Lambda instances
- **CloudFront** provides the custom domain and SSL termination (required if you want a vanity URL)

---

## Deployment options

| Option | When to use |
|---|---|
| **Terraform** (recommended) | New deployment, or taking existing resources under IaC |
| **Manual (AWS Console)** | Quick one-off change or if Terraform is not available |

---

## Option A — Terraform (automated)

The `terraform/` directory in this repo contains a complete Terraform configuration that creates and manages all AWS resources.

### Prerequisites

- [Terraform CLI](https://developer.hashicorp.com/terraform/install) ≥ 1.5
- AWS credentials configured (`aws configure` or environment variables `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`)

### First-time setup

**1. Build the Lambda zip** (skip if `lambda.zip` already exists — see [Package the app](#package-the-app)):

```powershell
# Windows (PowerShell) — run from the repo root
$pkg = "lambda_package"
if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $pkg | Out-Null
pip install flask requests -t $pkg --quiet
Copy-Item app.py, propagation.py $pkg
Copy-Item templates $pkg\templates -Recurse
Compress-Archive -Path "$pkg\*" -DestinationPath lambda.zip -Force
```

**2. Create your variable file:**

```powershell
cd terraform
Copy-Item terraform.tfvars.example terraform.tfvars
```

Open `terraform.tfvars` and fill in your values:

```hcl
aws_region           = "us-east-1"
domain_name          = "ggcloud.us"
subdomain            = "propagation"
ses_sender_email     = "noreply@ggcloud.us"   # must be verified in SES
lambda_function_name = "hf-propagation"
lambda_zip_path      = "../lambda.zip"
```

**3. Initialize and apply:**

```bash
terraform init
terraform plan    # review what will be created
terraform apply
```

Terraform will output:
- **`lambda_function_url`** — direct Lambda URL (use for smoke-testing)
- **`cloudfront_domain`** — add this as a CNAME in your DNS
- **`acm_certificate_validation_options`** — CNAME records needed to validate the ACM cert
- **`ses_dkim_tokens`** — DKIM CNAME records to add to your DNS

> **ACM validation:** after `terraform apply`, the ACM wildcard cert will be in *Pending validation* until you add the CNAME record shown in `acm_certificate_validation_options` to your DNS provider. CloudFront will not finish deploying until the cert is issued.

> **Cloudflare DNS:** set the CNAME pointing to `cloudfront_domain` to **DNS only (grey cloud)**. The orange proxy conflicts with CloudFront SSL and causes 403 errors.

---

### Importing existing resources into Terraform state

If the resources already exist in AWS, import them instead of recreating them:

**1. Edit `terraform/import.sh`** and fill in your account details at the top:

```bash
AWS_ACCOUNT_ID="123456789012"        # your 12-digit AWS account ID
                                     # find it: AWS Console → top-right account menu
LAMBDA_FUNCTION_NAME="hf-propagation"
CF_DISTRIBUTION_ID="EXXXXXXXXXXXX"  # CloudFront console → Distribution ID column
ACM_CERT_ARN="arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                                     # ACM console (us-east-1) → certificate ARN
```

**2. Run the import script:**

```bash
cd terraform
terraform init
bash import.sh
```

**3. Verify no unintended changes:**

```bash
terraform plan
```

The plan should show zero changes (or only minor tag/description drift). Fix any drift before running `apply`.

---

### Updating the app with Terraform

After any code change, rebuild the zip and let Terraform detect the new hash:

```bash
# from repo root
Compress-Archive -Path "lambda_package\*" -DestinationPath lambda.zip -Force
cd terraform && terraform apply
```

Terraform detects the changed `source_code_hash` and deploys only the Lambda update — no CloudFront invalidation needed.

---

## Option B — Manual (AWS Console)

The sections below walk through each resource in the AWS Console. Use these if you prefer not to use Terraform or need to make a targeted change.

---

## DynamoDB tables

Create both tables in the AWS Console → **DynamoDB** → **Create table**. Use default settings (on-demand billing, no sort key) unless noted.

### Table 1 — Solar cache and history (`hf_solar`)

| Setting | Value |
|---|---|
| Table name | `hf_solar` |
| Partition key | `record_id` (String) |

Two kinds of rows are written to this table:

- **`record_id = "current"`** — updated on every refresh; used for the fast O(1) freshness check on every page load
- **`record_id = "<timestamp>Z"`** (e.g. `2026-06-22T14:30:00.123456Z`) — one new row per refresh; oldest rows are automatically deleted when the count exceeds 100

Each row includes `refreshed_by` (the callsign that triggered the refresh, or `"auto"` for scheduled/startup fetches).

### Table 2 — Visitor tracking (`hf_users`)

| Setting | Value |
|---|---|
| Table name | `hf_users` |
| Partition key | `callsign` (String) |

One row per callsign. The callsign is the stable cross-browser identity — the same row is updated regardless of which browser, IP address, or device a user connects from, as long as they enter the same callsign.

Anonymous visitors (users who skip the callsign prompt) are not written to this table.

Wait for both tables to show status **Active** before deploying.

---

## IAM policy

Both the Lambda execution role and your local IAM user need the following policy. The `Scan` and `BatchWriteItem` actions are required for the solar history pruning logic.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": "*"
    }
  ]
}
```

### Attach to the Lambda execution role

1. Lambda console → your function → **Configuration** → **Permissions** → click the role name
2. **Add permissions** → **Create inline policy** → JSON tab → paste the policy above
3. Name it `hf-dynamodb-access` → **Create policy**

---

## Package the app

Build a deployment zip that includes the app source and its pip dependencies. `boto3` is **not** included — it is pre-installed in every Lambda Python runtime.

**Windows (PowerShell):**

```powershell
$root = "C:\path\to\propagation"
$pkg  = "$root\lambda_package"

if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $pkg | Out-Null

pip install flask requests -t $pkg --quiet

Copy-Item "$root\app.py"         "$pkg\app.py"
Copy-Item "$root\propagation.py" "$pkg\propagation.py"
Copy-Item "$root\templates"      "$pkg\templates" -Recurse

$zip = "$root\lambda.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$pkg\*" -DestinationPath $zip

Write-Host "Done — $([math]::Round((Get-Item $zip).Length/1MB, 1)) MB"
```

**macOS / Linux:**

```bash
cd /path/to/propagation
rm -rf lambda_package && mkdir lambda_package
pip install flask requests -t lambda_package --quiet
cp app.py propagation.py lambda_package/
cp -r templates lambda_package/
cd lambda_package && zip -r ../lambda.zip . && cd ..
echo "Done — $(du -sh ../lambda.zip | cut -f1)"
```

The resulting `lambda.zip` should be approximately 3 MB.

---

## Create the Lambda function

1. AWS Console → **Lambda** → **Create function**
2. **Author from scratch**
3. Runtime: **Python 3.12**, Architecture: **x86\_64**
4. Click **Create function**

### Upload the zip

- **Code** tab → **Upload from** → **.zip file** → select `lambda.zip` → **Save**

### Set the handler

- **Runtime settings** → **Edit** → Handler: `app.handler` → **Save**

### Configure memory and timeout

- **Configuration** → **General configuration** → **Edit**

| Setting | Value | Reason |
|---|---|---|
| Memory | 512 MB | Heatmap loop runs ~1,800 trig calls per request |
| Timeout | 30 sec | Allows for slow solar data fetches from hamqsl.com |

### Add a Function URL

- **Configuration** → **Function URL** → **Create function URL**
- Auth type: **NONE**
- Enable **CORS** — Allow origin: `*`, Allow methods: `*`, Allow headers: `content-type`
- **Save**

Copy the generated Function URL. That is your public app address. Test it in a browser before proceeding.

---

## Custom domain via CloudFront

A bare CNAME pointing to a Lambda Function URL does not work — Lambda validates the `Host` header and rejects requests that don't match the Function URL hostname. CloudFront sits in between and forwards the correct header.

### Step 1 — ACM certificate

Request a **wildcard certificate** so any subdomain is covered without a new cert each time.

> The certificate **must** be created in **us-east-1** regardless of where your Lambda lives — CloudFront only reads ACM certs from that region.

1. AWS Console → **ACM** (Certificate Manager) → switch region to **us-east-1**
2. **Request certificate** → Public
3. Domain: `*.yourdomain.com`
4. Validation method: **DNS validation**
5. Add the provided CNAME record to your DNS provider
6. Wait for status **Issued** (usually a few minutes if the DNS record is correct)

### Step 2 — CloudFront distribution

1. AWS Console → **CloudFront** → **Create distribution**
2. **Origin domain:** paste your Lambda Function URL — bare hostname only, no `https://`
3. **Origin type:** Other (Custom origin)
4. **Protocol:** HTTPS only
5. **Allowed HTTP methods:** GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE
6. **Cache policy:** CachingDisabled
7. **Origin request policy:** `AllViewerExceptHostHeader` — **required**; without this Lambda rejects every request with a host header mismatch
8. **Alternate domain names:** your custom subdomain (e.g. `propagation.yourdomain.com`)
9. **Custom SSL certificate:** select the ACM wildcard cert
10. Click **Create distribution** — deployment takes 5–10 minutes

### Step 3 — DNS

Point your subdomain to the CloudFront distribution domain name (shown in the CloudFront console, format `dXXXXXXXXXXXX.cloudfront.net`).

**If your DNS is managed by Cloudflare:**

| Type | Name | Target | Proxy status |
|---|---|---|---|
| CNAME | `propagation` | `dXXXXXXXXXXXX.cloudfront.net` | **DNS only (grey cloud)** |

> The Cloudflare proxy (orange cloud) **must be off**. Enabling it creates a double-proxy conflict with CloudFront SSL and produces a 403 error.

**Other DNS providers:** add a standard CNAME record with the same target.

### Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `{"Message": null}` on the custom domain | Bare CNAME to Lambda URL, no CloudFront | Add CloudFront as described above |
| 403 from CloudFront | Origin request policy missing or wrong | Set to `AllViewerExceptHostHeader` |
| `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` | ACM cert doesn't cover the subdomain | Use a wildcard cert `*.yourdomain.com` |
| 403 persists after setting the policy | Cloudflare proxy is still orange | Set DNS record to grey cloud (DNS only) |
| ACM cert stuck in Pending validation | CNAME not added to DNS, or wrong record | Verify the exact CNAME name and value from the ACM console |

---

## Updating the app

**Terraform:** rebuild the zip, then apply:

```bash
Compress-Archive -Path "lambda_package\*" -DestinationPath lambda.zip -Force
cd terraform && terraform apply
```

**Manual:** rebuild the zip, then re-upload:

1. Run the packaging script above
2. Lambda console → **Code** tab → **Upload from** → **.zip file** → select `lambda.zip` → **Save**

Lambda deploys the new code immediately — no CloudFront invalidation needed for code changes.
