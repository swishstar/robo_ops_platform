terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.30.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0"
    }
  }

  # Uncomment and set bucket for remote state in shared environments.
  # backend "gcs" {
  #   bucket = "YOUR-TF-STATE-BUCKET"
  #   prefix = "inner-loop/single-project"
  # }
}
