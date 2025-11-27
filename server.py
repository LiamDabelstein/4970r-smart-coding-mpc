import os
import httpx
import asyncio
from fastmcp import FastMCP, Context
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# We use the Client ID to identify the app to GitHub.
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
MCP_SERVER_NAME = "Smart Coding MCP"

mcp = FastMCP(MCP_SERVER_NAME)

# --- Helper: Get Token from Context or Env ---
def get_token(ctx: Context = None) -> str:
    """
    Retrieves the GitHub token. It prioritizes the token stored in the 
    MCP Client configuration (Environment Variable).
    """
    # 1. Check for token in the environment (The "Saved in Settings" way)
    # FastMCP automatically injects client-provided env vars into the server process.
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    
    if token and token.startswith("ghu"):
        return token
        
    # 2. If not found, instruct the user to configure it
    raise ValueError(
        "❌ Missing GitHub Token.\n"
        "Please run the 'authenticate_github' tool to generate a token,\n"
        "then add 'GITHUB_PERSONAL_ACCESS_TOKEN' to your MCP Client configuration."
    )

# --- Tool 1: The Login Portal ---
@mcp.tool()
async def authenticate_github(ctx: Context) -> str:
    """
    Start the login process to generate a new User Access Token.
    Returns the token for you to save in your settings.
    """
    async with httpx.AsyncClient() as client:
        # 1. Request Device Code from GitHub
        resp = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": GITHUB_CLIENT_ID, "scope": "repo,read:org"},
            headers={"Accept": "application/json"}
        )
        
        if resp.status_code != 200:
            return f"Error contacting GitHub: {resp.text}"

        data = resp.json()
        device_code = data["device_code"]
        user_code = data["user_code"]
        uri = data["verification_uri"]
        interval = data["interval"]

        # 2. Tell User to Go Click (and wait)
        # We use ctx.info to send a progress update to the user immediately
        ctx.info(f"Action Required: Please visit {uri} and enter code: {user_code}")
        
        # 3. Poll for Success
        # We poll for up to 5 minutes (300s) to give them time to click
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < 300:
            await asyncio.sleep(interval + 2)
            
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
                    f"✅ SUCCESS!\n\n"
                    f"Your Token: {token}\n\n"
                    "👉 NEXT STEP: Go to your MCP Client Settings (Cursor/Claude),\n"
                    "edit this server's configuration, and add this Environment Variable:\n\n"
                    f"GITHUB_PERSONAL_ACCESS_TOKEN={token}\n\n"
                    "After saving, restart the client to apply the changes."
                )
            
            if poll_data.get("error") == "expired_token":
                return "❌ The login code expired. Please run this tool again."

    return "❌ Timed out waiting for authentication."

# --- Tool 2: Example Protected Tool ---
@mcp.tool()
async def list_my_repos(ctx: Context) -> str:
    """
    Lists your private repositories.
    Requires GITHUB_PERSONAL_ACCESS_TOKEN to be set in your configuration.
    """
    try:
        # Get token from the environment (stateless!)
        token = get_token(ctx)
    except ValueError as e:
        return str(e)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/repos?sort=updated&per_page=5",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        
        if response.status_code == 200:
            repos = response.json()
            return "Your Recent Repos:\n" + "\n".join([r["full_name"] for r in repos])
        elif response.status_code == 401:
            return "❌ GitHub rejected your token. It may be invalid or expired."
        else:
            return f"Error from GitHub: {response.status_code}"

if __name__ == "__main__":
    mcp.run()