locals {
  moe_domain  = var.domains["moe"].domain
  moe_zone_id = var.domains["moe"].zone_id

  moe_records = {
    # general
    "."             = { kind = "A",     value = "46.62.132.125" }

    # megahost infra
    "megahost"      = { kind = "A",     value = "46.62.132.125" }
    "doco-cd"       = { kind = "CNAME", value = "megahost" }

    # towonel
    "towonel"       = { kind = "CNAME", value = "megahost" }
    "relay.towonel" = { kind = "CNAME", value = "towonel" }
    "external"      = { kind = "CNAME", value = "towonel" }
  }
}

resource "cloudflare_dns_record" "moe_records" {
  for_each = local.moe_records

  proxied = false
  ttl     = 1
  zone_id = local.moe_zone_id
  comment = "Managed by Terraform -- hayden/phoebe/terraform/stacks/cloudflare"

  name    = each.key == "." ? local.moe_domain : "${each.key}.${local.moe_domain}"
  type    = each.value.kind
  content = each.value.kind == "A" ? each.value.value : "${each.value.value}.${local.moe_domain}"
}

module "moe_fastmail" {
  source = "./modules/fastmail"

  domain  = local.moe_domain
  zone_id = local.moe_zone_id
}
