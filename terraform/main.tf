terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Primary region provider — Lambda, DynamoDB, SES live here
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

# CloudFront ACM certificates MUST be in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = var.tags
  }
}

# ── Resource group ────────────────────────────────────────────────────────────
# Queries all resources tagged app=hf_propagation across all supported services
resource "aws_resourcegroups_group" "hf_propagation" {
  name        = "hf_propagation"
  description = "HF Propagation Map — all app resources"

  resource_query {
    query = jsonencode({
      ResourceTypeFilters = ["AWS::AllSupported"]
      TagFilters = [
        {
          Key    = "app"
          Values = ["hf_propagation"]
        }
      ]
    })
  }

  tags = var.tags
}
