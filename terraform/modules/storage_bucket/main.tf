resource "cloudflare_r2_bucket" "self" {
  account_id = var.account_id
  name = var.name
  location = "WEUR"
  storage_class = var.storage_class
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
}
