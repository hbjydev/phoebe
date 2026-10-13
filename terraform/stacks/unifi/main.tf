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

  name    = each.value.name
  vlan    = each.value.vlan
  subnet  = each.value.subnet

  dhcp_server = {
    boot = {
      enabled = false
    }
    start   = each.value.dhcp_start
    stop    = each.value.dhcp_end
  }
}
