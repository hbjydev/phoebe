terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.0.0"
    }

    onepassword = {
      source  = "1Password/onepassword"
      version = "3.3.1"
    }
  }
}

provider "google" {}
provider "onepassword" {}
