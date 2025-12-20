data "cloudflare_api_token_permission_groups_list" "self" {
  provider = cloudflare.tokens
}

locals {
  cf_api_perms = [
    for x in data.cloudflare_api_token_permission_groups_list.self.result : {
      id = x.id
    }
    if contains([
      "Zone Read",
      "DNS Read",
      "DNS Edit",
    ], x.name)
  ]
}

resource "cloudflare_zone" "haydenmoe" {
  account = {
    id = var.CLOUDFLARE_ACCOUNT_ID
  }

  name = "hayden.moe"
}

resource "cloudflare_api_token" "self" {
  name = "tok-phoebe-external-dns"

  policies = [{
    effect = "allow"
    resources = jsonencode({
      "com.cloudflare.api.account.zone.${cloudflare_zone.haydenmoe.id}" = "*"
    })
    permission_groups = local.cf_api_perms
  }]

  provider = cloudflare.tokens
}

resource "onepassword_item" "self" {
  vault = var.PHOEBE_VAULT_ID
  title = "svc-cloudflare"
  tags = ["managed-by/terraform"]
  category = "password"
  password = cloudflare_api_token.self.value
  section {
    label = "meta"
    field {
      label = "zoneId"
      value = cloudflare_zone.haydenmoe.id
    }
  }
}
