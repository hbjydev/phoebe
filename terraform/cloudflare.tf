data "cloudflare_account_api_token_permission_groups_list" "self" {
  account_id = var.CLOUDFLARE_ACCOUNT_ID
  provider = cloudflare.tokens
}

locals {
  cf_api_perms = [
    for x in data.cloudflare_account_api_token_permission_groups_list.self.result : {
      id = x.id
    }
    if contains([
      "Zone Read",
      "Zone Write",
      "DNS Read",
      "DNS Write",
    ], x.name)
  ]
}

resource "cloudflare_zone" "haydenmoe" {
  account = {
    id = var.CLOUDFLARE_ACCOUNT_ID
  }

  name = "hayden.moe"
}

resource "cloudflare_zone" "roostmoe" {
  account = {
    id = var.CLOUDFLARE_ACCOUNT_ID
  }

  name = "roost.moe"
}

resource "random_bytes" "cloudflare_tunnel_secret" {
  length = 32
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "cloudflared" {
  account_id    = var.CLOUDFLARE_ACCOUNT_ID
  name          = "ztt-p-phoebe"
  config_src    = "local"
  tunnel_secret = random_bytes.cloudflare_tunnel_secret.base64
}

resource "cloudflare_dns_record" "tunnel_haydenmoe" {
  zone_id = cloudflare_zone.haydenmoe.id
  name = "external.hayden.moe"
  ttl = 1
  type = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.cloudflared.id}.cfargotunnel.com"
  proxied = true
}

resource "cloudflare_account_token" "self" {
  account_id = var.CLOUDFLARE_ACCOUNT_ID
  name = "tok-phoebe-external-dns"

  policies = [
    {
      effect = "allow"
      resources = jsonencode({
        "com.cloudflare.api.account.zone.${cloudflare_zone.haydenmoe.id}" = "*"
        "com.cloudflare.api.account.zone.${cloudflare_zone.roostmoe.id}" = "*"
      })
      permission_groups = local.cf_api_perms
    }
  ]

  provider = cloudflare.tokens
}

resource "onepassword_item" "tunnel" {
  vault = var.PHOEBE_VAULT_ID
  title = "app-cloudflared"
  tags = ["managed-by/terraform"]
  category = "password"

  section {
    label = "config"
    field {
      label = "accountTag"
      value = cloudflare_zero_trust_tunnel_cloudflared.cloudflared.account_tag
    }
    field {
      label = "tunnelId"
      value = cloudflare_zero_trust_tunnel_cloudflared.cloudflared.id
    }
    field {
      label = "tunnelSecret"
      type = "CONCEALED"
      value = random_bytes.cloudflare_tunnel_secret.base64
    }
  }
}

resource "onepassword_item" "self" {
  vault = var.PHOEBE_VAULT_ID
  title = "svc-cloudflare"
  tags = ["managed-by/terraform"]
  category = "password"
  password = cloudflare_account_token.self.value
  section {
    label = "meta"
    field {
      label = "accountId"
      value = var.PHOEBE_VAULT_ID
    }
    field {
      label = "haydenmoeZoneId"
      value = cloudflare_zone.haydenmoe.id
    }
    field {
      label = "roostmoeZoneId"
      value = cloudflare_zone.roostmoe.id
    }
  }
}
