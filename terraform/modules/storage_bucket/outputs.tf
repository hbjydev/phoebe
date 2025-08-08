output "cf_r2_bucket_name" {
  value = cloudflare_r2_bucket.self.name
}

output "cf_r2_bucket_location" {
  value = cloudflare_r2_bucket.self.location
}

output "cf_r2_bucket_token" {
  value = cloudflare_api_token.self.value
}
