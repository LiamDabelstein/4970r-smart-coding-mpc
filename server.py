import os  # System interface for environment variables
import httpx  # Async HTTP client for API requests
import asyncio  # Asynchronous I/O and time management
import base64  # Encoding/decoding for GitHub file content
from fastmcp import FastMCP, Context  # Core MCP server framework
from fastmcp.exceptions import ToolError  # MCP specific error handling
from dotenv import load_dotenv  # Load environment variables from .env file

load_dotenv()  # Initialize environment variables

# --- Configuration ---
# We use the Client ID to identify the app to GitHub.
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
MCP_SERVER_NAME = "Smart Coding MCP"

# Initialize server instance
mcp = FastMCP(MCP_SERVER_NAME)  

# --- Helper: Token Validation ---
def validate_header_token(ctx: Context) -> str:
    """
    Extracts the token from the custom header 'User-Access-Token'.
    """
    try:
        request = ctx.request_context.request  # Access raw request object
        headers = request.headers  # Get headers dictionary
        
        # Check for the custom header (case-insensitive)
        token = headers.get("user-access-token", "")
        
        if not token:
            raise ValueError("Missing 'User-Access-Token' header.")
            
        # Allow 'gho' (OAuth), 'ghp' (Personal), and 'ghu' (User) prefixes
        # This ensures we don't pass malformed strings to the GitHub API
        if not token.startswith(("ghu", "gho", "ghp")):
             raise ValueError("Invalid Token Format (must start with 'ghu', 'gho', or 'ghp')")
             
        return token
        
    except Exception:
        raise ToolError(
            "Authentication Failed.\n"
            "The tool attempted to access GitHub but no valid token was found header.\n"
            "Please RUN the 'initiate_login' tool now to fix this."
        )

# --- Helper: Centralized Error Parsing ---
def parse_github_error(resp: httpx.Response) -> str:
    """
    Translates HTTP status codes into actionable error messages for the LLM.
    """
    if resp.status_code == 401:
        return "401 Unauthorized: Your token is invalid, expired, or revoked."
        
    if resp.status_code == 403:
        # Common cause: The App is installed on the User's account, but NOT 
        # on the Organization that owns the repo.
        return (
            "403 Forbidden: Access denied. Possibilities:\n"
            "1. The App is not installed on this specific repository/organization.\n"
            "2. Organization SAML/SSO enforcement is blocking access.\n"
            "3. API Rate limit exceeded."
        )
        
    if resp.status_code == 404:
        # GitHub returns 404 for Private repos if you lack permissions
        return (
            "404 Not Found: The repository does not exist OR the App lacks permission to see it.\n"
            "(GitHub hides private repos as 404s to prevent leaking their existence)."
        )
        
    if resp.status_code == 409:
        return "409 Conflict: The file has changed since you last read it (Git Conflict)."
        
    if resp.status_code == 422:
        return "422 Unprocessable Entity: Validation failed (e.g., Pull Request already exists)."

    return f"GitHub API Error {resp.status_code}: {resp.text}"

# ==============================================================================
# AUTHENTICATION TOOLS
# Tools 1 & 2: Handle the OAuth Device Flow to get a token.
# ==============================================================================

# --- Start Login (Non-Blocking) ---
@mcp.tool()
async def initiate_login() -> str:
    """
    Starts the GitHub login process.
      
    IMPORTANT: Do NOT call this tool unless any other tools have failed 
    with an authentication error OR the user explicitly asks to login 
    to their GitHub account.
    """
    async with httpx.AsyncClient() as client:
        # Request device code from GitHub
        # This initiates the OAuth Device Flow
        resp = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": GITHUB_CLIENT_ID, "scope": "repo,read:org"},
            headers={"Accept": "application/json"}
        )
        data = resp.json()
        
        if resp.status_code != 200:
            return f"Error connecting to GitHub: {resp.text}"

        # Parse the response to get user verification codes
        device_code = data["device_code"]
        user_code = data["user_code"]
        uri = data["verification_uri"]
        interval = data.get("interval", 5)  # Polling interval recommended by GitHub

        # Return instructions to the LLM to display to the user
        return (
            f"ACTION REQUIRED:\n"
            f"1. Click this link: {uri}\n"
            f"2. Enter this code: {user_code}\n\n"
            "AFTER you have done this, please call the 'verify_login' tool "
            f"with this device_code: {device_code}"
        )

