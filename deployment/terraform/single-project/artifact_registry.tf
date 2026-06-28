resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = local.artifact_repo_id
  description   = "Inner Loop platform container images"
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}
