locals {
  # Manually configured resources
  manual_buckets = {
    "hbjydev-phoebe-volsync" = {},
    "hbjydev-phoebe-tsrecorder" = {},
    "drive-haydenmoe-storage" = {},
    "sso-haydenmoe-storage" = {},
  }
  manual_instances = {}

  # Automatically configured resources
  resource_prefix = "haydenmoe"
  apps = yamldecode(file("./apps.yaml"))["apps"]

  apps_buckets = merge([
    for ak, app in local.apps : {
      for bk, bucket in app.buckets : "${local.resource_prefix}-${ak}-${bk}" => {
        provider = try(bucket.provider, app.provider),
        storage_class = try(bucket.storage_class, "Standard"),
        region = try(bucket.region, "WEUR"),
      }
    }
  ]...)

  apps_instances = {
    for ak, app in local.apps : ak => {
      provider = try(app.instance.provider, try(app.provider, "upcloud"))
      name = "${app.network}-${ak}"
      network = app.network
      tailscale = try(app.tailscale, true)
      plan = try(app.instance.plan, "1xCPU-1GB")
      zone = try(app.instance.region, try(app.region, app.provider == "upcloud" ? "uk-lon1" : "FR-PAR1"))
      volumes = try(app.instance.volumes, [])
    }
    if try(app.instance.enabled, false) == true
  }

  instances = merge(local.apps_instances, local.manual_instances)
  instances_upcloud = {
    for ik, instance in local.instances : ik => instance
    if instance.provider == "upcloud"
  }
  instances_scw = {
    for ik, instance in local.instances : ik => instance
    if instance.provider == "scaleway"
  }

  buckets = merge(local.apps_buckets, local.manual_buckets)
  buckets_cloudflare = {
    for bk, bucket in local.buckets : bk => bucket
    if try(bucket.provider, "cloudflare") == "cloudflare"
  }
  buckets_upcloud = {
    for bk, bucket in local.buckets : bk => bucket
    if try(bucket.provider, "cloudflare") == "upcloud"
  }
}
