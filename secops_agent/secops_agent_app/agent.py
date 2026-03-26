import os
import google.auth
from google.adk.auth import AuthScheme, AuthCredential, AuthCredentialTypes, OAuth2Auth
from google.adk.agents import Agent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.genai import types

from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor
from dotenv import load_dotenv
import logging
import sys

def get_secops_headers(context) -> dict[str, str]:
    # Read from environment AT RUNTIME
    chronicle_project_id = os.environ.get("CHRONICLE_PROJECT_ID")
    customer_id = os.environ.get("CHRONICLE_CUSTOMER_ID")
    gemini_auth_id = os.environ.get("GEMINI_AUTHORIZATION_ID")
    region = os.environ.get("CHRONICLE_REGION", "us")

    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json"
    }
    
    # Only add the project header if we actually have a value
    if chronicle_project_id:
        headers["x-goog-user-project"] = chronicle_project_id
    else:
        # Critical for tool execution, though list_tools might still work
        logging.critical("CHRONICLE_PROJECT_ID is missing from environment! OneMCP tool calls *will* fail without a routing context.")

    if context and context.state and gemini_auth_id:
        user_token = context.state.get(gemini_auth_id)
        if user_token:
            headers["Authorization"] = f"Bearer {user_token}"
            # Log first few chars for debugging without leaking full sensitive token in recap
            logging.info(f"DEBUG: Tool Call Auth Header present (starts with: {user_token[:10]}...)")
            
    return headers

def create_mcp_toolset(region) -> McpToolset:
    # Matching working example pattern: https://chronicle.{region}.rep.googleapis.com/mcp
    secops_mcp_url = f"https://chronicle.{region}.rep.googleapis.com/mcp"
    
    logging.info(f"Initializing MCP Toolset with URL: {secops_mcp_url}")
    
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=secops_mcp_url),
        header_provider=get_secops_headers,
        errlog=None # explicitly None to prevent sys.stderr capturing (which cannot be pickled)
    )

def create_agent():
    load_dotenv()
    
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id and os.environ.get("REASONING_ENGINE_DEPLOYMENT") != "True":
        try:
            _, project_id = google.auth.default()
        except Exception:
            pass

    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id or ""
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

    if os.environ.get("REASONING_ENGINE_DEPLOYMENT") != "True":
         GoogleGenAiSdkInstrumentor().instrument()

    Agent.version = "1.0"
    os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "True"

    region = os.environ.get("CHRONICLE_REGION", "us")
    customer_id = os.environ.get("CHRONICLE_CUSTOMER_ID")
    chronicle_project_id = os.environ.get("CHRONICLE_PROJECT_ID")
    gemini_auth_id = os.environ.get("GEMINI_AUTHORIZATION_ID")

    secops_toolset = create_mcp_toolset(region)

    return Agent(
        name="secops_agent",
        model=Gemini(
            model="gemini-2.5-pro",
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        instruction=f"""You are a Google SecOps assistant. 
You have access to the remote SecOps MCP server which provides tools for SIEM and SOAR operations.
Always use the provided tools to fetch information from Chronicle.

Current Tenant Information:
- Project ID: {chronicle_project_id}
- Customer ID: {customer_id}
- Region: {region}

When calling tools, ensure you use these identifiers if the tool requires them.
""",
        tools=[secops_toolset],
    )
