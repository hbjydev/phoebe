locals {
  # Manually configured resources
  manual_buckets = {}
  manual_instances = {}

  # Automatically configured resources
  resource_prefix = "haydenmoe"
  networks = yamldecode(file("./config/networks.yaml"))
  apps = yamldecode(file("./config/apps.yaml"))

  all_networks = merge({
    for nk, network in local.networks : nk => {
      name = "${local.resource_prefix}-${nk}",
      provider = try(network.provider, "upcloud"),
      region = try(
        network.region,
        network.provider == "upcloud"
          ? "uk-lon1"
          : network.provider == "cloudflare"
            ? "WEUR"
            : "none"
      ),
      address_range_cidr = try(network.cidr, "10.0.0.0/16"),
      tailscale = {
        cidrs = try(network.tailscale.cidrs, [try(network.cidr, "10.0.0.0/16")])
      },
    }
  })

  networks_upcloud = {
    for nk, network in local.all_networks : nk => merge(network, {
      has_object_storage = can(local.networks[nk].upcloud) ? try(local.networks[nk].upcloud.objectStorage, false) : false
    })
    if network.provider == "upcloud"
  }

  networks_none = {
    for nk, network in local.all_networks : nk => network
    if network.provider == "none"
  }

  network_object_storages = {
    for nw, network in local.all_networks : nw => {
      name = "${local.resource_prefix}-${nw}-os"
    }
    if network.provider == "upcloud"
  }

  apps_buckets = merge([
    for ak, app in local.apps : {
      for bk, bucket in app.buckets : "${local.resource_prefix}-${ak}-${bk}" => {
        provider = try(
          bucket.provider,
          try(app.provider, local.all_networks[app.network].provider)
        ),
        network = try(app.network, "dione")
        restic = try(bucket.restic, false)
        storage_class = try(bucket.storage_class, "Standard"),
        region = try(
          bucket.region,
          try(app.region, local.all_networks[app.network].region)
        ),
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