# --- Finish Login (Blocking) ---
@mcp.tool()
async def verify_login(device_code: str) -> str:
    """
    Completes the login process. Call this AFTER the user clicks the link.

    IMPORTANT: Tell the user where to put the personal access token when
    the login is successful.
    """
    async with httpx.AsyncClient() as client:
        # Use get_running_loop() and with timeout of 120s to prevent hanging
        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < 120:

            # Check authorization status with GitHub
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
            
            # If the response contains 'access_token', the user has authorized
            if "access_token" in poll_data:
                token = poll_data["access_token"]  
                return (
                    f"SUCCESS! Token: {token}\n\n"
                    "CONFIGURATION STEP:\n"
                    "1. Copy this token.\n"
                    "2. Open your Claude Desktop config file.\n"
                    "3. Add the token to the 'env' section for 'smart-coding':\n"
                    f'   "env": {{\n'
                    f'     "GITHUB_PERSONAL_ACCESS_TOKEN": "{token}"\n'
                    f'   }}\n'
                    "4. Restart Claude."
                )
            
            # Handle explicit expiration error
            if poll_data.get("error") == "expired_token":
                return "The login code expired. Please start over with 'initiate_login'."
            
            await asyncio.sleep(5)  # Wait 5 seconds before next poll
            
    return "Timeout: User did not authorize in time. Please try again."

# ==============================================================================
# PHASE 0: DISCOVERY
# Use these tools to find out WHO the user is and search for repos.
# ==============================================================================

@mcp.tool()
async def get_user_context(ctx: Context) -> str:
    """
    Step 0 (Part A): Identifies the connected user and lists the 10 most recently updated repos.
    API Calls: GET /user, GET /user/repos

    IMPORTANT: Use this tool FIRST to help the user select which repository
    they want to work on. If the desired repository is NOT in this list,
    proceed to use 'search_repositories'.
    """
    token = validate_header_token(ctx)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient() as client:
        # Parallel fetch: User identity and Repos (Top 10 recently updated)
        tasks = [
            client.get("https://api.github.com/user", headers=headers),
            client.get("https://api.github.com/user/repos?sort=updated&per_page=10&type=owner", headers=headers)
        ]
        
        user_resp, repos_resp = await asyncio.gather(*tasks)

        # 1. Process User Identity (Strict Error Checking)
        if user_resp.status_code != 200:
             return f"User Check Failed: {parse_github_error(user_resp)}"
             
        user_data = user_resp.json()
        user_info = f"User: {user_data.get('login')} ({user_data.get('name', 'No Name')})"

        # 2. Process Repositories
        repo_list = []
        if repos_resp.status_code == 200:
            repos = repos_resp.json()
            for r in repos:
                private_icon = "[Private]" if r.get("private") else "[Public]"
                repo_list.append(f"- {private_icon} {r.get('full_name')}: {r.get('description', 'No description')}")
        else:
            # Explicitly capture why listing repos failed
            repo_list.append(f"Error fetching repositories: {parse_github_error(repos_resp)}")

        return (
            f"{user_info}\n"
            f"===================================\n"
            f"Top 10 Recent Repositories:\n" + "\n".join(repo_list)
        )

