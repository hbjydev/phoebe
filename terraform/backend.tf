terraform {
  backend "gcs" {
    bucket = "bkt-b-terraform-state-upvl"
    prefix = "terraform/phoebe"
  }
}
