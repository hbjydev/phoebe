terraform {
  backend "s3" {
    bucket = "haydenmoe-iac"
    key    = "phoebe.tfstate"
    region = "auto"

    # CF R2 compatibility
    use_lockfile                = true
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}
