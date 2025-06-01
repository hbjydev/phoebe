terraform {
  backend "s3" {
    bucket       = "hbjydev-tf-state"    
    key          = "gitops-tofu-onprem"
    region       = "eu-west-2"
    use_lockfile = true
  }
}
