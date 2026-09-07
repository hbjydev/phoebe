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

# Point *.hayden.moe at the UniFi resolver so tailnet clients resolve internal
# and public services the same way they do on the LAN. Restricted to the one
# domain, so global DNS is untouched.
resource "tailscale_dns_split_nameservers" "hayden-moe" {
  domain      = "hayden.moe"
  nameservers = ["10.70.0.1"]
}
