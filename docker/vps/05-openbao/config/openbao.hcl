ui = true

api_addr     = "https://openbao.hayden.moe"
cluster_addr = "https://127.0.0.1:8201"
cluster_name = "phoebe"

storage "pebbledb" {
  path = "/openbao/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "true"
}
