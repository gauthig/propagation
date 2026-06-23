# ── SES: Domain identity for sending auth emails ──────────────────────────────
# Verifies the entire ggcloud.us domain so any address @ggcloud.us can send
resource "aws_ses_domain_identity" "ggcloud" {
  domain = var.domain_name
}

# DKIM signing — add the three CNAME records this produces to your DNS provider
resource "aws_ses_domain_dkim" "ggcloud" {
  domain = aws_ses_domain_identity.ggcloud.domain
}
