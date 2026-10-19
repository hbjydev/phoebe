locals {
  comment = "[GS] Managed by Terraform -- hayden/phoebe/terraform/stacks/cloudflare/modules/gsuite"

  mx_records = [
    { priority = 1, content = "aspmx.l.google.com" },
    { priority = 5, content = "alt1.aspmx.l.google.com" },
    { priority = 5, content = "alt2.aspmx.l.google.com" },
    { priority = 10, content = "alt3.aspmx.l.google.com" },
    { priority = 10, content = "alt4.aspmx.l.google.com" }
  ]
}

resource "cloudflare_dns_record" "mx" {
  for_each = { for record in local.mx_records : "${record.priority}-${record.content}" => record }

  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name = var.domain
  type = "MX"

  content = each.value.content
  priority = each.value.priority
}

resource "cloudflare_dns_record" "spf" {
  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name    = var.domain
  type    = "TXT"
  content = "\"v=spf1 include:_spf.google.com ~all\""
}

resource "cloudflare_dns_record" "dkim" {
  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name    = "google._domainkey.${var.domain}"
  type    = "TXT"
  content = "\"${var.dkim_value}\""

  lifecycle {
    ignore_changes = [content]
  }
}

resource "cloudflare_dns_record" "dmarc" {
  proxied = false
  ttl     = 1
  zone_id = var.zone_id
  comment = local.comment

  name    = "_dmarc.${var.domain}"
  type    = "TXT"
  content = "\"v=DMARC1; p=quarantine;\""
}