@mcp.tool()
async def search_repositories(ctx: Context, query: str) -> str:
    """
    Step 0 (Part B): Searches for repositories accessible to the user.
    API Call: GET /search/repositories
    
    IMPORTANT: Use this tool if the repository the user wants to work on is 
    NOT listed in the 'get_user_context' results. This allows you to find 
    older or less frequently used repositories.
    """
    token = validate_header_token(ctx)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient() as client:
        # Search for repos matching the query that the user has access to
        # 'user:@me' limits search to the authenticated user's scope
        search_url = f"https://api.github.com/search/repositories?q={query}+user:@me&per_page=5"
        
        resp = await client.get(search_url, headers=headers)
        
        if resp.status_code != 200:
            return f"Search failed: {parse_github_error(resp)}"
            
        data = resp.json()
        items = data.get("items", [])
        
        if not items:
            return f"No repositories found matching '{query}'."
            
        results = []
        for repo in items:
            private_status = "[Private]" if repo.get("private") else "[Public]"
            # Include the updated date so the user knows if it's an old project
            results.append(f"- {private_status} {repo['full_name']} (Updated: {repo['updated_at'][:10]})")
            
        return f"Search Results for '{query}':\n" + "\n".join(results)

# ==============================================================================
# PHASE 1: ORIENTATION (The Map)
# Use these tools FIRST to understand the project before reading code.
# ==============================================================================

@mcp.tool()
async def get_repository_map(ctx: Context, owner: str, repo: str, branch: str = "main") -> str:
    """
    Step 1: Retrieves the entire file structure of the repository.
    API Call: GET /git/trees/{branch}?recursive=1

    IMPORTANT: When the user asks to document a file of source code within
    a project or github repository, get_repository_map represents the first 
    tool in the cronilogical order of operations. To provide the best results
    and get the most context about the source code for documentation, follow 
    tools that have steps 1-7 to fully complete the task.
    """
    token = validate_header_token(ctx)
    async with httpx.AsyncClient() as client:
        # Recursive=1 fetches nested folders (Deep Context)
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        resp = await client.get(
            url, 
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        )
        
        # Explicit error handling for missing/unauthorized repos
        if resp.status_code != 200:
            return parse_github_error(resp)

        data = resp.json()
        if data.get("truncated"):
            return "Warning: Repo is too large. Showing partial structure."
        
        # Filter to only show files (blobs), ignore folders to save tokens
        files = [item["path"] for item in data.get("tree", []) if item["type"] == "blob"]
        
        # Return top 200 files to prevent context overflow in the LLM
        return f"Repository Map for {owner}/{repo}:\n\n" + "\n".join(files[:200])

@mcp.tool()
async def get_project_overview(ctx: Context, owner: str, repo: str) -> str:
    """
    Step 2: Synthesizes the tech stack, languages, and README.
    API Calls: GET /languages, GET /dependency-graph/sbom, GET /readme

    IMPORTANT: When the user asks to document a file of source code within
    a project or github repository, get_repository_map represents the first 
    tool in the cronilogical order of operations. To provide the best results
    and get the most context about the source code for documentation, follow 
    tools that have steps 1-7 to fully complete the task.
    """
    token = validate_header_token(ctx)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    
    async with httpx.AsyncClient() as client:
        # Run 3 inexpensive requests in parallel to reduce latency
        tasks = [
            client.get(f"https://api.github.com/repos/{owner}/{repo}/languages", headers=headers),
            client.get(f"https://api.github.com/repos/{owner}/{repo}/dependency-graph/sbom", headers=headers),
            client.get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers)
        ]
        
        # Wait for all requests to complete
        langs_resp, sbom_resp, readme_resp = await asyncio.gather(*tasks)
        
        # 1. Process Languages
        languages = list(langs_resp.json().keys()) if langs_resp.status_code == 200 else ["Unknown"]
        
        # 2. Process SBOM (Software Bill of Materials / Libraries)
        stack = []
        if sbom_resp.status_code == 200:
            data = sbom_resp.json()
            for pkg in data.get("sbom", {}).get("packages", []):
                stack.append(f"{pkg.get('name')} ({pkg.get('versionInfo', '')})")
        else:
            stack = ["(Dependency Graph disabled for this repo)"]

        # 3. Process README
        readme_snippet = "No README found."
        if readme_resp.status_code == 200:
            try:
                content = base64.b64decode(readme_resp.json()["content"]).decode("utf-8")
                readme_snippet = content[:500] + "..." # Truncate to first 500 chars
            except:
                readme_snippet = "Error decoding README."
        # If the README is missing (404), it's not a critical error, so we don't return parse_github_error here.

        return (
            f"PROJECT OVERVIEW: {owner}/{repo}\n"
            f"===================================\n"
            f"Languages: {', '.join(languages)}\n"
            f"Tech Stack: {', '.join(stack[:10])}\n"
            f"README Preview:\n{readme_snippet}"
        )

