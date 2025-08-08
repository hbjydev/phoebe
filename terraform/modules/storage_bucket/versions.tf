terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5"
      configuration_aliases = [ cloudflare.main, cloudflare.tokens ]
    }
  }
}
