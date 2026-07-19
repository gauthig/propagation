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

# ── CloudFront managed policies ───────────────────────────────────────────────
# AWS-managed policy IDs are global constants (identical in every account).
# Hardcoded instead of data-source lookups so plan/apply doesn't require the
# cloudfront:ListCachePolicies / ListOriginRequestPolicies IAM permissions.
locals {
  # UseOriginCacheControlHeaders — min/default TTL 0, so CloudFront caches ONLY responses
  # where Flask sends a Cache-Control header (/, /robots.txt, /sitemap.xml). All other
  # routes send no header and stay fully dynamic. NOTE: this policy excludes query strings
  # from the cache key — never send Cache-Control from a query-varying route (e.g. /heatmap).
  cache_policy_use_origin_cache_headers    = "83da9c7e-98b4-4e11-a168-04f0df8e2c65" # UseOriginCacheControlHeaders
  origin_policy_all_viewer_except_host_hdr = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader
}

# ── CloudFront distribution ───────────────────────────────────────────────────
resource "aws_cloudfront_distribution" "hf_propagation" {
  enabled         = true
  comment         = "HF Propagation Map — ${local.fqdn}"
  aliases         = [local.fqdn]
  price_class     = "PriceClass_All" # forced: CloudFront Free pricing plan disallows selecting a price class
  is_ipv6_enabled = true

  # WAF web ACL created via the CloudFront console — must stay attached
  web_acl_id = "arn:aws:wafv2:us-east-1:${data.aws_caller_identity.current.account_id}:global/webacl/CreatedByCloudFront-1b132734/d515817b-739e-4c52-92f2-a088863694b5"

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

    cache_policy_id = local.cache_policy_use_origin_cache_headers
    # AllViewerExceptHostHeader is required — without it Lambda rejects requests
    # because the Host header contains the CloudFront domain instead of the Function URL
    origin_request_policy_id = local.origin_policy_all_viewer_except_host_hdr

    compress = true
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.wildcard.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.3_2025"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  tags = var.tags
}
