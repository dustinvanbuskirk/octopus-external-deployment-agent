from __future__ import annotations

import configparser
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request


# ---------------------------------------------------------------------------
# Config Loading
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """
    Resolve all required settings from one of two sources:

    LOCAL MODE  — set AGENT_REG_CONFIG to a .ini file path:
                    export AGENT_REG_CONFIG=dvb-finance-1.ini
                  API key is read from AGENT_REG_APIKEY env var (preferred)
                  or from the [agent] ApiKey field in the file (last resort).

    OCTOPUS MODE — when AGENT_REG_CONFIG is not set the script reads the
                  standard Octopus-injected environment variables instead
                  (used when running inside an Octopus runbook step).
    """
    config_file = os.environ.get("AGENT_REG_CONFIG")

    if config_file:
        # ---- Local / config-file mode ----
        if not os.path.isfile(config_file):
            raise SystemExit(f"ERROR: Config file not found: {config_file}")

        print(f"Config mode: reading from '{config_file}'")
        parser = configparser.ConfigParser()
        parser.read(config_file)

        # API key: env var takes priority; file value is a fallback with warning.
        api_key = os.environ.get("AGENT_REG_APIKEY")
        if not api_key:
            api_key = parser.get("agent", "ApiKey", fallback=None)
            if api_key:
                print(
                    "WARNING: API key loaded from config file. "
                    "For better security set the AGENT_REG_APIKEY environment variable "
                    "and remove the ApiKey entry from the file."
                )
            else:
                raise SystemExit(
                    "ERROR: API key not found. Set the AGENT_REG_APIKEY environment "
                    "variable or add ApiKey to the [agent] section of your config file."
                )

        return {
            "base_url":           parser.get("octopus", "ServerUri").rstrip("/"),
            "api_key":            api_key,
            "space_id":           parser.get("octopus", "SpaceId"),
            "agent_name":         parser.get("agent", "Name"),
            "agent_uri":          parser.get("agent", "Uri"),
            "agent_thumbprint":   parser.get("agent", "Thumbprint"),
            "environment_names":  [e.strip() for e in parser.get("agent", "EnvironmentNames").split(",")],
            "role_names":         [r.strip() for r in parser.get("agent", "Roles").split(",")],
            "worker_pool_name":   parser.get("agent", "WorkerPoolName", fallback=""),
        }

    else:
        # ---- Octopus runbook mode ----
        print("Config mode: reading from Octopus environment variables")
        return {
            "base_url":           os.environ["Octopus.Web.ServerUri"].rstrip("/"),
            "api_key":            os.environ["AgentRegistration.ApiKey"],
            "space_id":           os.environ["Octopus.Space.Id"],
            "agent_name":         os.environ["AgentRegistration.Agent.Name"],
            "agent_uri":          os.environ["AgentRegistration.Agent.Uri"],
            "agent_thumbprint":   os.environ["AgentRegistration.Agent.Thumbprint"],
            "environment_names":  [e.strip() for e in os.environ["AgentRegistration.Agent.EnvironmentNames"].split(",")],
            "role_names":         [r.strip() for r in os.environ["AgentRegistration.Agent.Roles"].split(",")],
            "worker_pool_name":   os.environ.get("AgentRegistration.Agent.WorkerPoolName", ""),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_headers(api_key: str) -> dict:
    return {
        "X-Octopus-ApiKey": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _ssl_context() -> ssl.SSLContext:
    """
    Returns the default SSL context.
    If your Octopus server uses a self-signed cert, swap for:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    """
    return ssl.create_default_context()


def octopus_get_items(base_url: str, api_key: str, path: str) -> list:
    """Retrieve all pages of a collection from the Octopus REST API."""
    items = []
    skip = 0
    ctx = _ssl_context()

    while True:
        sep = "&" if "?" in path else "?"
        url = f"{base_url}{path}{sep}skip={skip}"
        req = urllib.request.Request(url, headers=_make_headers(api_key))

        with urllib.request.urlopen(req, context=ctx) as resp:
            data = json.loads(resp.read().decode())

        if "Items" not in data:
            return data

        items.extend(data["Items"])
        per_page = data.get("ItemsPerPage", len(data["Items"]))

        if len(data["Items"]) < per_page:
            break
        skip += per_page

    return items


def octopus_request(method: str, url: str, api_key: str, payload: dict = None) -> dict:
    """Execute an authenticated Octopus API request."""
    body = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=body,
        headers=_make_headers(api_key),
        method=method,
    )
    ctx = _ssl_context()
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read().decode())


