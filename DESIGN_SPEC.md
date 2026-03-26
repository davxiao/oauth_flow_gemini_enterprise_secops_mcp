# DESIGN_SPEC.md

## Overview
This ADK Agent is the simplest possible implementation connecting to the Google Cloud Remote MCP Server for SecOps. It acts as a security operations assistant that leverages managed SecOps tools via the MCP protocol. It is designed to be deployed on Vertex AI Agent Engine and integrated with Gemini Enterprise, utilizing OAuth passthrough to authenticate requests to the remote SecOps MCP endpoint as the logged-in end-user.

## Example Use Cases
- **List Cases**: User asks "Show me recent cases". The agent calls the SecOps MCP `list_cases` tool and summarizes the active cases using the user's specific credentials.
- **Search Events**: User asks "Search UDM events for IP 1.2.3.4". The agent uses the `udm_search` tool from the SecOps MCP server.

## Tools Required
- **McpToolset**: Specifically connected via streaming HTTP to the Google Cloud Remote MCP Server for SecOps (`https://chronicle.[REGION].rep.googleapis.com/mcp`). 
  - **Authentication**: Uses Gemini Enterprise managed OAuth passthrough.
  - **Context Variables**: Project ID, Customer ID, and Region are used to target the correct SecOps tenant.

## Constraints & Safety Rules
- The agent must rely exclusively on the SecOps MCP server for its security operations capabilities.
- The agent must not log sensitive entity details (like raw credentials or tokens) in standard text output.
- The agent must use Vertex AI Agent Engine best practices, meaning no local session type should be explicitly configured in the code.

## Success Criteria
- The agent successfully initializes and connects to the remote SecOps MCP endpoint.
- The agent can execute a standard tool (e.g., `list_cases` or `udm_search`) when queried.
- The user's identity is correctly passed from Gemini Enterprise through Agent Engine to the MCP server.

## Edge Cases to Handle
- **Missing Configuration**: The agent should fail gracefully or inform the user if the SecOps Region, Project ID, or Customer ID are not set in the environment.
- **Authentication Errors**: If the user is not logged in or the token is missing from the state, the agent should inform the user that a sign-in is required via the Gemini Enterprise interface.

## Design Considerations: Gemini Enterprise OAuth Passthrough

This agent implements **OAuth Passthrough** specifically for the Gemini Enterprise ecosystem. This is a "hard requirement" to ensure that users act strictly as themselves and only access SecOps data they are entitled to.

### Architecture
1.  **Authorization Resource**: An OAuth configuration is registered in Google Cloud (Discovery Engine) as an "Authorization" resource. This configuration includes the Client ID, Secret, and the `https://www.googleapis.com/auth/chronicle` scope.
2.  **Registration**: The Agent Engine agent is registered with Gemini Enterprise using the `make register-gemini-enterprise` command, passing the `--authorization-id` of the resource created in step 1.
3.  **UI Orchestration**: When a user interacts with the agent in Gemini Enterprise, the Gemini UI detects the authorization requirement. It pauses the interaction, spawns the Google Sign-In flow, and captures the user's OAuth token.
4.  **Token Handoff**: Gemini Enterprise passes this token to the Vertex AI Agent Engine in the `authorizations` block of the request.
5.  **State Injection**: The Agent Engine runtime automatically injects this token into the agent's session state (`tool_context.state`), keyed by the registered Authorization ID.
6.  **Header Provider**: The agent's `McpToolset` uses a custom `header_provider` function (`get_secops_headers`). This function extracts the token from the state and adds it as a `Bearer` token to the `Authorization` header of the MCP connection request.

### Implementation Note
The agent does **not** use the ADK's interactive `auth_scheme` (the `adk_request_credential` loop) because Gemini Enterprise orchestrates the login flow externally before invoking the agent. Instead, the agent consumes the pre-authorized token provided in the session context.
