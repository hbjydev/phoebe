terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.9.0"
    }

    onepassword = {
      source  = "1Password/onepassword"
      version = "3.4.1"
    }
  }
}

provider "google" {}
provider "onepassword" {}
