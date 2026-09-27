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

**1. Build the Lambda zip** with the script in [Package the app](#package-the-app). It needs Linux numpy wheels and the `antennas/` tables, so don't hand-roll a simpler zip.

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

After any code change, bump `APP_VERSION` in `app.py`, rebuild the zip ([Package the app](#package-the-app)), then plan and apply:

```powershell
terraform -chdir=terraform plan -out=tfplan   # expect exactly one in-place change: the Lambda code hash
terraform -chdir=terraform apply tfplan
```

Terraform detects the changed `source_code_hash` and deploys only the Lambda update, with no CloudFront invalidation needed. Never apply a plan with unexplained lines. In particular, the WAF web ACL and TLS 1.3 minimum declared in `cloudfront.tf` must never show as removals.

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
- **`record_id = "<timestamp>Z"`** (e.g. `2026-06-22T14:30:00.123456Z`) — one history row per refresh, carrying an `expire_at` epoch attribute

**Enable TTL** on the table: DynamoDB → `hf_solar` → **Additional settings** → **Time to Live** → attribute `expire_at`. DynamoDB then deletes history rows after 7 days on its own, with no Scan and no read cost. Terraform sets this up automatically.

Each row includes `refreshed_by`: the callsign that triggered the refresh, or `"auto"` for scheduled/startup fetches.

### Table 2 — Users and accounts (`hf_users`)

| Setting | Value |
|---|---|
| Table name | `hf_users` |
| Partition key | `callsign` (String) |

One row per callsign. It is the stable identity for visitor tracking (browser, QTH, visit count) and for accounts: a PBKDF2 password hash, a login token (the `hf_auth` cookie, 30 days), an email for password resets, and `active`/`admin` flags. Anonymous visitors are not written to this table.

Wait for both tables to show status **Active** before deploying.

---

## IAM policy

Both the Lambda execution role and your local IAM user need the following policy (it matches `terraform/iam.tf`). `Scan` is used by the admin user list; the SES statement is only needed if you enable password-reset emails.

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
        "dynamodb:DeleteItem",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
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

The deployment zip contains:
- the app source (`app.py`, `propagation.py`, `templates/`);
- the antenna gain tables (`antennas/`) — required, or the elevated-GP and soil features fail;
- Flask and numpy.

numpy ships compiled code, so it must be the **Linux (manylinux)** wheel that matches the Lambda runtime, even when you build on Windows or macOS. `boto3` is **not** included, because every Lambda Python runtime already has it. CLAUDE.md rule 1 holds the canonical version of this script (it also bumps `APP_VERSION`).

**Windows (PowerShell)**, from the repo root:

```powershell
if (Test-Path .\lambda_package) { Remove-Item .\lambda_package -Recurse -Force }
New-Item -ItemType Directory -Path .\lambda_package | Out-Null
pip install --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.14 `
            --only-binary=:all: --target .\lambda_package flask numpy --quiet
Copy-Item app.py, propagation.py .\lambda_package
Copy-Item templates .\lambda_package\templates -Recurse
Copy-Item antennas  .\lambda_package\antennas  -Recurse
Compress-Archive -Path .\lambda_package\* -DestinationPath "$env:TEMP\lambda_build.zip" -Force
Copy-Item "$env:TEMP\lambda_build.zip" .\lambda.zip -Force   # build in TEMP: OneDrive locks files mid-sync
```

**macOS / Linux:**

```bash
rm -rf lambda_package && mkdir lambda_package
pip install --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.14 \
            --only-binary=:all: --target lambda_package flask numpy --quiet
cp app.py propagation.py lambda_package/
cp -r templates antennas lambda_package/
(cd lambda_package && zip -qr ../lambda.zip .)
```

The resulting `lambda.zip` is about 22 MB, mostly numpy. That's well under Lambda's 50 MB direct-upload limit. Check that `lambda_package/numpy/_core/` contains `.so` files. If you see Windows `.pyd` files, the `--platform` flags were dropped, and Lambda will fail with `ImportError: ... _multiarray_umath`.

---

## Create the Lambda function

1. AWS Console → **Lambda** → **Create function**
2. **Author from scratch**
3. Runtime: **Python 3.14**, Architecture: **x86\_64**
4. Click **Create function**

### Upload the zip

- **Code** tab → **Upload from** → **.zip file** → select `lambda.zip` → **Save**

### Set the handler

- **Runtime settings** → **Edit** → Handler: `app.handler` → **Save**

### Configure memory and timeout

- **Configuration** → **General configuration** → **Edit**

| Setting | Value | Reason |
|---|---|---|
| Memory | 512 MB | numpy model computes a full map in ~20 ms; memory also buys CPU on Lambda |
| Timeout | 30 sec | Allows for slow solar data fetches from hamqsl.com |

### Environment variable (optional)

- `SES_SENDER_EMAIL` — a verified SES sender address for password-reset emails. Without it, sign-in still works but reset emails are not sent. Terraform sets it from `ses_sender_email` in `terraform.tfvars`.

> **Python runtime note:** Use **Python 3.14** — it is the current AWS-recommended Lambda runtime. Python 3.13 is flagged for deprecation by AWS. If you need an older stable version for any reason, use **Python 3.12**.

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
6. **Cache policy:** CachingDisabled for the default behavior. Then add four cache behaviors using **CachingOptimized**, with path patterns `/`, `/robots.txt`, `/sitemap.xml` and `/BingSiteAuth.xml`. The app sends `Cache-Control` on those routes, and CloudFront honors the TTLs. Do **not** use `UseOriginCacheControlHeaders` — it puts the Host header in the cache key, which forwards the viewer Host to the origin, and Lambda Function URLs reject that with 403
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

## Updating the Python runtime

When a newer Python version becomes available on Lambda (e.g. 3.14), update in two steps:

**Terraform:**

1. Edit `terraform/lambda.tf` and change the `runtime` value:
   ```hcl
   runtime = "python3.14"
   ```
2. Apply:
   ```bash
   cd terraform && terraform apply
   ```

**Manual (Console):**

1. Lambda console → your function → **Runtime settings** → **Edit**
2. Select the new runtime from the dropdown → **Save**
3. Rebuild the zip with `--python-version` changed to match the new runtime (numpy's compiled wheel is version-specific), redeploy, and confirm the heatmap loads.

> The runtime change takes effect on the next cold start. Warm instances keep the old runtime for up to ~15 minutes.

> To verify the current runtime or switch versions via CLI:
> ```bash
> aws lambda update-function-configuration \
>   --function-name hf-propagation \
>   --runtime python3.14 \
>   --region us-east-1
> ```
> An `InvalidParameterValueException` means that version string is not yet available — fall back to `python3.12`. Alternatively, open the Lambda console → your function → **Runtime settings** → **Edit** and pick from the dropdown.

---

## Updating the app

**Terraform:** bump `APP_VERSION`, rebuild the zip ([Package the app](#package-the-app)), then plan and apply, as described in [Updating the app with Terraform](#updating-the-app-with-terraform).

**Manual:** rebuild the zip, then re-upload:

1. Run the packaging script above
2. Lambda console → **Code** tab → **Upload from** → **.zip file** → select `lambda.zip` → **Save**

Lambda deploys the new code immediately — no CloudFront invalidation needed for code changes.
