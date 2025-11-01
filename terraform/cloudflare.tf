resource "cloudflare_zone" "haydenmoe" {
  account = {
    id = var.CLOUDFLARE_ACCOUNT_ID
  }

  name = "hayden.moe"
}
