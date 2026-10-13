locals {
  zones = {
    internal = {
      networks = ["trunk", "trusted"]
    }

    gateway = {}

    vpn = {}

    hotspot = {}

    dmz = {
      networks = ["servers", "storage"]
    }

    untrusted = {
      networks = ["untrusted", "iot"]
    }

    management = {
      networks = ["mgmt"]
    }
  }
}

resource "unifi_firewall_zone" "zones" {
  for_each = local.zones

  name = title(each.key)
  network_ids = [
    for network in try(each.value.networks, []) : unifi_network.networks[network].id
  ]
}