# ==============================================================================
# PHASE 2: INSPECTION (The Reader)
# Use these tools to read code. 'Deep' for target files, 'References' for imports.
# ==============================================================================

@mcp.tool()
async def inspect_target_file(ctx: Context, owner: str, repo: str, path: str) -> str:
    """
    Step 3: Deep analysis of the file you want to document.
    API Calls: GET /contents, GET /commits, GET /commits/{sha}/pulls

    IMPORTANT: When the user asks to document a file of source code within
    a project or github repository, get_repository_map represents the first 
    tool in the cronilogical order of operations. To provide the best results
    and get the most context about the source code for documentation, follow 
    tools that have steps 1-7 to fully complete the task.
    """
    token = validate_header_token(ctx)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    
    async with httpx.AsyncClient() as client:
        # A. Get Content
        content_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
        
        # Explicitly catch file not found or permission errors
        if content_resp.status_code != 200:
            return parse_github_error(content_resp)
        
        file_data = content_resp.json()
        content = base64.b64decode(file_data["content"]).decode("utf-8")
        current_sha = file_data["sha"] # SHA needed later for updates

        # B. Get Commit History (Last 3)
        history_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/commits?path={path}&per_page=3", headers=headers)
        commits = history_resp.json() if history_resp.status_code == 200 else []
        
        history_text = ""
        latest_commit_sha = None
        
        for c in commits:
            if not latest_commit_sha: latest_commit_sha = c["sha"]
            msg = c["commit"]["message"].split('\n')[0]
            author = c["commit"]["author"]["name"]
            history_text += f"- {author}: {msg}\n"

        # C. Get Intent (PR) associated with the LATEST change
        pr_context = "No associated PR found."
        if latest_commit_sha:
            # Special endpoint to link commit -> PR to understand business logic
            pr_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/commits/{latest_commit_sha}/pulls", headers=headers)
            if pr_resp.status_code == 200 and pr_resp.json():
                pr = pr_resp.json()[0]
                pr_context = f"PR #{pr['number']} - {pr['title']}\n{pr['body'][:200]}..."

        return (
            f"DEEP INSPECTION: {path}\n"
            f"File SHA: {current_sha} (Required for updates)\n"
            f"===================================\n"
            f"Recent History:\n{history_text}\n"
            f"Business Intent (PR):\n{pr_context}\n"
            f"===================================\n"
            f"{content}"
        )

@mcp.tool()
async def read_references(ctx: Context, owner: str, repo: str, paths: list[str]) -> str:
    """
    Step 4: Reads dependencies/imports found in the target file.
    API Calls: Multiple GET /contents calls in parallel.

    IMPORTANT: When the user asks to document a file of source code within
    a project or github repository, get_repository_map represents the first 
    tool in the cronilogical order of operations. To provide the best results
    and get the most context about the source code for documentation, follow 
    tools that have steps 1-7 to fully complete the task.
    """
    token = validate_header_token(ctx)
    
    # Inner helper to fetch individual file content safely
    async def fetch_one(client, path):
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        )
        if resp.status_code == 200:
            try:
                content = base64.b64decode(resp.json()["content"]).decode("utf-8")
                return f"--- REFERENCE: {path} ---\n{content}\n"
            except:
                return f"--- ERROR: Could not decode {path} ---\n"
        
        # Return strict error if failed, so LLM knows why import is missing
        return f"--- ERROR: {path} ({parse_github_error(resp)}) ---\n"

    async with httpx.AsyncClient() as client:
        # Create tasks for every path requested
        tasks = [fetch_one(client, p) for p in paths]
        results = await asyncio.gather(*tasks)
    
    return "\n".join(results)

