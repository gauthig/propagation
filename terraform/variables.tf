variable "aws_region" {
  description = "Primary AWS region for Lambda and DynamoDB"
  type        = string
  default     = "us-east-1"
}

variable "domain_name" {
  description = "Root domain (e.g. ggcloud.us)"
  type        = string
  default     = "ggcloud.us"
}

variable "subdomain" {
  description = "Subdomain for this app"
  type        = string
  default     = "propagation"
}

variable "ses_sender_email" {
  description = "Verified SES sender address used for auth emails (SES_SENDER_EMAIL env var)"
  type        = string
  default     = ""
}

variable "lambda_zip_path" {
  description = "Path to the Lambda deployment zip relative to the terraform directory"
  type        = string
  default     = "../lambda.zip"
}

variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "hf-propagation"
}

variable "tags" {
  description = "Common tags applied to all resources"
  type        = map(string)
  default = {
    app = "hf_propagation"
  }
}
