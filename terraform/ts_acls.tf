locals {
  ts_admins = ["hayden@hayden.moe", "haydenuwu@passkey"]

  ts_prefix        = "hm"
  ts_teamgroup     = "tg"
  ts_appgroup      = "ag"
  ts_clustergroup  = "cg"

  ts_tags = {
    "cluster-phoebe" = {
      tag = "tag:${local.ts_prefix}-${local.ts_clustergroup}-phoebe",
      owners = [local.ts_groups["eng"]]
    },
  }

  ts_groups = {
    "eng"   = "group:${local.ts_prefix}-${local.ts_teamgroup}-eng",
    "infra" = "group:${local.ts_prefix}-${local.ts_teamgroup}-infra"
  }

  ts_networks = {
    for k, v in local.networks : k => {
      allow_from = ["${local.ts_groups["infra"]}"]
      tag = "tag:${local.ts_prefix}-nw-${k}"
    }
  }
}

resource "tailscale_acl" "self" {
  overwrite_existing_content = true
  acl = jsonencode({
    groups: {
      "${local.ts_groups["eng"]}": local.ts_admins,
      "${local.ts_groups["infra"]}": local.ts_admins,
    },

    ipsets: {
      # Clusters
      "ipset:hm-cis-phoebe": [
        "172.18.0.0/16",  # cluster pods
        "172.19.0.0/16",  # cluster services
      ],

      # Networks
      "ipset:hm-nis-phoebe": [
        "192.168.0.0/21",   # 1  - trunk vlan
        "192.168.20.0/24",  # 20 - iot vlan
        "192.168.40.0/24",  # 40 - trusted vlan
        "192.168.50.0/24",  # 50 - untrusted vlan
        "10.60.0.0/24",     # 60 - storage vlan
        "10.70.0.0/24",     # 70 - servers vlan
        "10.80.0.0/24",     # 80 - load balancing, non-vlan
        "10.90.0.0/24",     # 90 - privacy vpn vlan
        "10.99.0.0/24",     # 99 - management vlan
      ],
    },

    grants: concat([
      for k, v in local.ts_networks : {
        src: v.allow_from,
        dst: [v.tag],
        ip:  ["*"]
      }
    ], [
      {
        src: [local.ts_groups["infra"]],
        dst: ["ipset:hm-nis-phoebe"],
        ip: ["*"]
      },

      {
        src: [local.ts_groups["eng"]],
        dst: ["ipset:hm-cis-phoebe"],
        ip: ["*"]
      },

      {
        src: [local.ts_groups["eng"]],
        dst: [local.ts_tags["cluster-phoebe"].tag],
        app: {
          "tailscale.com/cap/kubernetes": [{
            "impersonate": {
              "groups": ["system:masters"],
            },
          }],
        },
      },
    ]),

    ssh: [
      for k, v in local.ts_networks : {
        action: "accept", # todo: check
        src:    v.allow_from,
        dst:    [v.tag],
        users:  ["root", "autogroup:nonroot"],
        # todo: recorder & enforceRecorder
      }
    ],

    tagowners: merge({
      for k, v in local.ts_networks : v.tag => [local.ts_groups["infra"]]
    }, {
      for k, v in local.ts_tags : v.tag => v.owners
    })
  })
}
