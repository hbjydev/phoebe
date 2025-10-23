resource "grafana_cloud_stack" "haydenmoe" {
  provider          = grafana.cloud
  name              = "hayden.moe"
  slug              = "haydenmoe"
  region_slug       = "uk"
  delete_protection = true
}
