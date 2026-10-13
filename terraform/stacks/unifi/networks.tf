locals {
  networks = {
    trunk = {
      infra = false
    }

    iot = {
      vlan_id = 20
      infra = false
    }

    trusted = {
      vlan_id = 40
      infra = false
    }

    untrusted = {
      vlan_id = 50
      infra = false
    }

    storage = {
      vlan_id = 60
      infra = true
    }

    servers = {
      vlan_id = 70
      infra = true
    }

    vpn = {
      vlan_id = 90
      infra = true
    }

    mgmt = {
      vlan_id = 99
      infra = true
    }
  }

  all_networks = {
    for name, v in local.networks : name => {
      name   = "phoebe-v-${name}"
      vlan   = try(v.vlan_id, null)

      subnet     = v.infra ? "10.${try(v.vlan_id, 4)}.0.1/${can(v.vlan_id) ? "24" : "23"}" : "192.168.${try(v.vlan_id, 4)}.1/${can(v.vlan_id) ? "24" : "23"}"
      dhcp_start = v.infra ? "10.${try(v.vlan_id, 4)}.0.${can(v.vlan_id) ? "6" : "11"}"    : "192.168.${try(v.vlan_id, 4)}.${can(v.vlan_id) ? "6" : "11"}"
      dhcp_end   = v.infra ? "10.${try(v.vlan_id, 5)}.0.254"  : "192.168.${try(v.vlan_id, 5)}.254"
    }
  }
}

resource "unifi_network" "networks" {
  for_each = local.all_networks

  vlan    = each.value.vlan

  dhcp_v6_server      = null
  enabled             = true
  gateway_type        = "default"
  igmp_snooping       = false
  internet_access     = true
  lte_lan             = true
  multicast_dns       = true
  name                = each.value.name
  network_isolation   = false
  purpose             = "corporate"
  setting_preference  = each.key == "trunk" ? "auto" : "manual"
  site                = "default"
  subnet              = each.value.subnet
  third_party_gateway = false

  ipv6_aliases                   = null
  ipv6_client_address_assignment = "slaac"
  ipv6_interface_type            = "none"
  ipv6_pd_auto_prefixid_enabled  = true
  ipv6_pd_interface              = null
  ipv6_pd_prefixid               = null
  ipv6_pd_start                  = "::2"
  ipv6_pd_stop                   = "::7d1"
  ipv6_ra                        = true
  ipv6_ra_preferred_lifetime     = "4h0m0s"
  ipv6_ra_priority               = "high"
  ipv6_ra_valid_lifetime         = null
  ipv6_static_subnet             = null

  dhcp_server = {
    boot = {
      enabled = false
    }
    start   = each.value.dhcp_start
    stop    = each.value.dhcp_end
  }
}
