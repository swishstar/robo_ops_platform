data "google_project" "current" {
  project_id = var.project_id
}

locals {
  labels = {
    environment = var.environment
    platform    = "robo-inner-loop"
    managed_by  = "terraform"
  }

  vpc_name            = "${var.name_prefix}-vpc"
  subnet_name         = "${var.name_prefix}-subnet"
  vpc_connector_name  = "${var.name_prefix}-connector"
  sql_instance_name   = "${var.name_prefix}-pg-${var.environment}"
  artifact_repo_id    = "${var.name_prefix}-images"
  orchestrator_name   = "${var.name_prefix}-orchestrator"
  web_app_name        = "${var.name_prefix}-ops-web"
  mcp_qbo_name        = "${var.name_prefix}-mcp-qbo"
  mcp_linkedin_name   = "${var.name_prefix}-mcp-linkedin"
  orchestrator_sa_id  = "${var.name_prefix}-orchestrator"
  mcp_sa_id           = "${var.name_prefix}-mcp"
  cicd_sa_id          = "${var.name_prefix}-cicd"

  # Cloud Run IAP audience (no load balancer): /projects/NUMBER/locations/REGION/services/NAME
  computed_iap_audience = "/projects/${data.google_project.current.number}/locations/${var.region}/services/${local.web_app_name}"
  effective_iap_audience = var.iap_audience != "" ? var.iap_audience : (
    var.enable_iap_ops_web ? local.computed_iap_audience : ""
  )
  iap_service_agent = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-iap.iam.gserviceaccount.com"
}
