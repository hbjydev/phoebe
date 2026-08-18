terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.45.0"
    }

    onepassword = {
      source  = "1Password/onepassword"
      version = "3.3.1"
    }
  }
}

provider "google" {}
provider "onepassword" {}