# ==============================================================================
# PHASE 3: INTEGRATION (The Writer)
# Use these tools to safely write changes and submit them.
# ==============================================================================

@mcp.tool()
async def initialize_workspace(ctx: Context, owner: str, repo: str, base_branch: str = "main") -> str:
    """
    Step 5: Creates a new branch for the documentation work.
    API Calls: GET /git/ref/heads/{base}, POST /git/refs

    IMPORTANT: When the user asks to document a file of source code within
    a project or github repository, get_repository_map represents the first 
    tool in the cronilogical order of operations. To provide the best results
    and get the most context about the source code for documentation, follow 
    tools that have steps 1-7 to fully complete the task.
    """
    token = validate_header_token(ctx)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    
    # Generate a unique branch name (timestamp based ideally, or fixed for simplicity)
    import time
    new_branch = f"docs/update-{int(time.time())}"
    
    async with httpx.AsyncClient() as client:
        # 1. Get SHA of base branch to know where to start from
        ref_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{base_branch}", headers=headers)
        
        # Explicit error checking (e.g., if 'main' doesn't exist or access denied)
        if ref_resp.status_code != 200:
            return f"Failed to find base branch '{base_branch}': {parse_github_error(ref_resp)}"
        
        base_sha = ref_resp.json()["object"]["sha"]
        
        # 2. Create new branch pointing to that SHA
        create_resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{new_branch}", "sha": base_sha},
            headers=headers
        )
        
        if create_resp.status_code == 201:
            return f"Workspace initialized. Created branch: '{new_branch}'"
        
        # If branch creation fails (e.g., already exists or protected), explain why
        return f"Error creating branch: {parse_github_error(create_resp)}"

@mcp.tool()
async def commit_file_update(ctx: Context, owner: str, repo: str, branch: str, path: str, new_content: str, original_sha: str, message: str) -> str:
    """
    Step 6: Writes the documented code to the file.
    API Call: PUT /contents/{path}

    IMPORTANT: When the user asks to document a file of source code within
    a project or github repository, get_repository_map represents the first 
    tool in the cronilogical order of operations. To provide the best results
    and get the most context about the source code for documentation, follow 
    tools that have steps 1-7 to fully complete the task.
    """
    token = validate_header_token(ctx)
    # GitHub API requires content to be Base64 encoded
    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    
    payload = {
        "message": message,
        "content": encoded,
        "branch": branch,
        "sha": original_sha  # Critical for concurrency safety (rejects if file changed elsewhere)
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        )
        
        if resp.status_code in [200, 201]:
            return f"File '{path}' successfully updated on branch '{branch}'."
        
        # Capture conflicts (409) or permission errors (403)
        return f"Update failed: {parse_github_error(resp)}"

@mcp.tool()
async def submit_review_request(ctx: Context, owner: str, repo: str, head_branch: str, title: str, body: str, base_branch: str = "main") -> str:
    """
    Step 7: Opens a Pull Request for the documentation.
    API Call: POST /pulls

    IMPORTANT: When the user asks to document a file of source code within
    a project or github repository, get_repository_map represents the first 
    tool in the cronilogical order of operations. To provide the best results
    and get the most context about the source code for documentation, follow 
    tools that have steps 1-7 to fully complete the task.
    """
    token = validate_header_token(ctx)
    payload = {"title": title, "body": body, "head": head_branch, "base": base_branch}
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        )
        
        if resp.status_code == 201:
            return f"Success! PR Created: {resp.json()['html_url']}"
        
        # Capture if PR already exists (422) or access denied
        return f"PR Creation failed: {parse_github_error(resp)}"

# --- Start the MCP server ---
if __name__ == "__main__":
    mcp.run()