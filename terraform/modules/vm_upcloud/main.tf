resource "tailscale_tailnet_key" "self" {
  count = var.tailscale ? 1 : 0
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
  user_data = var.tailscale ? templatefile(
    "${path.module}/userdata.yaml",
    {
      ts_auth_key = tailscale_tailnet_key.self[0].key
    }
  ) : ""

  template {
    storage = "Rocky Linux 10"
    size    = 30
    tier    = "standard"
    backup_rule {
      interval  = "daily"
      time      = "0100"
      retention = 3
    }
  }

  network_interface {
    type = "public"
  }

  network_interface {
    type    = "private"
    network = var.network_id
  }

  login {
    user = "rocky"
    keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDkhuhfzyg7R+O62XSktHufGmmhy6FNDi/NuPPJt7bI+", # ssh-personal
    ]
  }

  dynamic "storage_devices" {
    for_each = upcloud_storage.extra_volume
    iterator = vol
    content {
      storage = vol.value.id
    }
  }

  lifecycle {
    ignore_changes = [
      user_data,
    ]
  }
}

resource "upcloud_storage" "extra_volume" {
  for_each = { for volume in var.volumes : "${volume.name}" => volume }

  size  = try(each.value.size, 5)
  tier  = "standard"  # only available tier currently
  title = "${var.name}-vol-${each.key}"
  zone  = var.zone
}
