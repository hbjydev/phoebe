resource "vault_pki_secret_backend_root_cert" "root" {
  depends_on = [vault_mount.root]
  backend    = vault_mount.root.path

  type                 = "internal"
  common_name          = "${var.ca_tree_name_prefix} R1"
  issuer_name          = "${var.ca_tree_issuer_prefix}-r1"
  ttl                  = "315360000"
  format               = "pem"
  private_key_format   = "pkcs8"
  key_type             = "ed25519"
  key_bits             = 0
  exclude_cn_from_sans = true
  max_path_length      = 1

  ou           = "Engineering"
  organization = "Hayden.moe"
}
