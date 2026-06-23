# ── IAM: Lambda execution role ───────────────────────────────────────────────
resource "aws_iam_role" "lambda_exec" {
  name = "hf-propagation-lambda-exec"

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

# Basic Lambda logging permissions (CloudWatch)
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# DynamoDB access — GetItem, PutItem, UpdateItem, Scan, BatchWriteItem
# Scan is required for solar history pruning; BatchWriteItem for bulk delete of old rows
resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "hf-dynamodb-access"
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
