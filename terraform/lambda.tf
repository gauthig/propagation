# ── Lambda function ───────────────────────────────────────────────────────────
resource "aws_lambda_function" "hf_propagation" {
  function_name = var.lambda_function_name
  description   = "HF Propagation Map — Flask app via custom WSGI adapter"

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  runtime       = "python3.14"
  architectures = ["x86_64"]
  handler       = "app.handler"
  role          = aws_iam_role.lambda_exec.arn

  memory_size = 512 # heatmap loop runs ~1800 trig calls per request
  timeout     = 30  # allows for slow solar data fetches from hamqsl.com

  # AWS_REGION is a reserved Lambda key — the runtime injects it; setting it here
  # fails apply with a ValidationException.
  environment {
    variables = var.ses_sender_email != "" ? { SES_SENDER_EMAIL = var.ses_sender_email } : {}
  }

  tags = var.tags
}

# ── Lambda Function URL (public, no auth) ─────────────────────────────────────
resource "aws_lambda_function_url" "hf_propagation" {
  function_name      = aws_lambda_function.hf_propagation.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    allow_methods     = ["*"]
    allow_headers     = ["content-type"]
    max_age           = 0
  }
}
