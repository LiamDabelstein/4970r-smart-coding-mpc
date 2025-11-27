import os
import httpx
import asyncio
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
            "Please ask the AI to 'Log me in to GitHub' to start the process."
        )

# --- Tool 1: Step 1 - Start Login (Non-Blocking) ---
@mcp.tool()
async def initiate_login() -> str:
    """
    STEP 1: Call this to start the GitHub login process.
    It returns a URL and Code for the user, and a 'device_code' 
    that must be passed to the 'verify_login' tool.
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
    STEP 2: Call this AFTER the user has entered the code on GitHub.
    It polls GitHub until the login is complete and returns the Access Token.
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
                    "3. Add/Update the 'env' section for 'smart-coding':\n"
                    f'   "env": {{ "GITHUB_PERSONAL_ACCESS_TOKEN": "{token}" }}\n'
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
    Authentication is handled automatically via headers.
    """
    token = validate_header_token(ctx)

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