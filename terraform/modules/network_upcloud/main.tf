resource "upcloud_router" "self" {
  name = "${var.name}-rt"
  labels = {
    "moe.hayden.source" = "github/hbjydev/phoebe",
    "moe.hayden.network" = var.name,
  }
}

resource "upcloud_network" "self" {
  name   = "${var.name}-net"
  router = upcloud_router.self.id
  zone   = var.zone

  labels = {
    "moe.hayden.source" = "github/hbjydev/phoebe",
    "moe.hayden.network" = var.name,
  }

  ip_network {
    dhcp    = true
    family  = "IPv4"
    address = var.address_range_cidr
  }
}

resource "upcloud_managed_object_storage" "self" {
  count = var.has_object_storage ? 1 : 0

  name              = "${var.name}-os"
  region            = "europe-1"
  configured_status = "started"

  network {
    family = "IPv4"
    type   = "private"
    name   = "internal-net"
    uuid   = upcloud_network.self.id
  }

  network {
    family = "IPv4"
    type   = "public"
    name   = "public-net"
  }

  labels = {
    "moe.hayden.source" = "github/hbjydev/phoebe",
    "moe.hayden.network" = var.name,
  }
}
