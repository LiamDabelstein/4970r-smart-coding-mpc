import os
import httpx
import asyncio
from typing import Annotated
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
MCP_SERVER_NAME = "Smart Coding MCP"

mcp = FastMCP(MCP_SERVER_NAME)

# --- Helper: Token Validation ---
def validate_header_token(ctx: Context) -> str:
    """
    Extracts the token from the custom header 'User-Access-Token'.
    """
    try:
        request = ctx.request_context.request
        headers = request.headers
        
        # Check for our custom header (case-insensitive)
        token = headers.get("user-access-token", "")
        
        # Also check env var for local testing fallback
        if not token:
            token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")

        if not token:
            raise ValueError("Missing Token")
            
        if not token.startswith("ghu"):
             raise ValueError("Invalid Token Format")
             
        return token
        
    except Exception:
        raise ToolError(
            "🔒 Authentication Required.\n"
            "Please run the 'authenticate_github' tool first to get a token.\n"
            "Then add it to your configuration."
        )

# --- Tool 1: Login ---
@mcp.tool()
async def authenticate_github(ctx: Context) -> str:
    """
    Start login process. Returns the token.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": GITHUB_CLIENT_ID, "scope": "repo,read:org"},
            headers={"Accept": "application/json"}
        )
        data = resp.json()
        
        ctx.info(f"Action Required: Visit {data['verification_uri']} and enter: {data['user_code']}")
        
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < 300:
            await asyncio.sleep(data["interval"] + 2)
            poll_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": data["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                },
                headers={"Accept": "application/json"}
            )
            poll_data = poll_resp.json()
            if "access_token" in poll_data:
                token = poll_data["access_token"]
                return (
                    f"✅ SUCCESS! Token: {token}\n\n"
                    "👉 CONFIGURATION STEP:\n"
                    "Update your Claude Desktop config for 'smart-coding':\n"
                    '"env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "' + token + '" }'
                )
            
            if poll_data.get("error") == "expired_token":
                return "❌ Code expired. Try again."
    return "❌ Timeout."

# --- Tool 2: Protected Tool ---
@mcp.tool()
async def list_my_repos(ctx: Context) -> str:
    """
    Lists private repos. Token is extracted from 'User-Access-Token' header.
    """
    token = validate_header_token(ctx)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/repos?sort=updated&per_page=5",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        )
        if response.status_code == 200:
            return "Repos:\n" + "\n".join([r["full_name"] for r in response.json()])
        return f"Error: {response.status_code}"

if __name__ == "__main__":
    mcp.run()