locals {
  buckets = {
    "hbjydev-phoebe-volsync" = {},
    "hbjydev-phoebe-tsrecorder" = {},
    "drive-haydenmoe-storage" = {},
    "sso-haydenmoe-storage" = {},
  }

  virtual_machines = {
    "dione-authentik" = {
      plan = "2xCPU-2GB",
      backup = "daily",
      network = "public",
    },
  }
}
