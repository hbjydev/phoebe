locals {
  aps = {
    all = ["office"]
  }

  wlans = {
    mix = {
      network    = "untrusted"
      passphrase = var.mix_passphrase
      proxy_arp  = true
      uapsd      = true
    },

    iot = {
      network    = "iot"
      passphrase = var.iot_passphrase
    },
  }
}

variable "mix_passphrase" {
  type        = string
  description = "The passphrase for the mix WLAN"
  sensitive   = true
}

variable "iot_passphrase" {
  type        = string
  description = "The passphrase for the iot WLAN"
  sensitive   = true
}

resource "unifi_ap_group" "default" {
  name        = "All APs"
  device_macs = [
    for ap in local.aps.all : unifi_device.devices[ap].mac
  ]
}

resource "unifi_client_qos_rate" "wifi" {
  name = "Default"
}

resource "unifi_wlan" "wifi" {
  for_each = local.wlans

  name          = "${each.key}.hayden.wan"
  passphrase_wo = each.value.passphrase
  security      = "wpapsk"

  pmf_mode          = "disabled"
  multicast_enhance = true

  proxy_arp = try(each.value.proxy_arp, false)
  uapsd     = try(each.value.uapsd, false)

  network_id    = unifi_network.networks[each.value.network].id
  ap_group_ids  = [unifi_ap_group.default.id]
  user_group_id = unifi_client_qos_rate.wifi.id

  lifecycle {
    ignore_changes = [bandsteering_mode]
  }
}
