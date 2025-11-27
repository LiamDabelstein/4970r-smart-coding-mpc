import os
import httpx
import asyncio
from typing import Annotated
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# We use the Client ID to identify the app to GitHub.
# The Client Secret is NOT needed for Device Flow.
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
            # We explicitly raise a helpful error that the LLM can see
            # This triggers the fallback to login ONLY if the header is missing
            raise ValueError("Missing Token")
            
        if not token.startswith("ghu"):
             raise ValueError("Invalid Token Format")
             
        return token
        
    except Exception:
        raise ToolError(
            "🔒 Authentication Failed.\n"
            "The tool attempted to access GitHub but no valid token was found header.\n"
            "Please RUN the 'initiate_login' tool now to fix this."
        )

# --- Tool 1: Step 1 - Start Login (Non-Blocking) ---
@mcp.tool()
async def initiate_login() -> str:
    """
    Starts the GitHub login process.
    
    IMPORTANT: Do NOT call this tool unless 'list_my_repos' has failed 
    with an Authentication Error or the user explicitly asks to login
    to their github account.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": GITHUB_CLIENT_ID, "scope": "repo,read:org"},
            headers={"Accept": "application/json"}
        )
        data = resp.json()
        
        if resp.status_code != 200:
            return f"Error connecting to GitHub: {resp.text}"

        device_code = data["device_code"]
        user_code = data["user_code"]
        uri = data["verification_uri"]
        interval = data.get("interval", 5)

        # We return the instructions immediately so the user sees them.
        return (
            f"ACTION REQUIRED:\n"
            f"1. Click this link: {uri}\n"
            f"2. Enter this code: {user_code}\n\n"
            "AFTER you have done this, please call the 'verify_login' tool "
            f"with this device_code: {device_code}"
        )

# --- Tool 2: Step 2 - Finish Login (Blocking) ---
@mcp.tool()
async def verify_login(device_code: str) -> str:
    """
    Completes the login process. Call this AFTER the user clicks the link.
    """
    async with httpx.AsyncClient() as client:
        # We poll for up to 2 minutes (120s)
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < 120:
            # Poll GitHub
            poll_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": device_code,
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
                    "1. Copy this token.\n"
                    "2. Open your Claude Desktop config file.\n"
                    "3. Update the 'smart-coding' args to include:\n"
                    f'   "--header", "User-Access-Token:{token}"\n'
                    "4. Restart Claude."
                )
            
            if poll_data.get("error") == "expired_token":
                return "❌ The login code expired. Please start over with 'initiate_login'."
            
            # Wait 5 seconds before checking again
            await asyncio.sleep(5)
            
    return "❌ Timeout: User did not authorize in time. Please try again."

# --- Tool 3: Protected Tool ---
@mcp.tool()
async def list_my_repos(ctx: Context) -> str:
    """
    Lists your private repositories.
    
    IMPORTANT: Always try this tool FIRST. 
    Authentication is handled automatically via headers. 
    You do not need to call initiate_login unless this tool returns an error.
    """
    # 1. Validate the token from the header
    token = validate_header_token(ctx)

    # 2. Use the token to fetch data
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/repos?sort=updated&per_page=5",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        )
        if response.status_code == 200:
            repos = response.json()
            names = [r["full_name"] for r in repos]
            return "Your Recent Repos:\n" + "\n".join(names)
        
        return f"GitHub Error: {response.status_code}"

if __name__ == "__main__":
    mcp.run()