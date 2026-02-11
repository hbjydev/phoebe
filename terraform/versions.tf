terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = ">= 5"
    }

    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = "~> 5.26"
    }

    tailscale = {
      source = "tailscale/tailscale"
      version = "~> 0.27"
    }

    onepassword = {
      source = "1Password/onepassword"
      version = "~> 3.0"
    }

    grafana = {
      source  = "grafana/grafana"
      version = "~> 4.0"
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
