terraform {
  required_providers {
    proxmox = {
      source = "bpg/proxmox"
      version = "0.78.0"
    }
  }
}

provider "proxmox" {
  endpoint = "https://hy-net-vm-01.tail92a40f.ts.net:8006/"
  ssh {
    agent = true
  }
}
