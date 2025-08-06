resource "tailscale_tailnet_key" "self" {
  reusable = false
  ephemeral = false
  tags = ["tag:net-dione"]
  expiry = 3600
}

resource "upcloud_server" "self" {
  hostname = "${var.name}.hayden.moe"
  zone     = var.zone
  plan     = var.plan
  firewall = true

  labels = {
    "moe.hayden.source" = "github/hbjydev/phoebe",
    "moe.hayden.network" = "dione",
  }

  metadata  = true
  user_data = templatefile(
    "${path.module}/userdata.yaml",
    {
      ts_auth_key = tailscale_tailnet_key.self.key
    }
  )


  template {
    storage = "Rocky Linux 10"
    size    = 25
    backup_rule {
      interval  = "daily"
      time      = "0100"
      retention = 3
    }
  }

  network_interface {
    type = "public"
  }

  login {
    user = "rocky"
    keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDkhuhfzyg7R+O62XSktHufGmmhy6FNDi/NuPPJt7bI+", # ssh-personal
    ]
  }
}