def find_by_name(items: list, name: str) -> dict | None:
    return next((i for i in items if i.get("Name") == name), None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

cfg = load_config()

base_url         = cfg["base_url"]
api_key          = cfg["api_key"]
space_id         = cfg["space_id"]
agent_name       = cfg["agent_name"]
agent_uri        = cfg["agent_uri"]
agent_thumbprint = cfg["agent_thumbprint"]
environment_names = cfg["environment_names"]
role_names       = cfg["role_names"]
worker_pool_name = cfg["worker_pool_name"]


# ---------------------------------------------------------------------------
# Resolve Environments
# ---------------------------------------------------------------------------

print("Resolving environments...")
all_environments = octopus_get_items(base_url, api_key, f"/api/{space_id}/environments")
environment_ids = []

for name in environment_names:
    env = find_by_name(all_environments, name)
    if env:
        environment_ids.append(env["Id"])
        print(f"  Found: {name} ({env['Id']})")
    else:
        print(f"  WARNING: Environment '{name}' not found — skipping.")

if not environment_ids:
    raise SystemExit("ERROR: No valid environments resolved. Aborting.")


# ---------------------------------------------------------------------------
# Resolve Machine Policy
# ---------------------------------------------------------------------------

print("Resolving machine policy...")
policies = octopus_get_items(base_url, api_key, f"/api/{space_id}/machinepolicies")
machine_policy = find_by_name(policies, "Default Machine Policy")

if not machine_policy:
    raise SystemExit("ERROR: 'Default Machine Policy' not found. Aborting.")

print(f"  Found: Default Machine Policy ({machine_policy['Id']})")


# ---------------------------------------------------------------------------
# Resolve Worker Pool (optional)
# ---------------------------------------------------------------------------

worker_pool_id = None

if worker_pool_name:
    print(f"Resolving worker pool '{worker_pool_name}'...")
    pools = octopus_get_items(base_url, api_key, f"/api/{space_id}/workerPools")
    pool = find_by_name(pools, worker_pool_name)

    if pool:
        worker_pool_id = pool["Id"]
        print(f"  Found: {worker_pool_name} ({worker_pool_id})")
    else:
        print(f"  WARNING: Worker pool '{worker_pool_name}' not found — continuing without it.")


# ---------------------------------------------------------------------------
# Build Registration Payload
# ---------------------------------------------------------------------------

payload = {
    "Name": agent_name,
    "MachinePolicyId": machine_policy["Id"],
    "IsDisabled": False,
    "EnvironmentIds": environment_ids,
    "Roles": role_names,
    "TenantedDeploymentParticipation": "Untenanted",
    "TenantIds": [],
    "TenantTags": [],
    "Endpoint": {
        "CommunicationStyle": "KubernetesTentacle",
        "TentacleEndpointConfiguration": {
            "CommunicationMode": "Polling",
            "Thumbprint": agent_thumbprint,
            "Uri": agent_uri,
        },
    },
}

if worker_pool_id:
    payload["WorkerPoolIds"] = [worker_pool_id]


# ---------------------------------------------------------------------------
# Register Agent
# ---------------------------------------------------------------------------

print(f"\nRegistering Kubernetes agent '{agent_name}'...")

try:
    machine = octopus_request(
        "POST",
        f"{base_url}/api/{space_id}/machines",
        api_key,
        payload,
    )
    print(f"  Registered — Machine Id: {machine['Id']}")

except urllib.error.HTTPError as e:
    error_body = e.read().decode()
    print(f"  ERROR: HTTP {e.code} {e.reason}")
    print(f"  Response body: {error_body}")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Poll for Health Status
# ---------------------------------------------------------------------------

print("  Waiting for health check...")
max_attempts = 24   # 24 x 5s = 2 min timeout

for attempt in range(max_attempts):
    if machine.get("HealthStatus") != "Unknown":
        break
    time.sleep(5)
    try:
        machine = octopus_request(
            "GET",
            f"{base_url}{machine['Links']['Self']}",
            api_key,
        )
    except urllib.error.HTTPError as e:
        print(f"  WARNING: Health poll failed on attempt {attempt + 1}: HTTP {e.code}")

health = machine.get("HealthStatus", "Unknown")
print(f"  Health status: {health}")

if health not in ("Healthy", "HasWarnings"):
    print(f"  WARNING: Agent '{agent_name}' did not reach a healthy state (status: {health}).")
    raise SystemExit(1)

print(f"\nDone. Agent '{agent_name}' successfully registered and {health.lower()}.")