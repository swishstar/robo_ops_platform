resource "google_project_service" "required" {
  for_each = toset([
    "compute.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "chat.googleapis.com",
    "discoveryengine.googleapis.com",
    "iap.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
