import os
import httpx
import asyncio
from fastmcp import FastMCP, Context
from dotenv import load_dotenv

load_dotenv()

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
MCP_SERVER_NAME = "Smart Coding MCP"

mcp = FastMCP(MCP_SERVER_NAME)

# --- Helper: Validation ---
def validate_token(token: str) -> str:
    if not token or not token.startswith("ghu"):
        raise ValueError("❌ Invalid Token. Please run 'authenticate_github' first.")
    return token

# --- Tool 1: Login ---
@mcp.tool()
async def authenticate_github(ctx: Context) -> str:
    """
    Start login process. Returns the token.
    User should save this token in their System Prompt or Rules.
    """
    async with httpx.AsyncClient() as client:
        # 1. Request Code
        resp = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": GITHUB_CLIENT_ID, "scope": "repo,read:org"},
            headers={"Accept": "application/json"}
        )
        data = resp.json()
        
        # 2. Tell User to Click
        ctx.info(f"Visit {data['verification_uri']} and enter: {data['user_code']}")
        
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
                    "👉 INSTRUCTION: Add this to your System Prompt / Project Rules:\n"
                    f"'My GitHub Token is {token}. Use this for all Smart Coding tools.'"
                )
    return "❌ Timed out."

# --- Tool 2: Protected Tool ---
@mcp.tool()
async def list_my_repos(github_token: str) -> str:
    """
    Lists private repos. 
    You must provide the 'github_token' argument.
    """
    # 1. Use the token passed by the LLM
    token = validate_token(github_token)

    # 2. Call GitHub
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
            return "Repos:\n" + "\n".join([r["full_name"] for r in repos])
        return f"Error: {response.status_code}"

if __name__ == "__main__":
    mcp.run()