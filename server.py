import os
import uvicorn
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration ---
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
MCP_SERVER_NAME = "Smart Coding MCP"

# --- 1. Define the MCP Server ---
mcp = FastMCP(MCP_SERVER_NAME)

@mcp.tool()
def hello_github_user(name: str) -> str:
    """A simple tool to verify the server is working."""
    return f"Hello, {name}! The Smart Coding server is active."

# --- 2. Create the Main FastAPI Application ---
app = FastAPI()

# FIX: Use 'mcp._fastapi_app' or the documented 'http_app()' if available.
# In FastMCP 2.x+, the safest way to get the ASGI app is often implicit or via .http_app()
# We will use a try-block to be robust against version differences, 
# but .http_app() is the standard for 2.12+
try:
    mcp_asgi = mcp.http_app()
except AttributeError:
    # Fallback: In some versions, mcp itself is the app or it uses .sse_app()
    mcp_asgi = mcp.sse_app()

app.mount("/mcp", mcp_asgi) 

# --- 3. Define the OAuth Callback Route ---
@app.get("/callback", response_class=HTMLResponse)
async def github_callback(request: Request):
    """
    Handle the redirect from GitHub App installation.
    """
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' parameter.")

    # Exchange code for access token
    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": code
    }
    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, json=payload, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to communicate with GitHub.")

    data = response.json()
    access_token = data.get("access_token")

    if not access_token:
        error_desc = data.get("error_description", "Unknown error")
        return f"<h1>Authentication Failed</h1><p>{error_desc}</p>"

    # Success: Display the token
    html_content = f"""
    <html>
        <head>
            <title>Auth Success</title>
            <style>
                body {{ font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; }}
                .token-box {{ background: #f4f4f4; padding: 15px; border-radius: 5px; word-break: break-all; font-family: monospace; }}
            </style>
        </head>
        <body>
            <h1>✅ Authentication Successful!</h1>
            <p>You have successfully installed the app and generated a User Access Token.</p>
            <p><strong>Your User Access Token:</strong></p>
            <div class="token-box">{access_token}</div>
            <p>Copy this token. You can now use it in your MCP client configuration.</p>
        </body>
    </html>
    """
    return html_content

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)