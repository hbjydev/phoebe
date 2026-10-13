locals {
  zones = {
    internal = { networks = ["trunk", "trusted"] }
    gateway = {}
    vpn = {}
    hotspot = {}
    dmz = { networks = ["servers", "storage"] }
    untrusted = { networks = ["untrusted", "iot"] }
    management = { networks = ["mgmt"] }
  }

  rules = [
    # 1xxx: Base Ruleset
    {
      idx         = 1000
      name        = "Allow management traffic"
      source_zone = "internal"
      dest_zone   = "management"
    },
    {
      idx         = 1100
      name        = "Allow local communication"
      source_zone = "management"
      dest_zone   = "management"
    },

    # 2xxx: Inter-VLAN Policies
    {
      idx         = 2000
      name        = "Allow traffic to IoT"
      source_zone = "dmz"
      dest_zone   = "untrusted"
      dest_net    = "iot"
    },
    {
      idx         = 2100
      name        = "Allow untrusted WLAN clients traffic to IoT"
      source_zone = "untrusted"
      source_net  = "untrusted"
      dest_zone   = "untrusted"
      dest_net    = "iot"
    },
    {
      idx         = 2200
      name        = "Allow traffic to IoT"
      source_zone = "internal"
      dest_zone   = "untrusted"
      dest_net    = "iot"
    },
  ]
}

resource "unifi_firewall_zone" "zones" {
  for_each = local.zones

  name = title(each.key)
  network_ids = [
    for network in try(each.value.networks, []) : unifi_network.networks[network].id
  ]
}

resource "unifi_firewall_policy" "policies" {
  for_each = { for rule in local.rules : rule.idx => rule }

  name                 = "[${each.value.idx}][${upper(substr(each.value.source_zone, 0, 3))}] ${each.value.name}"
  description          = "Managed by Terraform"
  enabled              = try(each.value.enabled, true)
  action               = try(each.value.action, "ALLOW")
  protocol             = try(each.value.protocol, "all")
  logging              = try(each.value.logging, true)
  create_allow_respond = try(each.value.allow_return, true)

  source = {
    zone_id         = unifi_firewall_zone.zones[each.value.source_zone].id
    matching_target = can(each.value.source_net) ? "NETWORK" : "ANY"
    network_ids     = can(each.value.source_net) ? [unifi_network.networks[each.value.source_net].id] : null
  }

  destination = {
    zone_id         = unifi_firewall_zone.zones[each.value.dest_zone].id
    matching_target = can(each.value.dest_net) ? "NETWORK" : "ANY"
    network_ids     = can(each.value.dest_net) ? [unifi_network.networks[each.value.dest_net].id] : null
  }
}
