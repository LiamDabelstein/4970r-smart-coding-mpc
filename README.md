# 4970r-smart-coding-mpc-repo

This project implements a Model Context Protocol (MCP) server that acts as a bridge between Large Language Models (LLMs) and GitHub. It provides a structured, safe, and context-aware workflow for AI agents to analyze codebases and submit contributions.

Core Capabilities

    Secure Authentication: Implements the GitHub OAuth Device Flow to safely authenticate users without hardcoding credentials.

    Context Gathering: Tools to map repository structures (get_repository_map) and analyze tech stacks/dependencies (get_project_overview) before diving into code.

    Deep Inspection: Reads source code while simultaneously fetching commit history and associated Pull Request data to understand the intent behind the code.

    Safe Contribution Workflow: Enforces best practices by managing the full lifecycle of a code change:
        Creating a dedicated feature branch.
        Committing changes with safety checks (SHA verification).
        Automatically opening a Pull Request for human review.

Primary Use Case

While capable of general code editing, this server is optimized for automated documentation and refactoring tasks, allowing the AI to understand the full context of a file (imports, history, references) before proposing changes.

# 4970r-smart-coding-mpc GitHub App

The GitHub application found at https://github.com/apps/4970r-smart-coding-mpc
is needed to utilize the 4970r-smart-coding remote mcp server.

To install the mcp server and acquire your user access token:
1) Install the smart-coding remote mpc server in the client mcp configuration file, seen below.
2) Open up the mcp client and ask your LLM to log into GitHub.
3) Follow the guided steps to revive the user access token.
4) Re-update the mcp configuration file with the user access token.
5) You can now use the remote mcp server functionality as normal.

"smart-coding": {
    "command": "npx",
    "args": [
        "-y",
        "mcp-remote",
        "https://4970r-smart-coding.fastmcp.app/mcp",
        "--header",
        "User-Access-Token:${GITHUB_PERSONAL_ACCESS_TOKEN}"
    ],
    "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghu_YOUR_TOKEN_HERE"
}
