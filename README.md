# Register Kubernetes Agent

> ⚠️ **Pre-release — Not Supported**
> This script is currently undergoing testing and is not yet supported for production use. Functionality, configuration, and interfaces may change without notice. Use at your own risk.

This script registers an Octopus Kubernetes agent as a deployment target in an Octopus Space. The registered agent is a **space-level resource** available to all projects within that space.

---

## Repository Structure

```
.
├── .gitignore                  # Excludes populated .ini files and common artifacts
├── CHANGELOG.md
├── README.md
├── config.example.ini          # Template — copy and rename per target space
├── dvb-finance-1.ini           # Example populated config (git-ignored)
├── requirements.txt            # No third-party deps; Python 3.10+ required
└── register_k8s_agent.py       # Registration script
```

Config files follow the naming convention `<space-or-cluster-name>.ini`. Only `config.example.ini` is committed — all populated configs are git-ignored.

---

## Prerequisites

- The Octopus Kubernetes agent must already be installed in your cluster via the agent Helm chart. The chart populates a ConfigMap with the `Uri` and `Thumbprint` values required for registration:
  ```bash
  kubectl get cm -n octopus-agent tentacle-config -o yaml
  ```
- Python 3.10+ available on the machine or worker running the script. No third-party packages are required.
- An API key with **Space Manager** (or higher) permissions in the target space.

---

## Running the Script

The script supports two configuration modes depending on how it is invoked. The mode is detected automatically based on whether the `AGENT_REG_CONFIG` environment variable is set.

### Option 1 — Octopus Cloud Built-in Dynamic Worker *(easiest for cloud)*

If your space is on Octopus Cloud, the built-in worker pool provides on-demand Ubuntu workers that include Python 3. No infrastructure setup is required.

