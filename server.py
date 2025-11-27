# --- Standard Library Imports ---
# os: Access environment variables for configuration and secrets.
import os

# --- Third-Party Web Server Imports ---
# uvicorn: ASGI server to run the FastAPI application.
import uvicorn

# --- HTTP Client Imports ---
# httpx: Async HTTP client for making non-blocking requests to GitHub's API.
import httpx

# --- FastAPI Framework Imports ---
# FastAPI: Main web framework for routing and request handling.
# Request: Access incoming request data (query params).
# HTTPException: Return HTTP error codes.
# HTMLResponse: Return HTML content for the success page.
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse

# --- MCP Protocol Imports ---
# FastMCP: High-level framework handling JSON-RPC protocol for AI clients.
from fastmcp import FastMCP

# --- Environment Management Imports ---
# dotenv: Load variables from .env for local development.
from dotenv import load_dotenv

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

# --- 2. Create the Web Application ---
app = FastAPI()

# --- Mount MCP Server ---
# Expose MCP protocol endpoints at /mcp
try:
    # Attempt to get standard ASGI app (FastMCP 2.12+)
    mcp_asgi = mcp.http_app()
except AttributeError:
    # Fallback for older versions/different internal structures
    mcp_asgi = mcp.sse_app()

app.mount("/mcp", mcp_asgi) 

# --- 3. OAuth Callback Route (Detailed Walkthrough) ---
@app.get("/callback", response_class=HTMLResponse)
async def github_callback(request: Request):
    """
    Handle GitHub App installation redirect.
    This function performs the 'OAuth Handshake'.
    """
    # --------------------------------------------------------------------------
    # Step 1: The Code (The "Permission Slip")
    # --------------------------------------------------------------------------
    # When the user clicks "Install" on GitHub, GitHub redirects their browser
    # to this URL (e.g., .../callback?code=xyz123).
    # This 'code' is a temporary, one-time-use credential. It proves the user
    # said "Yes", but it expires in 10 minutes and cannot be used to access data yet.
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' parameter.")

    # --------------------------------------------------------------------------
    # Step 2: The Exchange (Trading the Slip for the Key)
    # --------------------------------------------------------------------------
    # We now have to call GitHub back (server-to-server) to trade that temporary
    # 'code' for a permanent 'access_token'.
    # We must prove our identity by including our 'client_secret' (password).
    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": GITHUB_CLIENT_ID,         # "Hi, I am the Smart Coding App"
        "client_secret": GITHUB_CLIENT_SECRET, # "Here is my secret password to prove it"
        "code": code                           # "Here is the user's permission slip"
    }
    # We request the response in JSON format so it's easy to read in Python.
    headers = {"Accept": "application/json"}

    # --------------------------------------------------------------------------
    # Step 3: The Request (Behind the Scenes)
    # --------------------------------------------------------------------------
    # We use 'httpx' to send this POST request securely. The user's browser
    # never sees this part; it happens entirely on our server.
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, json=payload, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to communicate with GitHub.")

    # --------------------------------------------------------------------------
    # Step 4: The Token (The "Key")
    # --------------------------------------------------------------------------
    # If successful, GitHub replies with an 'access_token'. 
    # This token is the "Key" to the user's repository. 
    # Any tool that holds this token can read/write their code as if it were them.
    data = response.json()
    access_token = data.get("access_token")

    if not access_token:
        error_desc = data.get("error_description", "Unknown error")
        return f"<h1>Authentication Failed</h1><p>{error_desc}</p>"

    # --------------------------------------------------------------------------
    # Step 5: Delivery (Handing the Key to the User)
    # --------------------------------------------------------------------------
    # Since we are building an MCP tool, we simply show the token to the user
    # so they can copy-paste it into their AI Client (Claude/Cursor).
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
            <p>Copy this token for your MCP client configuration.</p>
        </body>
    </html>
    """
    return html_content

# --- 4. Run the Server ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)