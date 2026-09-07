terraform {
  required_providers {
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.29"
    }
  }
}

provider "tailscale" {
  oauth_client_id     = var.oauth_client_id
  oauth_client_secret = var.oauth_client_secret
}

# This resource owns the whole policy file, so policy.hujson is the source of
# truth. Keep reset_acl_on_destroy off; a destroy should not drop the tailnet
# back to permit-all.
resource "tailscale_acl" "policy" {
  acl                        = file("${path.module}/policy.hujson")
  overwrite_existing_content = true
  reset_acl_on_destroy       = false
}
