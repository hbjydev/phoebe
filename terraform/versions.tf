terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5"
    }

    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = "~> 5.26"
    }

    tailscale = {
      source = "tailscale/tailscale"
      version = "~> 0.22"
    }

    onepassword = {
      source = "1Password/onepassword"
      version = "~> 2.1"
    }

    grafana = {
      source  = "grafana/grafana"
      version = ">= 2.9.0"
    }
  }
}

provider "cloudflare" {}
provider "cloudflare" {
  alias = "tokens"
  api_token = var.CLOUDFLARE_TOKENS_API_TOKEN
}

provider "upcloud" {}
provider "onepassword" {}
provider "tailscale" {}
provider "grafana" {
  alias = "cloud"
}
