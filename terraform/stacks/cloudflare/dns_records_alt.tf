locals {
  alt_domain  = var.domains["alt"].domain
  alt_zone_id = var.domains["alt"].zone_id

  alt_records = {}
}

resource "cloudflare_dns_record" "alt_records" {
  for_each = local.alt_records

  proxied = false
  ttl     = 1
  zone_id = local.alt_zone_id
  comment = "Managed by Terraform -- hayden/phoebe/terraform/stacks/cloudflare"

  name    = each.key == "." ? local.alt_domain : "${each.key}.${local.alt_domain}"
  type    = each.value.kind
  content = each.value.kind == "A" ? each.value.value : "${each.value.value}.${local.alt_domain}"
}

module "alt_fastmail" {
  source = "./modules/fastmail"

  domain  = local.alt_domain
  zone_id = local.alt_zone_id
}
