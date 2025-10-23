resource "grafana_cloud_stack" "haydenmoe" {
  provider          = grafana.cloud
  name              = "haydenmoe.grafana.net"
  slug              = "haydenmoe"
  region_slug       = "prod-gb-south-1"
}
