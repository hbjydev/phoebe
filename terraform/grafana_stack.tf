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

resource "vault_kv_secret_v2" "self_token" {
  mount     = vault_mount.phoebe.path
  name      = "grafana-cloud"
  data_json = jsonencode({
    token    = grafana_cloud_access_policy_token.phoebe.token
    stackId = grafana_cloud_stack.haydenmoe.id

    mimirUrl    = grafana_cloud_stack.haydenmoe.prometheus_remote_write_endpoint
    mimirUserId = grafana_cloud_stack.haydenmoe.prometheus_user_id

    lokiUrl    = "${grafana_cloud_stack.haydenmoe.logs_url}/loki/api/v1/push"
    lokiUserId = grafana_cloud_stack.haydenmoe.logs_user_id

    otlpUrl    = "${grafana_cloud_stack.haydenmoe.otlp_url}/otlp"
  })

  custom_metadata {
    data = { managed-by = "terraform" }
  }
}
