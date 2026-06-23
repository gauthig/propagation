# ── DynamoDB: Solar cache and history ────────────────────────────────────────
resource "aws_dynamodb_table" "hf_solar" {
  name         = "hf_solar"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "record_id"

  attribute {
    name = "record_id"
    type = "S"
  }

  # Auto-expire timestamped history rows (record_id != "current").
  # The app writes an `expire_at` epoch on history rows; the "current"
  # fast-lookup row omits it and is never expired.
  ttl {
    attribute_name = "expire_at"
    enabled        = true
  }

  tags = var.tags
}

# ── DynamoDB: Visitor / callsign tracking ─────────────────────────────────────
resource "aws_dynamodb_table" "hf_users" {
  name         = "hf_users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "callsign"

  attribute {
    name = "callsign"
    type = "S"
  }

  tags = var.tags
}
