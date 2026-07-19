data "aws_caller_identity" "current" {}

# ── IAM: Lambda execution role ───────────────────────────────────────────────
# Name and path match the console-created role adopted via `terraform import`
# on 2026-07-18 — IAM roles cannot be renamed in place, so keep these as-is.
resource "aws_iam_role" "lambda_exec" {
  name = "hf-propagation-role-x6khsb2n"
  path = "/service-role/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = var.tags
}

# Basic Lambda logging permissions (CloudWatch) — the console generated a
# customer-managed copy of AWSLambdaBasicExecutionRole; reference it by ARN.
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/service-role/AWSLambdaBasicExecutionRole-962979a9-f854-4249-88e9-a78704bb78cd"
}

# DynamoDB access — GetItem, PutItem, UpdateItem, Scan, BatchWriteItem
# Scan is required for solar history pruning; BatchWriteItem for bulk delete of old rows
resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "hf-dynamodb-local1" # console-created name, adopted via import
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Scan",
          "dynamodb:BatchWriteItem"
        ]
        Resource = [
          aws_dynamodb_table.hf_solar.arn,
          aws_dynamodb_table.hf_users.arn
        ]
      }
    ]
  })
}

# SES send permission — only attached when ses_sender_email is set
resource "aws_iam_role_policy" "lambda_ses" {
  count = var.ses_sender_email != "" ? 1 : 0

  name = "hf-ses-send"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ses:SendEmail", "ses:SendRawEmail"]
        Resource = "*"
      }
    ]
  })
}
