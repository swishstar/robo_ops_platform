"""QuickBooks MCP adapter stub — full mock implementation arrives in Phase 4."""

from fastapi import FastAPI

app = FastAPI(title="QuickBooks MCP Stub")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"service": "mcp_quickbooks", "status": "ready"}


@app.post("/jsonrpc")
async def jsonrpc_stub(payload: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": payload.get("id"),
        "result": {
            "receipt_id": "qbo-stub",
            "status": "accepted",
            "method": payload.get("method"),
        },
    }
