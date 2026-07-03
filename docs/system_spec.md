System Specification: Robo Reliance "Inner Loop" Platform (ADK Edition)

1. Executive Summary & Core Engineering Philosophy

This document establishes the architecture, database schema, operational flow, and deployment criteria for the Robo Reliance Field Operations "Inner Loop" Platform. This platform is built natively on Google Cloud Platform (GCP) and the Gemini Enterprise Agent Platform using the open-source Agent Development Kit (ADK).

Core Constraint

AI interprets and suggests; deterministic systems validate and execute. The Large Language Model (LLM) is treated as an untrusted reasoning engine for parsing unstructured natural language into strictly structured JSON objects. Under no circumstances is the agent permitted to write directly to persistent storage, alter financial records, or trigger API mutations on external systems (QuickBooks, LinkedIn, Slack). Every transaction must be validated, enforced, and committed by handcoded, deterministic Python validation logic exposed to the agent as explicit ADK Tools.

2. System Architecture & Component Topology

The platform coordinates real-time field operations through a secure GCP boundary. Below is the functional mapping of the system layers.

Component Layer Architecture

Layer

System Component

Technical Stack / Service

Functional Scope

Interface

Ops & Finance Web App

React SPA on Cloud Run (IAP)

Primary service-request intake (+ New Service Request form), timekeeping UI, finance approval/history tables, and embedded Web Chat for NL queries about process/data. Finance approval uses the web app (not Chat Cards).

Web Chat (embedded)

POST /api/v1/web-chat/message

Authenticated per-user session; separate from channel-listening agents. Supports NL commands including clock in/out via shared ADK tools.

Workspace Client — Google Chat (internal)

Google Chat Spaces API + /webhooks/google-chat

Internal visit spaces; invitable agent for RAG, field-learnings capture, and NL timekeeping.

Workspace Client — Slack (external)

Slack Events API + /webhooks/slack

Client-facing channels, external technical discussion; parallel agent integration to Google Chat. New visit requests are created via the web app's POST /api/v1/visits (Slack can call this API).

Ingestion

Webhook Target

Google Cloud Functions (Python)

High-speed async ingestion handling Slack events and Chat webhook payloads.

Orchestration

Agent Runtime

Cloud Run hosting ADK App

The core system runtime executing the Agent Development Kit (ADK) team configuration.

Reasoning

Model Core

Gemini 2.0 Pro / Flash

High-context token parsing, intent detection, and structured metadata extraction.

Grounding

Knowledge RAG

Platform Search Extension

Natively indexes files in Google Drive (/03_Technical_Library) with verified citations.

Memory

Session Storage

Platform Memory Bank

Natively maintains cross-session technician contexts and past repair summaries.

Storage

System Database

Cloud SQL for PostgreSQL

Strictly hosts transactional ledgers, visit statuses, timesheets, and audit trails.

MCP Gate

Systems Adapters

Remote MCP Servers (Cloud Run)

Encapsulates QuickBooks, LinkedIn, and Slack integration logic behind standard JSON-RPC.

3. Relational Schema Blueprint

The relational PostgreSQL engine manages state progression, accounting states, and audit tracking across operations.

-- Schema Initialisation Script

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- State progression indicator for technician visits
CREATE TYPE visit_status AS ENUM ('initiated', 'active', 'pending_approval', 'completed', 'failed');

