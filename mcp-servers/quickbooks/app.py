"""QuickBooks MCP adapter stub — full mock implementation arrives in Phase 4."""

from fastapi import FastAPI

app = FastAPI(title="QuickBooks MCP Stub")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"service": "mcp_quickbooks", "status": "ready"}


@app.post("/jsonrpc")
async def jsonrpc_stub(payload: dict) -> dict:
    method = payload.get("method", "unknown")
    params = payload.get("params") or {}
    result = {
        "receipt_id": f"qbo-{params.get('ledger_id', 'unknown')[:8]}",
        "status": "accepted",
        "method": method,
    }
    if method == "quickbooks.create_invoice":
        result["invoice_reference"] = f"INV-{params.get('visit_id', 'unknown')[:8].upper()}"
        result["invoice_cents"] = params.get("invoice_cents")
    elif method == "quickbooks.record_payout":
        result["payout_cents"] = params.get("payout_cents")
        result["technician_identity"] = params.get("technician_identity")
    return {
        "jsonrpc": "2.0",
        "id": payload.get("id"),
        "result": result,
    }
