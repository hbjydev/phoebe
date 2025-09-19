resource "upcloud_managed_object_storage" "dione" {
  name              = "${local.resource_prefix}-dione-os"
  region            = "europe-1"
  configured_status = "started"

  labels = {
    "moe.hayden.source" = "github/hbjydev/phoebe",
    "moe.hayden.network" = "dione",
  }
}

module "bucket_upcloud" {
  source   = "./modules/bucket_upcloud"
  for_each = merge(local.apps_buckets, local.buckets)

  name          = try(each.value.name, each.key)
  storage_uuid  = upcloud_managed_object_storage.dione.id
  op_title      = try(each.value.name, "uc-os-${try(each.value.name, each.key)}")
  op_vault      = var.PHOEBE_VAULT_ID
}

moved {
  from = module.bucket
  to = module.bucket_cloudflare
}

module "bucket_cloudflare" {
  source   = "./modules/storage_bucket"
  for_each = merge(local.apps_buckets, local.buckets)

  name          = try(each.value.name, each.key)
  account_id    = "09c8f0e370aa6c96c9b46741f994d5f5"
  storage_class = try(each.value.storage_class, "Standard")
  region        = try(each.value.region, "WEUR")
  op_title      = try(each.value.name, "cf-r2-${try(each.value.name, each.key)}")
  op_vault      = var.PHOEBE_VAULT_ID

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
