locals {
  comment = "[FM] Managed by Terraform -- hayden/phoebe/terraform/stacks/cloudflare/modules/fastmail"
}

resource "cloudflare_dns_record" "mx" {
  count = 2

  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name = var.domain
  type = "MX"

  content = "in${count.index + 1}-smtp.messagingengine.com"
  priority = (count.index + 1) * 10
}

resource "cloudflare_dns_record" "spf" {
  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name    = var.domain
  type    = "TXT"
  content = "\"v=spf1 include:spf.messagingengine.com ?all\""
}

resource "cloudflare_dns_record" "dkim" {
  for_each = toset([for i in range(1, 4) : "fm${i}"])

  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name    = "${each.key}._domainkey.${var.domain}"
  type    = "CNAME"
  content = "${each.key}.${var.domain}.dkim.fmhosted.com"
}

resource "cloudflare_dns_record" "dmarc" {
  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name    = "_dmarc.${var.domain}"
  type    = "TXT"
  content = "\"v=DMARC1; p=none;\""
}
