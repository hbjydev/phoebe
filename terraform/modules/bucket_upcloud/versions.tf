terraform {
  required_providers {
    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = "~> 5"
    }

    vault = {
      source = "hashicorp/vault"
      version = "~> 5.3"
    }
  }
}
