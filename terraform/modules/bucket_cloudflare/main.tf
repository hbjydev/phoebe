resource "cloudflare_r2_bucket" "self" {
  account_id = var.account_id
  name = var.name
  location = "WEUR"
  storage_class = var.storage_class
  provider = cloudflare.main
}

resource "cloudflare_api_token" "self" {
  name = "R2-${var.name}-RW"

  policies = [{
    effect = "allow"
    resources = jsonencode({
      "${local.iam_bucket_name}" = "*"
    })
    permission_groups = [for x in local.permission_id_list : { id = x }]
  }]

  provider = cloudflare.tokens
}

resource "vault_kv_secret_v2" "self_token" {
  mount     = var.vault_mount
  name      = "r2/${var.name}"
  data_json = jsonencode({
    endpoint          = "https://${cloudflare_r2_bucket.self.name}.r2.cloudflarestorage.com/${cloudflare_r2_bucket.self.name}",
    bucket_name       = cloudflare_r2_bucket.self.name,
    access_key_id     = cloudflare_api_token.self.id,
    secret_access_key = sha256(cloudflare_api_token.self.value)
  })

  custom_metadata {
    data = { managed-by = "terraform" }
  }
}

resource "cloudflare_r2_bucket_cors" "self" {
  count = var.name == "sso-haydenmoe-storage" ? 1 : 0

  account_id = var.account_id
  bucket_name = cloudflare_r2_bucket.self.name
  rules = [{
    allowed = {
      methods = ["GET"]
      origins = ["https://sso.hayden.moe"]
      headers = ["Authorization"]
    }
    id = "Allow Authentik access"
    max_age_seconds = 3600
  }]
  provider = cloudflare.main
}
