# --- Standard Library Imports ---
# [RUNS] Needed for configuration
import os

# --- Third-Party Web Server Imports ---
# [IGNORED] Cloud has its own server; it doesn't use your uvicorn import.
import uvicorn

# --- HTTP Client Imports ---
# [RUNS] Can be used inside tools, but effectively dead for the callback since the callback never runs.
import httpx

# --- FastAPI Framework Imports ---
# [IGNORED] The Cloud doesn't use your FastAPI app.
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse

# --- MCP Protocol Imports ---
# [RUNS] This is the core library the Cloud looks for.
from fastmcp import FastMCP

# --- Environment Management Imports ---
# [RUNS] Loads your secrets.
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# [RUNS] These variables are loaded successfully.
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
MCP_SERVER_NAME = "Smart Coding MCP"

# --- 1. Define the MCP Server ---
# [RUNS] This is the ONLY thing the Cloud cares about.
# It finds this object and wraps it in its own hidden web server.
mcp = FastMCP(MCP_SERVER_NAME)

# [RUNS] This tool is registered and works perfectly.
@mcp.tool()
def hello_github_user(name: str) -> str:
    """A simple tool to verify the server is working."""
    return f"Hello, {name}! The Smart Coding server is active."

# ==============================================================================
# 💀 DEAD CODE ZONE (Everything below is IGNORED by the Cloud) 💀
# ==============================================================================

# [IGNORED] You create this app, but the Cloud never starts it. It sits in memory doing nothing.
# app = FastAPI()

# [IGNORED] Since 'app' isn't running, this mount does nothing.
# try:
#     mcp_asgi = mcp.http_app()
# except AttributeError:
#     mcp_asgi = mcp.sse_app()
# app.mount("/mcp", mcp_asgi)

# [IGNORED] This route is attached to your 'app'. Since the Cloud ignores 'app',
# this route effectively doesn't exist. This is why you get 404.
# @app.get("/callback", response_class=HTMLResponse)
# async def github_callback(request: Request):
#     """
#     Handle GitHub App installation redirect.
#     """
#     code = request.query_params.get("code")
#     # ... (Rest of your authentication logic is dead code) ...
#     return html_content

# [IGNORED] FastMCP Cloud does NOT run your script as "__main__".
# It imports your file and runs the 'mcp' object directly.
# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8000)