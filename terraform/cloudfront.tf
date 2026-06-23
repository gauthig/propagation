locals {
  fqdn = "${var.subdomain}.${var.domain_name}"

  # Strip https:// and trailing slash from the Function URL to get the bare hostname
  lambda_origin_domain = replace(replace(aws_lambda_function_url.hf_propagation.function_url, "https://", ""), "/", "")
}

# ── ACM wildcard certificate — MUST be in us-east-1 for CloudFront ────────────
resource "aws_acm_certificate" "wildcard" {
  provider = aws.us_east_1

  domain_name       = "*.${var.domain_name}"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = var.tags
}

# ── CloudFront managed policy lookups ─────────────────────────────────────────
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host_header" {
  name = "AllViewerExceptHostHeader"
}

# ── CloudFront distribution ───────────────────────────────────────────────────
resource "aws_cloudfront_distribution" "hf_propagation" {
  enabled         = true
  comment         = "HF Propagation Map — ${local.fqdn}"
  aliases         = [local.fqdn]
  price_class     = "PriceClass_100"  # US, Canada, Europe only (cheapest)
  is_ipv6_enabled = true

  origin {
    origin_id   = "lambda-function-url"
    domain_name = local.lambda_origin_domain

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "lambda-function-url"
    viewer_protocol_policy = "redirect-to-https"

    # All methods needed — POST used by /track/* and /solar/refresh
    allowed_methods = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods  = ["GET", "HEAD"]

    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    # AllViewerExceptHostHeader is required — without it Lambda rejects requests
    # because the Host header contains the CloudFront domain instead of the Function URL
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host_header.id

    compress = true
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.wildcard.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  tags = var.tags
}
