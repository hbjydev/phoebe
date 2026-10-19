locals {
  devices = {
    utility = {
      mac = "1c:6a:1b:18:35:9b"
      type = "gateway"
    },

    core = {
      mac = "0c:ea:14:f2:15:f1"
      type = "switch"
    },

    desk = {
      mac = "f4:e2:c6:67:fd:76"
      type = "switch"
    },

    office = {
      mac = "9c:05:d6:37:19:4d"
      type = "access point"
    },
  }

  types = {
    "gateway"      = "gw"
    "switch"       = "sw"
    "access point" = "ap"
  }
}

resource "unifi_device" "devices" {
  for_each = local.devices

  name              = "phoebe-${local.types[each.value.type]}-${each.key}"
  mac               = each.value.mac
  allow_adoption    = true
  forget_on_destroy = false

  bandsteering_mode = each.value.type == "access point" ? "prefer_5g" : null
}
