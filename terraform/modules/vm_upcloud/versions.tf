terraform {
  required_providers {
    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = ">= 5"
    }

    tailscale = {
      source = "tailscale/tailscale"
      version = "~> 0.24"
    }
  }
}
