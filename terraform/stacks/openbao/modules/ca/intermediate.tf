resource "vault_pki_secret_backend_intermediate_cert_request" "intermediate" {
  for_each    = var.intermediates
  depends_on  = [vault_mount.self]
  backend     = vault_mount.self[each.key].path

  type                 = "internal"
  common_name          = ""
  format               = "pem"
  private_key_format   = "pkcs8"
  key_type             = "ed25519"
  key_bits             = 0
  exclude_cn_from_sans = true

  ou           = "Engineering"
  organization = "Hayden.moe"
}

resource "vault_pki_secret_backend_root_sign_intermediate" "intermediate" {
  for_each   = var.intermediates
  depends_on = [vault_pki_secret_backend_config_urls.root]
  backend    = vault_mount.root.path

  csr                   = vault_pki_secret_backend_intermediate_cert_request.intermediate[each.key].csr
  common_name           = "${each.value.common_name}"
  ttl                   = "63113904"
  format                = "pem"
  exclude_cn_from_sans  = true
  issuer_ref            = vault_pki_secret_backend_root_cert.root.issuer_id
  max_path_length       = 0
  permitted_dns_domains = each.value.allowed_domains

  ou                   = "Engineering"
  organization         = "hayden.moe"
}

resource "vault_generic_endpoint" "intermediate_import" {
  for_each = var.intermediates

  path = "${vault_mount.self[each.key].path}/intermediate/set-signed"

  disable_read   = true
  disable_delete = true
  write_fields   = ["mapping"]

  data_json = jsonencode({
    certificate = vault_pki_secret_backend_root_sign_intermediate.intermediate[each.key].certificate_bundle
  })
}


resource "vault_pki_secret_backend_issuer" "intermediate" {
  for_each = var.intermediates

  backend     = vault_mount.self[each.key].path
  issuer_name = "${var.ca_tree_issuer_prefix}-${each.key}"

  issuer_ref = one([
    for issuer_id, key_id in jsondecode(
      vault_generic_endpoint.intermediate_import[each.key].write_data_json
    ).mapping : issuer_id
    if key_id == vault_pki_secret_backend_intermediate_cert_request.intermediate[each.key].key_id
  ])
}
