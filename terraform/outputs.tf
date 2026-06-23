output "lambda_function_url" {
  description = "Direct Lambda Function URL (bypass CloudFront for testing)"
  value       = aws_lambda_function_url.hf_propagation.function_url
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain — add as CNAME target in your DNS"
  value       = aws_cloudfront_distribution.hf_propagation.domain_name
}

output "app_url" {
  description = "Production URL"
  value       = "https://${local.fqdn}"
}

output "acm_certificate_validation_options" {
  description = "DNS CNAME records needed to validate the ACM wildcard certificate"
  value       = aws_acm_certificate.wildcard.domain_validation_options
}

output "ses_dkim_tokens" {
  description = "DKIM CNAME records to add to your DNS provider for SES"
  value       = aws_ses_domain_dkim.ggcloud.dkim_tokens
}

output "dynamodb_solar_table_arn" {
  value = aws_dynamodb_table.hf_solar.arn
}

output "dynamodb_users_table_arn" {
  value = aws_dynamodb_table.hf_users.arn
}
