locals {
  grafana_slug     = "haydenmoe"
  grafana_hostname = "grafana.hayden.moe"
  grafana_region   = "prod-gb-south-1"
}

resource "grafana_cloud_stack" "haydenmoe" {
  provider    = grafana.cloud
  name        = "hayden.moe"
  slug        = local.grafana_slug
  region_slug = local.grafana_region
  url         = "https://${local.grafana_hostname}"
  labels      = { managed-by = "terraform" }
  depends_on  = [cloudflare_dns_record.grafana_haydenmoe]
}

resource "cloudflare_dns_record" "grafana_haydenmoe" {
  zone_id = cloudflare_zone.haydenmoe.id
  name    = local.grafana_hostname
  ttl     = 3600
  type    = "CNAME"
  content = "${local.grafana_slug}.grafana.net"
  proxied = false
}

resource "grafana_cloud_access_policy" "phoebe" {
  region       = local.grafana_region
  name         = "sa-phoebe-k8s"
  display_name = "Phoebe Kubernetes"
  scopes       = ["metrics:read", "logs:write", "metrics:write", "traces:write", "profiles:write", "fleet-management:read"]

  realm {
    type       = "stack"
    identifier = grafana_cloud_stack.haydenmoe.id
    label_policy {
      selector = "{cluster=\"phoebe\"}"
    }
  }
}

resource "grafana_cloud_access_policy_token" "phoebe" {
  region           = local.grafana_region
  access_policy_id = grafana_cloud_access_policy.phoebe.policy_id
  name             = "sat-phoebe-k8s"
  display_name     = "Phoebe Kubernetes"
}
