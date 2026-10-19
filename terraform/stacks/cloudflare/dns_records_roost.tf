locals {
  roost_domain  = var.domains["roost"].domain
  roost_zone_id = var.domains["roost"].zone_id

  roost_records = {}
}

resource "cloudflare_dns_record" "roost_records" {
  for_each = local.roost_records

  proxied = false
  ttl     = 1
  zone_id = local.roost_zone_id
  comment = "Managed by Terraform -- hayden/phoebe/terraform/stacks/cloudflare"

  name    = each.key == "." ? local.roost_domain : "${each.key}.${local.roost_domain}"
  type    = each.value.kind
  content = each.value.kind == "A" ? each.value.value : "${each.value.value}.${local.roost_domain}"
}

module "roost_gsuite" {
  source = "./modules/gsuite"

  domain     = local.roost_domain
  dkim_value = var.domains["roost"].dkim_value
  zone_id    = local.roost_zone_id
}
