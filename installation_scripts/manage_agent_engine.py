#!/usr/bin/env python3
"""
Simplified Agent Engine Management Script
Focused on OneMCP SecOps Agent with OAuth Passthrough
"""

import os
import sys
import importlib
from pathlib import Path
from typing import Optional, List

import typer
import vertexai
from google.cloud import aiplatform
from google.cloud import aiplatform_v1beta1
from google.protobuf import field_mask_pb2
from vertexai.preview.reasoning_engines import ReasoningEngine, AdkApp
from dotenv import load_dotenv
import logging

app = typer.Typer(help="Manage OneMCP SecOps Agent Engine instances.")

def setup_vertex_ai():
    """Initialize Vertex AI from environment."""
    load_dotenv()
    project = os.environ.get("GCP_PROJECT_ID")
    location = os.environ.get("GCP_LOCATION", "us-central1")
    staging_bucket = os.environ.get("GCP_STAGING_BUCKET")

    if not project:
        typer.secho("Error: GCP_PROJECT_ID not set in .env", fg=typer.colors.RED)
        raise typer.Exit(1)

    vertexai.init(project=project, location=location, staging_bucket=staging_bucket)
    aiplatform.init(project=project, location=location, staging_bucket=staging_bucket)
    return project, location

@app.command()
def deploy(
    agent_module: str = typer.Option("agent", help="Module containing create_agent()"),
    description: str = typer.Option("OneMCP SecOps Agent with OAuth Passthrough", help="Agent description"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    run_test: bool = typer.Option(True, "--test/--no-test", help="Run a test query after deployment"),
):
    """Deploy a new Agent Engine instance."""
    setup_vertex_ai()
    
    if debug:
        os.environ["DEBUG"] = "True"
        typer.echo("Debug logging enabled")

    typer.echo(f"Deploying agent from module: {agent_module}")
    agent = load_agent(agent_module)
    
    # Wrap agent in AdkApp as required by Reasoning Engines
    # Environment variables are passed here so they are pickled with the app
    app_instance = AdkApp(agent=agent, env_vars=get_env_vars())
    
def get_env_vars():
    """Collect environment variables for injection."""
    env_vars = {
        "CHRONICLE_PROJECT_ID": os.environ.get("CHRONICLE_PROJECT_ID"),
        "CHRONICLE_CUSTOMER_ID": os.environ.get("CHRONICLE_CUSTOMER_ID"),
        "CHRONICLE_REGION": os.environ.get("CHRONICLE_REGION"),
        "GEMINI_AUTHORIZATION_ID": os.environ.get("GEMINI_AUTHORIZATION_ID"),
        "OAUTH_AUTH_ID": os.environ.get("OAUTH_AUTH_ID"),
        "GOOGLE_CLOUD_PROJECT": os.environ.get("GCP_PROJECT_ID"),
        "DEBUG": os.environ.get("DEBUG", "False"),
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
        "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "32768",
    }
    # Remove None values
    return {k: v for k, v in env_vars.items() if v is not None}

def get_requirements():
    """Return the list of requirements for the Reasoning Engine."""
    return [
        "google-adk~=1.27.4",
        "google-cloud-aiplatform[agent-engines,evaluation]~=1.143.0",
        "pydantic",
        "python-dotenv",
        "opentelemetry-sdk",
        "opentelemetry-instrumentation-google-genai",
        "opentelemetry-exporter-gcp-logging",
        "mcp>=1.0.0",
        "gcsfs>=2024.11.0",
        "google-cloud-logging>=3.12.0",
        "protobuf>=6.31.1",
        "google-genai",
    ]

@app.command()
def deploy(
    agent_module: str = typer.Option("agent", help="Module containing create_agent()"),
    description: str = typer.Option("OneMCP SecOps Agent with OAuth Passthrough", help="Agent description"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    run_test: bool = typer.Option(True, "--test/--no-test", help="Run a test query after deployment"),
):
    """Deploy a new Agent Engine instance."""
    setup_vertex_ai()
    
    if debug:
        os.environ["DEBUG"] = "True"
        typer.echo("Debug logging enabled")

    typer.echo(f"Deploying agent from module: {agent_module}")
    agent = load_agent(agent_module)
    
    # Wrap agent in AdkApp as required by Reasoning Engines
    # Environment variables are passed here so they are pickled with the app
    app_instance = AdkApp(agent=agent, env_vars=get_env_vars())
    
    try:
        remote_app = ReasoningEngine.create(
            reasoning_engine=app_instance,
            display_name=f"SecOps Agent - {agent_module}",
            description=description,
            requirements=get_requirements(),
            extra_packages=["secops_agent"],
        )
        try:
            # Manually add framework metadata and telemetry env vars since SDK creation is missing support (ref: issue #6267)
            client_options = {"api_endpoint": f"{os.environ.get('GCP_LOCATION', 'us-central1')}-aiplatform.googleapis.com"}
            client = aiplatform_v1beta1.ReasoningEngineServiceClient(client_options=client_options)
            
            # Fetch existing to safely merge env vars
            existing_engine = client.get_reasoning_engine(name=remote_app.resource_name)
            
            env_vars_to_add = {
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
                "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
                "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "32768",
                "GEMINI_AUTHORIZATION_ID": os.environ.get("GEMINI_AUTHORIZATION_ID"),
            }
            existing_envs = {e.name: e for e in existing_engine.spec.deployment_spec.env}
            for k, v in env_vars_to_add.items():
                existing_envs[k] = aiplatform_v1beta1.EnvVar(name=k, value=v)
            
            new_spec = aiplatform_v1beta1.ReasoningEngineSpec(
                agent_framework="google-adk",
                deployment_spec=aiplatform_v1beta1.ReasoningEngineSpec.DeploymentSpec(
                    env=list(existing_envs.values())
                )
            )

            # Use field mask to only update the framework spec and env
            update_mask = field_mask_pb2.FieldMask(paths=["spec.agent_framework", "spec.deployment_spec.env"])
            reasoning_engine_resource = aiplatform_v1beta1.ReasoningEngine(
                name=remote_app.resource_name,
                spec=new_spec
            )
            
            typer.echo("Tagging engine as 'google-adk' and applying telemetry vars...")
            client.update_reasoning_engine(
                reasoning_engine=reasoning_engine_resource, 
                update_mask=update_mask
            ).result()
            typer.secho("Tagging successful!", fg=typer.colors.GREEN)
        except Exception as label_err:
            typer.secho(f"Warning: Failed to add ADK labels: {label_err}", fg=typer.colors.YELLOW)

        typer.secho(f"\nDeployment successful!", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Resource Name: {remote_app.resource_name}")
        
        if run_test:
            typer.echo("\nRunning smoke test...")
            try:
                response = remote_app.query(input="Hello")
                typer.echo(f"Test response: {response}")
            except Exception as test_err:
                typer.secho(f"Warning: Smoke test failed: {test_err}", fg=typer.colors.YELLOW)

    except Exception as e:
        typer.secho(f"\nDeployment failed: {e}", fg=typer.colors.RED)
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)

@app.command()
def create(
    agent_module: str = typer.Option("agent", help="Module containing create_agent()"),
    description: str = typer.Option("OneMCP SecOps Agent with OAuth Passthrough", help="Agent description"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    run_test: bool = typer.Option(True, "--test/--no-test", help="Run a test query after deployment"),
):
    """Create a new Agent Engine instance (alias for deploy)."""
    deploy(agent_module=agent_module, description=description, debug=debug, run_test=run_test)

@app.command()
def update(
    agent_module: str = typer.Option("agent", help="Module containing create_agent()"),
    description: str = typer.Option(None, help="Updated agent description"),
):
    """Update an existing Agent Engine instance in-place."""
    setup_vertex_ai()
    resource_name = os.environ.get("AGENT_ENGINE_RESOURCE_NAME")
    
    if not resource_name:
        typer.secho("Error: AGENT_ENGINE_RESOURCE_NAME not set in .env", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"Updating agent {resource_name} from module: {agent_module}")
    agent = load_agent(agent_module)
    
    # Wrap agent in AdkApp as required by Reasoning Engines
    # Environment variables are passed here so they are pickled with the app
    app_instance = AdkApp(agent=agent, env_vars=get_env_vars())
    
    try:
        engine = ReasoningEngine(resource_name)
        remote_app = engine.update(
            reasoning_engine=app_instance,
            display_name=f"SecOps Agent - {agent_module}",
            description=description,
            requirements=get_requirements(),
            extra_packages=["secops_agent"],
        )
        try:
            # Manually add framework metadata and telemetry env vars since SDK creation is missing support (ref: issue #6267)
            client_options = {"api_endpoint": f"{os.environ.get('GCP_LOCATION', 'us-central1')}-aiplatform.googleapis.com"}
            client = aiplatform_v1beta1.ReasoningEngineServiceClient(client_options=client_options)
            
            # Fetch existing to safely merge env vars
            existing_engine = client.get_reasoning_engine(name=remote_app.resource_name)
            
            env_vars_to_add = {
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
                "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
                "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "32768",
                "GEMINI_AUTHORIZATION_ID": os.environ.get("GEMINI_AUTHORIZATION_ID"),
            }

            existing_envs = {e.name: e for e in existing_engine.spec.deployment_spec.env}
            for k, v in env_vars_to_add.items():
                existing_envs[k] = aiplatform_v1beta1.EnvVar(name=k, value=v)
            
            new_spec = aiplatform_v1beta1.ReasoningEngineSpec(
                agent_framework="google-adk",
                deployment_spec=aiplatform_v1beta1.ReasoningEngineSpec.DeploymentSpec(
                    env=list(existing_envs.values())
                )
            )

            typer.echo(f"updating env vars: {existing_envs}")

            # Use field mask to only update the framework spec and env
            update_mask = field_mask_pb2.FieldMask(paths=["spec.agent_framework", "spec.deployment_spec.env"])
            reasoning_engine_resource = aiplatform_v1beta1.ReasoningEngine(
                name=remote_app.resource_name,
                spec=new_spec
            )
            
            typer.echo("Refreshed ADK tags and telemetry vars...")
            client.update_reasoning_engine(
                reasoning_engine=reasoning_engine_resource, 
                update_mask=update_mask
            ).result()

        except Exception as label_err:
            typer.secho(f"Warning: Failed to update ADK labels: {label_err}", fg=typer.colors.YELLOW)

        typer.secho(f"\nUpdate successful!", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Resource Name: {remote_app.resource_name}")
    except Exception as e:
        typer.secho(f"\nUpdate failed: {e}", fg=typer.colors.RED)
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)

@app.command()
def tag_as_adk(
    resource_name: str = typer.Option(None, help="Specific resource name to tag (defaults to .env value)"),
):
    """Manually tag the Reasoning Engine as an ADK-built agent to enable Cloud Console metrics."""
    setup_vertex_ai()
    name = resource_name or os.environ.get("AGENT_ENGINE_RESOURCE_NAME")
    
    if not name:
        typer.secho("Error: No resource name provided and AGENT_ENGINE_RESOURCE_NAME not set in .env", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        client_options = {"api_endpoint": f"{os.environ.get('GCP_LOCATION', 'us-central1')}-aiplatform.googleapis.com"}
        client = aiplatform_v1beta1.ReasoningEngineServiceClient(client_options=client_options)
        # Fetch existing to safely merge env vars
        existing_engine = client.get_reasoning_engine(name=name)
        
        env_vars_to_add = {
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
            "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "32768",
            "GEMINI_AUTHORIZATION_ID": os.environ.get("GEMINI_AUTHORIZATION_ID"),
        }
        existing_envs = {e.name: e for e in existing_engine.spec.deployment_spec.env}
        for k, v in env_vars_to_add.items():
            existing_envs[k] = aiplatform_v1beta1.EnvVar(name=k, value=v)
        
        new_spec = aiplatform_v1beta1.ReasoningEngineSpec(
            agent_framework="google-adk",
            deployment_spec=aiplatform_v1beta1.ReasoningEngineSpec.DeploymentSpec(
                env=list(existing_envs.values())
            )
        )

        update_mask = field_mask_pb2.FieldMask(paths=["spec.agent_framework", "spec.deployment_spec.env"])
        reasoning_engine_resource = aiplatform_v1beta1.ReasoningEngine(
            name=name,
            spec=new_spec
        )
        
        typer.echo(f"Tagging engine {name} as 'google-adk' and applying telemetry vars...")
        client.update_reasoning_engine(
            reasoning_engine=reasoning_engine_resource, 
            update_mask=update_mask
        )
        typer.secho("Tagging successful! Cloud Console metrics should now be available.", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"Tagging failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

@app.command(name="list")
def list_engines(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Detailed output"),
):
    """List all Agent Engine instances."""
    setup_vertex_ai()
    typer.echo("Listing Agent Engine instances...")
    
    try:
        engines = ReasoningEngine.list()
        if not engines:
            typer.echo("No Agent Engine instances found.")
            return
        
        for i, engine in enumerate(engines, 1):
            typer.echo(f"{i}. Resource: {engine.resource_name}")
            typer.echo(f"   Display Name: {engine.display_name}")
            if verbose:
                typer.echo(f"   Create Time: {engine.create_time}")
                typer.echo(f"   Update Time: {engine.update_time}")
                typer.echo(f"   Description: {getattr(engine, 'description', 'N/A')}")
            typer.echo("-" * 40)
    except Exception as e:
        typer.secho(f"Error listing engines: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

@app.command()
def delete(
    index: Optional[int] = typer.Option(None, help="Index of the engine to delete (from list)"),
    resource: Optional[str] = typer.Option(None, help="Full resource name of the engine to delete"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt"),
):
    """Delete an Agent Engine instance."""
    setup_vertex_ai()
    
    target_engine = None
    if resource:
        try:
            target_engine = ReasoningEngine(resource)
        except Exception as e:
            typer.secho(f"Error: Could not find engine with resource name {resource}: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
    elif index is not None:
        try:
            engines = ReasoningEngine.list()
            if index < 1 or index > len(engines):
                typer.secho(f"Error: Invalid index {index}. Use 'list' to see valid indices.", fg=typer.colors.RED)
                raise typer.Exit(1)
            target_engine = engines[index - 1]
        except Exception as e:
            typer.secho(f"Error retrieving engine list: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
    else:
        typer.secho("Error: Must provide either --index or --resource", fg=typer.colors.RED)
        raise typer.Exit(1)

    if not force:
        if not typer.confirm(f"Are you sure you want to delete engine {target_engine.resource_name}?"):
            typer.echo("Cancelled.")
            return

    typer.echo(f"Deleting engine: {target_engine.resource_name}...")
    try:
        target_engine.delete()
        typer.secho("Deletion successful!", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Deletion failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

@app.command()
def test(
    input: str = typer.Option("Hello, who are you?", help="Test query input"),
):
    """Test the deployed agent engine."""
    setup_vertex_ai()
    resource_name = os.environ.get("AGENT_ENGINE_RESOURCE_NAME")
    if not resource_name:
        typer.secho("Error: AGENT_ENGINE_RESOURCE_NAME not set in .env", fg=typer.colors.RED)
        raise typer.Exit(1)
    
    typer.echo(f"Testing engine: {resource_name}")
    try:
        engine = ReasoningEngine(resource_name)
        response = engine.query(input=input)
        typer.echo(f"\nResponse: {response}")
        typer.secho("\nTest successful!", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"\nTest failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

@app.command()
def warmup():
    """Pre-warm MCP server connections to reduce cold start latency."""
    setup_vertex_ai()
    typer.echo("Pre-warming agent engine connections...")
    test(input="Warmup query - please initialize tools")

def load_agent(module_name: str):
    """Import and return the agent instance."""
    # Ensure the parent directory is in path for full package resolution
    root_path = os.path.abspath(os.getcwd())
    if root_path not in sys.path:
        sys.path.insert(0, root_path)
    
    # Auto-prefix the module name to align with the 'secops_agent.secops_agent_app' package
    if not module_name.startswith("secops_agent.secops_agent_app.") and "." not in module_name:
        module_name = f"secops_agent.secops_agent_app.{module_name}"

    # Mark that we are in a deployment context to help with pickling-safe init
    os.environ["REASONING_ENGINE_DEPLOYMENT"] = "True"
    
    try:
        module = importlib.import_module(module_name)
        if hasattr(module, "create_agent"):
            return module.create_agent()
        else:
            typer.secho(f"Error: Module '{module_name}' has no create_agent() function", fg=typer.colors.RED)
            raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Error loading agent module '{module_name}': {e}", fg=typer.colors.RED)
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)

if __name__ == "__main__":
    app()
