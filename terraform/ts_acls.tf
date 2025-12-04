locals {
  ts_admins = ["hayden@hayden.moe", "haydenuwu@passkey"]

  ts_prefix        = "hm"
  ts_teamgroup     = "tg"
  ts_appgroup      = "ag"
  ts_clustergroup  = "cg"
  ts_exitnodetag   = "en"

  ts_tags = {
    "exitnode-phoebe" = {
      tag = "tag:${local.ts_prefix}-${local.ts_exitnodetag}-phoebe",
      owners = [local.ts_groups["infra"]]
    },
    "cluster-phoebe" = {
      tag = "tag:${local.ts_prefix}-${local.ts_clustergroup}-phoebe",
      owners = [local.ts_groups["eng"]]
    },
    "k8soperator-phoebe" = {
      tag = "tag:${local.ts_prefix}-${local.ts_appgroup}-k8s-operator-phoebe",
      owners = [local.ts_groups["eng"]]
    }
    "k8s-phoebe" = {
      tag = "tag:${local.ts_prefix}-${local.ts_appgroup}-k8s-phoebe",
      owners = ["tag:${local.ts_prefix}-${local.ts_appgroup}-k8s-operator-phoebe"]
    }
    "tsrecorder-phoebe" = {
      tag = "tag:${local.ts_prefix}-${local.ts_appgroup}-tsrecorder",
      owners = [
        local.ts_groups["infra"],
        local.ts_groups["eng"],
        "tag:${local.ts_prefix}-${local.ts_appgroup}-k8s-operator-phoebe"
      ]
    }
  }

  ts_groups = {
    "eng"   = "group:${local.ts_prefix}-${local.ts_teamgroup}-eng",
    "infra" = "group:${local.ts_prefix}-${local.ts_teamgroup}-infra"
  }

  ts_networks = {
    for k, v in local.all_networks : k => {
      allow_from = ["${local.ts_groups["infra"]}"]
      tag = "tag:${local.ts_prefix}-nw-${k}"
      ipset = "ipset:${local.ts_prefix}-nis-${k}"
      cidrs = v.tailscale.cidrs
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

    ipsets: merge({
      for k, v in local.ts_networks : v.ipset => v.cidrs
    }, {
      # Clusters
      "ipset:hm-cis-phoebe": [
        "172.18.0.0/16",  # cluster pods
        "172.19.0.0/16",  # cluster services
      ]
    }),

    grants: concat([
      for k, v in local.ts_networks : {
        src: v.allow_from,
        dst: [v.tag],
        ip:  ["*"]
      }
    ], [
      {
        src: [local.ts_groups["infra"]],
        dst: ["autogroup:internet"],
        via: [local.ts_tags["exitnode-phoebe"].tag],
        ip: ["*"]
      },

      {
        src: [local.ts_groups["infra"]],
        dst: [local.ts_networks["phoebe"].ipset],
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
