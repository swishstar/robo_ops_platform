"""LinkedIn MCP adapter stub — full mock implementation arrives in Phase 4."""

from fastapi import FastAPI

app = FastAPI(title="LinkedIn MCP Stub")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"service": "mcp_linkedin", "status": "ready"}


@app.post("/jsonrpc")
async def jsonrpc_stub(payload: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": payload.get("id"),
        "result": {
            "receipt_id": "linkedin-stub",
            "status": "accepted",
            "method": payload.get("method"),
        },
    }
