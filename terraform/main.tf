module "bucket" {
  source   = "./modules/storage_bucket"
  for_each = merge(local.apps_buckets, local.buckets)

  name          = try(each.value.name, each.key)
  account_id    = "09c8f0e370aa6c96c9b46741f994d5f5"
  storage_class = try(each.value.storage_class, "Standard")
  region        = try(each.value.region, "WEUR")
  op_title      = null

  providers = {
    cloudflare.main = cloudflare
    cloudflare.tokens = cloudflare.tokens
  }
}

module "vm_upcloud" {
  source   = "./modules/vm_upcloud"
  for_each = local.instances_upcloud

  name      = try(each.value.name, each.key)
  zone      = try(each.value.zone, "uk-lon1")
  plan      = try(each.value.plan, "1xCPU-1GB")
  network   = try(each.value.network, "UNKNOWN")
  tailscale = try(each.value.tailscale, true)
  volumes   = try(each.value.volumes, [])
}