-- 1. Visit Metadata Records
CREATE TABLE visits (
    visit_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slack_channel_id VARCHAR(100),
    google_space_id VARCHAR(255) UNIQUE,
    location_string TEXT NOT NULL,
    metadata_poc JSONB NOT NULL, -- Point of contact: name, phone, email
    current_state visit_status NOT NULL DEFAULT 'initiated',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Labor Tracking Ledger
CREATE TABLE labor_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    visit_id UUID REFERENCES visits(visit_id) ON DELETE CASCADE,
    technician_identity VARCHAR(255) NOT NULL,
    clock_in TIMESTAMP WITH TIME ZONE,
    clock_out TIMESTAMP WITH TIME ZONE,
    extracted_findings TEXT,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Financial Transaction Ledger
CREATE TABLE financial_ledgers (
    ledger_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    visit_id UUID REFERENCES visits(visit_id) ON DELETE CASCADE,
    calculated_hours NUMERIC(6, 2),
    invoice_cents INT NOT NULL,
    payout_cents INT NOT NULL,
    approval_state VARCHAR(50) NOT NULL DEFAULT 'pending_review', -- pending_review, approved, rejected
    qbo_invoice_reference VARCHAR(100),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Immutable Administrative Audit Log
CREATE TABLE immutable_audit_trail (
    audit_id BIGSERIAL PRIMARY KEY,
    visit_id UUID,
    execution_context VARCHAR(100) NOT NULL, -- e.g., "adk_tool_clock_out"
    input_payload JSONB,
    output_receipt JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


4. System Workflow State Transitions

Intake: Customer request submitted via Ops Web App (POST /api/v1/visits) or Slack API call -> Cloud Run Orchestrator creates a dedicated Google Chat Space for the visit and logs record as initiated.

Support: Technician enters Google Chat space -> Conversational RAG queries SOP folder (/03_Technical_Library) via the Search Extension -> ADK platform serves grounded answers with inline citations.

Completion: Tech submits clock-out message -> Agent parses parameters -> Passes data payload to process_visit_signoff tool.

Validation: Deterministic tool code calculates time differences, checks business rules (e.g. clock_out > clock_in), saves status as pending_approval in PostgreSQL, and locks transaction state.

Approval: Finance manager reviews pending ledgers in the Ops Web App and approves or rejects via POST /api/v1/finance/approve (optional Chat notification with deep-link only).

Execution: Accounting manager clicks "Approve" -> Secure callback endpoint triggers remote MCP calls to QuickBooks Online (creating invoices and technician pay records) and LinkedIn (staging social media posts).

Audit: System writes the complete transaction and API receipts to immutable_audit_trail and archives the Google Chat space.

5. ADK Agent & Tool Declarations (Python Spec)

The code below represents the structure of the agent definitions and tools using the Google Agent Development Kit (ADK).

from google_agents_cli_adk import Agent, Gemini, Tool
import datetime
import json

# RAG SOP Retrieval Tool definition
@Tool
def lookup_technical_sop(query: str) -> str:
    """
    Queries the robot manuals and operational standard operating procedures (SOPs).
    This tool connects directly to the Vertex AI Search Index pointing to Google Drive /03_Technical_Library.
    """
    # The platform framework handles vector execution. Returns structured context text.
    pass

# Deterministic validation and ledger update tool definition
@Tool
def process_visit_signoff(visit_id: str, clock_in_str: str, clock_out_str: str, text_findings: str) -> dict:
    """
    Executes core server validation on time entries, calculates billing bounds, 
    and writes to PostgreSQL database ledgers. Banned from AI generation rules.
    """
    try:
        # Parse ISO-8601 Strings
        t_in = datetime.datetime.fromisoformat(clock_in_str.replace("Z", "+00:00"))
        t_out = datetime.datetime.fromisoformat(clock_out_str.replace("Z", "+00:00"))
        
        # Invariant checks
        if t_out <= t_in:
            return {"status": "error", "message": "Validation Failed: Clock-out time cannot precede Clock-in time."}
            
        duration = t_out - t_in
        duration_hours = duration.total_seconds() / 3600.0
        
        # Calculate billing metrics (e.g., $150/hr client invoice, $75/hr contractor pay)
        invoice_amount_cents = int(duration_hours * 15000)
        payout_amount_cents = int(duration_hours * 7500)
        
        # DB Persistence execution (Pseudo-code connector interface)
        # 1. Update visits state to 'pending_approval'
        # 2. Insert record into technician_logs
        # 3. Insert record into financial_ledgers awaiting manager authorization
        
        return {
            "status": "success",
            "calculated_hours": duration_hours,
            "invoice_cents": invoice_amount_cents,
            "payout_cents": payout_amount_cents,
            "next_step": "awaiting_manager_hitl_approval"
        }
    except Exception as e:
        return {"status": "error", "message": f"Execution processing fault: {str(e)}"}

# Define the Master Technician Support Agent
tech_support_agent = Agent(
    name="field_tech_support_agent",
    model=Gemini(model="gemini-2.0-pro"),
    instruction="""
    You are the on-site operational intelligence agent for Robo Reliance. 
    Your mission is to support field engineers and extract visit parameters upon completion.
    
    Operations Guidelines:
    1. Ground all engineering, error codes, and maintenance lookups using 'lookup_technical_sop'.
       Do not hallucinate instructions or error definitions. Always reference matching sources.
    2. When the technician signals work completion or requests to clock out, you must capture 
       the clock-in time, clock-out time, and technical findings. Once extracted, you MUST invoke 
       the 'process_visit_signoff' tool.
    3. You cannot authorize payments or directly log success metrics yourself. You must delegate to your tools.
    """,
    tools=[lookup_technical_sop, process_visit_signoff]
)


6. Local Development Environment (Docker Configuration)

To build and run tests locally without connecting to live GCP resources, use the following container configuration.

docker-compose.yml

version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: local_postgres_ledger
    environment:
      POSTGRES_DB: roboreliance_local
      POSTGRES_USER: engine_admin
      POSTGRES_PASSWORD: development_vault_password
    ports:
      - "5432:5432"
    volumes:
      - ./init-scripts:/docker-entrypoint-initdb.d

  adk_orchestrator:
    build:
      context: ./orchestrator
      dockerfile: Dockerfile.dev
    container_name: local_adk_runtime
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgresql://engine_admin:development_vault_password@postgres:5432/roboreliance_local
      - MCP_QUICKBOOKS_ENDPOINT=http://mcp_quickbooks:9001
      - MCP_LINKEDIN_ENDPOINT=http://mcp_linkedin:9002
      - ENVIRONMENT=development
    depends_on:
      - postgres

  mcp_quickbooks:
    build: ./mcp-servers/quickbooks
    container_name: local_mcp_qbo
    ports:
      - "9001:9001"

  mcp_linkedin:
    build: ./mcp-servers/linkedin
    container_name: local_mcp_linkedin
    ports:
      - "9002:9002"


7. Provisioning & Cloud Deployment Plan

Our continuous deployment pipelines follow a strict segregation between infrastructure topology and container compilation.

7.1 Infrastructure Layer (Terraform)

Terraform manages the cloud topology assets and is executed during environment orchestration setups.

Provisions VPC networking, Private Service Access interfaces, and Cloud SQL databases.

Declares Agent Identity (SPIFFE) permissions to grant the orchestrator minimum required access.

Initializes empty Cloud Run service targets and configures secrets within Cloud Key Vault.

7.2 Application Layer (Agents CLI)

The Agent Development Kit code, tools, model configurations, and runtime engines are deployed using Google's dedicated tooling.

The release manager uses the command agents-cli deploy --target cloud_run to package application changes.

Compiles local application assets into clean container snapshots, uploads the artifact to Artifact Registry, and performs automated rolling zero-downtime updates on the Cloud Run cluster.
