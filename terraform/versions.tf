terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5"
    }

    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = "~> 5"
    }

    tailscale = {
      source = "tailscale/tailscale"
      version = "~> 0.21"
    }
  }
}

provider "cloudflare" {}
provider "cloudflare" {
  alias = "tokens"
  api_token = var.CLOUDFLARE_TOKENS_API_TOKEN
}

provider "upcloud" {}
provider "tailscale" {}
