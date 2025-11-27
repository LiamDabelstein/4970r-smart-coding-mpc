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
# You must set these in your Fast MCP Cloud environment variables
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# The name of your MCP server
MCP_SERVER_NAME = "Smart Coding MCP"

# --- 1. Define the MCP Server ---
# We create the MCP server instance here. 
# You can add your tools and resources to this 'mcp' object as usual.
mcp = FastMCP(MCP_SERVER_NAME)

@mcp.tool()
def hello_github_user(name: str) -> str:
    """A simple tool to verify the server is working."""
    return f"Hello, {name}! The Smart Coding server is active."

# --- 2. Create the Main FastAPI Application ---
# We use a standard FastAPI app to host both the MCP server and the Auth routes.
app = FastAPI()

# Mount the MCP server's HTTP app at /mcp
# This matches the URL shown in your screenshot: .../mcp
app.mount("/mcp", mcp._http_handler) 
# Note: In some versions of fastmcp this might be mcp.http_app() or similar. 
# If _http_handler is unavailable, check the fastmcp documentation for the specific 
# method to get the ASGI app. For many versions, mcp.run() handles it, 
# but mounting allows custom routes.

# --- 3. Define the OAuth Callback Route ---
@app.get("/callback", response_class=HTMLResponse)
async def github_callback(request: Request):
    """
    Handle the redirect from GitHub App installation.
    1. Receive 'code' from query parameters.
    2. Exchange 'code' for a User Access Token.
    3. Display the token to the user.
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

    # Success: Display the token (In production, you might save this to a DB)
    html_content = f"""
    <html>
        <head>
            <title>Auth Success</title>
            <style>
                body {{ font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; }}
                .token-box {{ background: #f4f4f4; padding: 15px; border-radius: 5px; word-break: break-all; font-family: monospace; }}
                .copy-btn {{ margin-top: 10px; padding: 8px 16px; cursor: pointer; }}
            </style>
        </head>
        <body>
            <h1>✅ Authentication Successful!</h1>
            <p>You have successfully installed the app and generated a User Access Token.</p>
            <p><strong>Your User Access Token:</strong></p>
            <div class="token-box">{access_token}</div>
            <p>Copy this token. You can now use it in your MCP client configuration to authenticate specific users.</p>
        </body>
    </html>
    """
    return html_content

# --- 4. Entrypoint ---
# This block allows the script to be run directly or by the cloud host
if __name__ == "__main__":
    # The port 8000 is standard, but Fast MCP Cloud might assign one dynamically.
    # Usually, the host looks for the 'app' object in 'server.py'.
    uvicorn.run(app, host="0.0.0.0", port=8000)