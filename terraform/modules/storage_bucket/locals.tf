data "cloudflare_api_token_permission_groups_list" "self" {
  provider = cloudflare.tokens
}

locals {
  iam_bucket_name = "com.cloudflare.edge.r2.bucket.${var.account_id}_default_${var.name}"
  r2_api_perms = {
    for x in data.cloudflare_api_token_permission_groups_list.self.result :
      x.name => x.id
      if contains([
        "Workers R2 Storage Bucket Item Read",
        "Workers R2 Storage Bucket Item Write",
      ], x.name)
  }
  permission_id_list = [
    local.r2_api_perms["Workers R2 Storage Bucket Item Read"],
    local.r2_api_perms["Workers R2 Storage Bucket Item Write"],
  ]
}
