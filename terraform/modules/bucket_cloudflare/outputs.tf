output "cf_r2_bucket_name" {
  value = cloudflare_r2_bucket.self.name
}

output "cf_r2_bucket_location" {
  value = cloudflare_r2_bucket.self.location
}

output "cf_r2_bucket_token" {
  value = cloudflare_account_token.self.value
  sensitive = true
}

output "cf_r2_bucket_token_id" {
  value = cloudflare_account_token.self.id
}

output "cf_r2_bucket_token_secret_access_key" {
  value = sha256(cloudflare_account_token.self.value)
  sensitive = true
}
