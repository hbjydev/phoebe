terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = ">= 5"
      configuration_aliases = [ cloudflare.main, cloudflare.tokens ]
    }

    vault = {
      source = "hashicorp/vault"
      version = "~> 5.3"
    }
  }
}
