resource "vault_mount" "root" {
  path        = "ca/${var.path}/root"
  type        = "pki"
  description = "Root Certificate Authority for ${var.ca_tree_name_prefix}"

  default_lease_ttl_seconds = 3600
  max_lease_ttl_seconds     = 315360000
}

resource "vault_pki_secret_backend_config_cluster" "root" {
  backend  = vault_mount.root.path
  path     = "https://openbao.hayden.moe/v1/${vault_mount.root.path}"
  aia_path = "https://openbao.hayden.moe/v1/${vault_mount.root.path}"
}

resource "vault_pki_secret_backend_config_urls" "root" {
  depends_on              = [vault_pki_secret_backend_config_cluster.root]
  backend                 = vault_mount.root.path
  enable_templating       = true
  issuing_certificates    = ["{{cluster_aia_path}}/issuer/{{issuer_id}}/der"]
  crl_distribution_points = ["{{cluster_aia_path}}/issuer/{{issuer_id}}/crl/der"]
}

resource "vault_pki_secret_backend_config_issuers" "root" {
  backend                       = vault_mount.root.path
  default                       = vault_pki_secret_backend_root_cert.root.issuer_id
  default_follows_latest_issuer = false
}

resource "vault_mount" "self" {
  for_each = var.intermediates

  path        = "ca/${var.path}/int/${each.key}"
  type        = "pki"
  description = "Intermediate Certificate Authority for ${var.ca_tree_name_prefix}"

  default_lease_ttl_seconds = 3600
  max_lease_ttl_seconds     = 315360000
}

resource "vault_pki_secret_backend_config_cluster" "self" {
  for_each = var.intermediates

  backend  = vault_mount.self[each.key].path
  path     = "https://openbao.hayden.moe/v1/${vault_mount.self[each.key].path}"
  aia_path = "https://openbao.hayden.moe/v1/${vault_mount.self[each.key].path}"
}

resource "vault_pki_secret_backend_config_urls" "self" {
  for_each   = var.intermediates
  depends_on = [vault_pki_secret_backend_config_cluster.self]

  backend                 = vault_mount.self[each.key].path
  enable_templating       = true
  issuing_certificates    = ["{{cluster_aia_path}}/issuer/{{issuer_id}}/der"]
  crl_distribution_points = ["{{cluster_aia_path}}/issuer/{{issuer_id}}/crl/der"]
}

resource "vault_pki_secret_backend_config_issuers" "self" {
  for_each = var.intermediates

  backend                       = vault_mount.self[each.key].path
  default                       = vault_pki_secret_backend_issuer.intermediate[each.key].issuer_id
  default_follows_latest_issuer = false
}
