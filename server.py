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

# Initialize FastMCP
mcp = FastMCP(MCP_SERVER_NAME)

# --- Dependency: Token Validation ---
# This function runs before any tool that requests 'token: str'.
# It looks for the 'Authorization' header in the incoming request.
# NOTE: FastMCP handles dependency injection based on type hints or context.
# Since direct header access can vary by transport (SSE vs HTTP), 
# we will use a Context helper or simply check it inside the tool if dependencies are tricky.

def validate_header_token(ctx: Context) -> str:
    """
    Extracts the Bearer token from the request headers.
    This works when 'mcp-remote' passes the --header "Authorization: Bearer ..."
    """
    # Attempt to get headers from the underlying request context
    # Note: The exact property path depends on FastMCP version, but this is standard.
    try:
        # Access the raw Starlette/FastAPI request object if available
        request = ctx.request_context.request
        auth_header = request.headers.get("authorization", "")
        
        if not auth_header.startswith("Bearer "):
            # Fallback: check if it was passed as a direct env var (local testing)
            local_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
            if local_token:
                return local_token
            raise ValueError("Missing Authorization Header")
            
        token = auth_header.split("Bearer ")[1]
        if not token.startswith("ghu"):
             raise ValueError("Invalid Token Format")
        return token
        
    except Exception:
        # If we can't find the header, we ask the user to log in.
        raise ToolError(
            "🔒 Authentication Required.\n"
            "Please run the 'authenticate_github' tool first to get a token.\n"
            "Then configure your client to send it as an Authorization header."
        )

# --- Tool 1: Login (Public) ---
@mcp.tool()
async def authenticate_github(ctx: Context) -> str:
    """
    Start the login process to generate a new User Access Token.
    """
    async with httpx.AsyncClient() as client:
        # 1. Request Code
        resp = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": GITHUB_CLIENT_ID, "scope": "repo,read:org"},
            headers={"Accept": "application/json"}
        )
        data = resp.json()
        
        # 2. Instruct User
        ctx.info(f"Please visit {data['verification_uri']} and enter code: {data['user_code']}")
        
        # 3. Poll
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
    return "❌ Timeout."

# --- Tool 2: Protected Tool ---
@mcp.tool()
async def list_my_repos(ctx: Context) -> str:
    """
    Lists your private repositories. 
    (Token is automatically extracted from headers).
    """
    # 1. Get Token (Validation happens here)
    token = validate_header_token(ctx)

    # 2. Use Token
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/repos?per_page=5",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        )
        if response.status_code == 200:
            return "Repos:\n" + "\n".join([r["full_name"] for r in response.json()])
        return f"GitHub Error: {response.status_code}"

if __name__ == "__main__":
    mcp.run()