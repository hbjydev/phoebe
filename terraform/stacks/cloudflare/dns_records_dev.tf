locals {
  dev_domain  = var.domains["dev"].domain
  dev_zone_id = var.domains["dev"].zone_id

  dev_records = {}
}

resource "cloudflare_dns_record" "dev_records" {
  for_each = local.dev_records

  proxied = false
  ttl     = 1
  zone_id = local.dev_zone_id
  comment = "Managed by Terraform -- hayden/phoebe/terraform/stacks/cloudflare"

  name    = each.key == "." ? local.dev_domain : "${each.key}.${local.dev_domain}"
  type    = each.value.kind
  content = each.value.kind == "A" ? each.value.value : "${each.value.value}.${local.dev_domain}"
}

module "dev_gsuite" {
  source = "./modules/gsuite"

  domain     = local.dev_domain
  dkim_value = var.domains["dev"].dkim_value
  zone_id    = local.dev_zone_id
}
