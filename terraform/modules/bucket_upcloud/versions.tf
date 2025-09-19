terraform {
  required_providers {
    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = "~> 5"
    }

    onepassword = {
      source = "1Password/onepassword"
      version = "~> 2"
    }
  }
}
