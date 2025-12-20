module "network_upcloud" {
  source   = "./modules/network_upcloud"
  for_each = local.networks_upcloud

  name               = each.value.name
  zone               = each.value.region
  address_range_cidr = each.value.address_range_cidr
  has_object_storage = each.value.has_object_storage
}

module "bucket_upcloud" {
  source   = "./modules/bucket_upcloud"
  for_each = local.buckets_upcloud

  name                     = try(each.value.name, each.key)
  storage_uuid             = module.network_upcloud[each.value.network].network_object_storage_id
  storage_endpoint_private = module.network_upcloud[each.value.network].network_object_storage_private_endpoint
  storage_endpoint_public  = module.network_upcloud[each.value.network].network_object_storage_public_endpoint
  restic                   = each.value.restic
  op_vault_id              = var.PHOEBE_VAULT_ID
}

module "bucket_cloudflare" {
  source   = "./modules/bucket_cloudflare"
  for_each = local.buckets_cloudflare

  name          = try(each.value.name, each.key)
  account_id    = "09c8f0e370aa6c96c9b46741f994d5f5"
  storage_class = try(each.value.storage_class, "Standard")
  region        = try(each.value.region, "WEUR")
  restic        = each.value.restic
  op_vault_id   = var.PHOEBE_VAULT_ID

  providers = {
    cloudflare.main = cloudflare
    cloudflare.tokens = cloudflare.tokens
  }
}

module "vm_upcloud" {
  source   = "./modules/vm_upcloud"
  for_each = local.instances_upcloud

  name       = try(each.value.name, each.key)
  zone       = try(each.value.zone, "uk-lon1")
  plan       = try(each.value.plan, "1xCPU-1GB")
  network    = try(each.value.network, "UNKNOWN")
  network_id = module.network_upcloud[each.value.network].network_id
  tailscale  = try(each.value.tailscale, true)
  volumes    = try(each.value.volumes, [])
}
