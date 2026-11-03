ui       = true
api_addr = "https://openbao.hayden.moe"

storage "pebbledb" {
  path = "/openbao/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "true"
}
