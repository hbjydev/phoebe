resource "cloudflare_r2_bucket" "self" {
  account_id = var.account_id
  name = var.name
  location = "WEUR"
  storage_class = var.storage_class
}
