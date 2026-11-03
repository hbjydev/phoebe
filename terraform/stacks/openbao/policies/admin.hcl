# Grant full permissions on all paths
path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}
