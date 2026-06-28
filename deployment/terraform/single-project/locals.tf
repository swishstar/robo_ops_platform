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
  mcp_qbo_name        = "${var.name_prefix}-mcp-qbo"
  mcp_linkedin_name   = "${var.name_prefix}-mcp-linkedin"
  orchestrator_sa_id  = "${var.name_prefix}-orchestrator"
  mcp_sa_id           = "${var.name_prefix}-mcp"
  cicd_sa_id          = "${var.name_prefix}-cicd"
}
