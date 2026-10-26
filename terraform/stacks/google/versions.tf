terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.8.1"
    }

    onepassword = {
      source  = "1Password/onepassword"
      version = "3.4.0"
    }
  }
}

provider "google" {}
provider "onepassword" {}
