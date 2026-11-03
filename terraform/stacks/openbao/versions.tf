terraform {
  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "5.13.0"
    }
  }
}

provider "vault" {}