1. Create a **Runbook** in any project in the space.
2. Add a **Run a Script** step set to run on the **Default Worker Pool**.
3. Set the language to **Python** and paste in `register_k8s_agent.py`.
4. Define the `AgentRegistration.*` variables listed in the [Octopus Variables](#octopus-variables) section on the project.
5. Run the runbook.

### Option 2 — Octopus Server *(self-hosted only)*

The script step can be configured to run directly on the Octopus Server without any worker or target.

1. Follow the same runbook setup as Option 1.
2. Set the step execution location to **Run on the Octopus Server**.
3. Ensure Python 3.10+ is installed on the server.

> ⚠️ Running arbitrary scripts on the Octopus Server is generally discouraged in production. Prefer Option 1 or 3 where possible.

### Option 3 — External Worker *(recommended for self-hosted)*

Register a standalone Tentacle (VM or container) as a **Worker** in a worker pool before running the runbook. Workers are space-level resources independent of deployment targets, sidestepping the bootstrap problem cleanly.

1. Install and register a Tentacle as a worker in the target space.
2. Ensure Python 3.10+ is installed on the worker machine.
3. Follow the same runbook setup as Option 1, targeting your worker pool.

### Option 4 — Run Locally *(best for bootstrapping a new space)*

Run the script directly from any machine with Python 3 using a `.ini` config file. No Octopus runbook is needed.

**Setup:**

1. Copy `config.example.ini` to a new file named for your target, e.g.:
   ```bash
   cp config.example.ini dvb-finance-1.ini
   ```
2. Edit the new file and fill in all values. See [Config File Reference](#config-file-reference) below.
3. Set your API key as an environment variable (**do not put it in the file**):
   ```bash
   export AGENT_REG_APIKEY="API-xxxxxxxxxxxx"
   ```
4. Point the script at your config file:
   ```bash
   export AGENT_REG_CONFIG=dvb-finance-1.ini
   ```
5. Run the script:
   ```bash
   python register_k8s_agent.py
   ```

To switch targets, just change the `AGENT_REG_CONFIG` value — your per-space config files can all live alongside each other:

```
config.example.ini       ← template, never edited
dvb-finance-1.ini
dvb-health-pilot.ini
dvb-presales-sandbox.ini
```

### Option 5 — Octopus CLI or curl *(one-off / no Python required)*

For a truly one-off registration, call the Octopus REST API directly without running the script at all.

```bash
curl -X POST "https://your-instance.octopus.app/api/Spaces-1/machines" \
  -H "X-Octopus-ApiKey: API-xxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "Name": "my-k8s-agent",
    "MachinePolicyId": "MachinePolicies-1",
    "IsDisabled": false,
    "EnvironmentIds": ["Environments-1"],
    "Roles": ["k8s-agent"],
    "TenantedDeploymentParticipation": "Untenanted",
    "TenantIds": [],
    "TenantTags": [],
    "Endpoint": {
      "CommunicationStyle": "KubernetesTentacle",
      "TentacleEndpointConfiguration": {
        "CommunicationMode": "Polling",
        "Thumbprint": "YOUR_THUMBPRINT",
        "Uri": "poll://your-agent-uri/"
      }
    }
  }'
```

Use the Octopus REST API to look up `MachinePolicyId` and `EnvironmentIds` first, or retrieve them from **Infrastructure** in the Octopus UI.

---

## Config File Reference

Used in **Option 4** only. Copy `config.example.ini` and edit for each target space.

| Section | Key | Required | Description |
|---|---|---|---|
| `[octopus]` | `ServerUri` | ✅ | Base URL of your Octopus server |
| `[octopus]` | `SpaceId` | ✅ | Space ID, e.g. `Spaces-1` |
| `[agent]` | `Name` | ✅ | Display name in Infrastructure > Deployment Targets |
| `[agent]` | `Uri` | ✅ | Polling URI from the agent ConfigMap |
| `[agent]` | `Thumbprint` | ✅ | Certificate thumbprint from the agent ConfigMap |
| `[agent]` | `EnvironmentNames` | ✅ | Comma-separated environment names, e.g. `Development,Test` |
| `[agent]` | `Roles` | ✅ | Comma-separated target roles, e.g. `k8s-agent` |
| `[agent]` | `WorkerPoolName` | ❌ | Worker pool to also assign the agent to. Leave blank to skip. |
| `[agent]` | `ApiKey` | ⚠️ | Last resort only — prefer `AGENT_REG_APIKEY` env var. |

### API Key Security

The `AGENT_REG_APIKEY` environment variable is always checked first. The `ApiKey` field in the config file is only used as a fallback and the script will emit a warning if it is used. Recommended approaches for setting the env var securely:

- **macOS/Linux:** Add to your shell profile, a `.env` file sourced before running, or a secrets manager such as 1Password CLI (`op run --env-file=...`)
- **WSL2:** Add to `~/.bashrc` or `~/.zshrc`, but consider using a `.env` file excluded from version control instead
- **CI/GitHub Actions:** Store as an encrypted secret and inject via `env:`

Never commit a config file containing an API key to version control. Add your populated `.ini` files to `.gitignore`:

```
# .gitignore
*.ini
!config.example.ini
```

---

## Octopus Variables

Used in **Options 1–3** when the script runs inside an Octopus runbook step. Define these on the host project.

| Variable | Required | Sensitive | Description |
|---|---|---|---|
| `AgentRegistration.ApiKey` | ✅ | ✅ | API key with Space Manager or higher permissions |
| `AgentRegistration.Agent.Name` | ✅ | ❌ | Display name for the agent |
| `AgentRegistration.Agent.Uri` | ✅ | ❌ | Polling URI from the agent ConfigMap |
| `AgentRegistration.Agent.Thumbprint` | ✅ | ❌ | Certificate thumbprint from the agent ConfigMap |
| `AgentRegistration.Agent.EnvironmentNames` | ✅ | ❌ | Comma-separated environment names |
| `AgentRegistration.Agent.Roles` | ✅ | ❌ | Comma-separated target roles |
| `AgentRegistration.Agent.WorkerPoolName` | ❌ | ❌ | Worker pool name. Leave unset to skip. |

The following are Octopus built-in variables provided automatically at runtime:

| Variable | Description |
|---|---|
| `Octopus.Space.Id` | ID of the space the runbook executes in |
| `Octopus.Web.ServerUri` | Base URL of the Octopus server |

---

## Re-running the Script

The script does not check for an existing agent with the same name before registering. Running it a second time will create a **duplicate** deployment target. Remove the existing target from **Infrastructure → Deployment Targets** before re-running, or extend the script with a pre-flight lookup against `GET /api/{spaceId}/machines?name=<agentName>`.