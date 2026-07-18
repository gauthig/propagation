#!/usr/bin/env bash
# Import existing AWS resources into Terraform state.
# Run AFTER `terraform init`. Fill in the values in ALL_CAPS before running.
#
# Usage: bash import.sh

set -euo pipefail

AWS_ACCOUNT_ID="YOUR_ACCOUNT_ID"        # 12-digit number, e.g. 123456789012
LAMBDA_FUNCTION_NAME="hf-propagation"   # exact name in Lambda console
CF_DISTRIBUTION_ID="EXXXXXXXXXXXX"      # e.g. E1234ABCDEF5GH — from CloudFront console
ACM_CERT_ARN="arn:aws:acm:us-east-1:${AWS_ACCOUNT_ID}:certificate/YOUR-CERT-UUID"

# DynamoDB tables
terraform import aws_dynamodb_table.hf_solar  hf_solar
terraform import aws_dynamodb_table.hf_users  hf_users

# IAM role + attached policies
terraform import aws_iam_role.lambda_exec  hf-propagation-lambda-exec
terraform import aws_iam_role_policy.lambda_dynamodb  hf-propagation-lambda-exec:hf-dynamodb-access
terraform import aws_iam_role_policy_attachment.lambda_basic  "hf-propagation-lambda-exec/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

# Lambda function
terraform import aws_lambda_function.hf_propagation  "${LAMBDA_FUNCTION_NAME}"

# Lambda Function URL (uses function name as id)
terraform import aws_lambda_function_url.hf_propagation  "${LAMBDA_FUNCTION_NAME}"

# ACM wildcard cert (must target the us-east-1 provider alias)
terraform import "aws_acm_certificate.wildcard"  "${ACM_CERT_ARN}"

# CloudFront distribution
terraform import aws_cloudfront_distribution.hf_propagation  "${CF_DISTRIBUTION_ID}"

# SES domain identity + DKIM
terraform import aws_ses_domain_identity.ggcloud  ggcloud.us
terraform import aws_ses_domain_dkim.ggcloud  ggcloud.us

# Resource group
terraform import aws_resourcegroups_group.hf_propagation  hf_propagation

echo "All imports complete. Run 'terraform plan' to review any drift."
