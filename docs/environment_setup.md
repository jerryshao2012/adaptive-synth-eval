# Environment Setup

This guide covers local dependencies, model-provider credentials, AWS Bedrock AgentCore prerequisites, and network-specific configuration. Contract field definitions and target-mode schemas remain canonical in [Simulation contracts](contracts.md).

## Local setup

ASE requires Python 3.11 or later and uses `uv` for dependency management.

```bash
cp src/.env.example src/.env
uv sync
uv run ase --help
```

`src/.env` is loaded for local CLI runs. Do not commit credentials. Use `--dry-run` until both harness-side model providers and live target credentials are configured.

On Windows, a repository stored in OneDrive can cause hard-link errors from `uv` (including OS error 396). Use copy mode for that shell:

```powershell
$env:UV_LINK_MODE = "copy"
uv sync
uv run ase --help
```

The repository also sets `tool.uv.link-mode = "copy"`, but the environment override is useful with older tooling or inherited configuration.

## Model-provider credentials

Provider selection and authentication differ between the unified runner and the environment-driven client used by monitoring. Keep secrets in environment variables rather than contract YAML.

### Unified contract components

Unified planner, generator, judge, policy, and user-simulator providers are selected by the top-level `llm` block and optional component overrides. See [Simulation contracts](contracts.md) for the provider-block schema and precedence.

- `claude` and `openai` read the API-key environment variable named by `api_key_env`, defaulting to `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` respectively.
- `azure-openai` uses an API-key client. It reads the endpoint, deployment, and API version from the contract (with Azure environment fallbacks) and reads `AZURE_OPENAI_API_KEY` unless `api_key_env` names another variable. This unified provider does not use the managed-identity path.
- `bedrock` uses the native `boto3` Bedrock Runtime client and its standard IAM credential chain, such as environment credentials, an AWS profile or SSO session, or an attached workload role. Set the region in the contract; otherwise the unified factory falls back to `AWS_DEFAULT_REGION`, then `us-east-1`.
- `ollama` reads the model from the contract's `model` field and the base URL from the contract or `OLLAMA_BASE_URL`.

### Monitoring and the legacy simulator client

`ase monitor run` does not read unified contract provider blocks. Its `LLMClient` selects and configures the evaluator from environment variables. The legacy synth simulator uses the same client behavior when its optional `llm` configuration does not override those values.

| Provider | Environment-based client configuration |
| --- | --- |
| Azure OpenAI | `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`, plus `AZURE_OPENAI_API_KEY`; alternatively, `AZURE_AUTH_TYPE=managed_identity` with optional `AZURE_CLIENT_ID` and `AZURE_OPENAI_SCOPE` |
| Anthropic | `ANTHROPIC_API_KEY` and optional `MODEL_NAME` |
| OpenAI | `OPENAI_API_KEY` and optional `MODEL_NAME` |
| Ollama | `OLLAMA_BASE_URL` (or `OLLAMA_API_BASE`) and optional `MODEL_NAME` |
| Bearer-token Bedrock | `AWS_BEARER_TOKEN_BEDROCK`, optional `AWS_REGION`, optional `AWS_BEDROCK_ENDPOINT`, and optional `MODEL_NAME` |

The environment-client Bedrock path is an OpenAI-compatible bearer-token client whose default URL is the regional Bedrock Mantle endpoint; it is different from the unified runner's native `boto3` Bedrock Runtime path.

The checked-in `src/.env.example` is the starting template. It currently shows `OLLAMA_MODEL`, but `clients/llm.py` consumes `MODEL_NAME`; until that implementation/template mismatch is resolved, set `MODEL_NAME` for monitoring and the legacy environment-based client. Unified Ollama components continue to use the contract's `model` field.

For an authenticated HTTP target, set the environment variable named by `target.auth.env_var` in the contract (the examples commonly use `CHATBOT_API_TOKEN`). Browser and AgentCore targets use their own session and AWS identity mechanisms. Configure target fields in [Simulation contracts](contracts.md) rather than duplicating them here.

## AWS Bedrock AgentCore targets

AgentCore target mode invokes a deployed runtime through AWS credentials available to `boto3`. The Python dependencies are installed by `uv sync`; separately install and authenticate the AWS CLI if you use its setup commands.

Configure credentials using your organization's approved method, such as an AWS profile, SSO session, workload identity, or environment credentials. For a local access-key profile:

```bash
aws configure
aws sts get-caller-identity
```

Before a live run, confirm:

- the active identity can invoke the deployed AgentCore runtime;
- the AWS region matches the runtime;
- the runtime ARN is available through the environment variable referenced by the contract, such as `TFSA_AGENT_RUNTIME_ARN`;
- any endpoint qualifier and request payload settings are declared in the contract.

Use the target schema and authentication notes in [Simulation contracts](contracts.md#agentcore-target). Checked-in execution examples include:

- [TFSA AgentCore without reasoning](../contracts/examples/tfsa_aws_unified_evaluation_no_reasoning.yaml)
- [TFSA AgentCore with reasoning](../contracts/examples/tfsa_aws_unified_evaluation_reasoning.yaml)

Validate and dry-run the selected contract before invoking the runtime:

```bash
uv run ase validate-contract contracts/examples/tfsa_aws_unified_evaluation_no_reasoning.yaml
uv run ase run --contract contracts/examples/tfsa_aws_unified_evaluation_no_reasoning.yaml --dry-run
```

## Corporate CA and TLS configuration

Corporate TLS inspection may require a trusted CA bundle. Obtain the CA file from your IT or security team; do not disable verification as a permanent workaround.

Linux or macOS:

```bash
export SSL_CERT_FILE=/path/to/corporate-ca.pem
export REQUESTS_CA_BUNDLE=/path/to/corporate-ca.pem
export CURL_CA_BUNDLE=/path/to/corporate-ca.pem
```

Windows PowerShell:

```powershell
$env:SSL_CERT_FILE = "C:\path\to\corporate-ca.pem"
$env:REQUESTS_CA_BUNDLE = "C:\path\to\corporate-ca.pem"
$env:CURL_CA_BUNDLE = "C:\path\to\corporate-ca.pem"
```

AWS SDK calls can use a dedicated bundle:

```bash
export AWS_CA_BUNDLE=/path/to/corporate-ca.pem
```

For Git, configure the CA only if repository access also passes through the inspected connection:

```bash
git config --global http.sslCAInfo /path/to/corporate-ca.pem
```

ASE's HTTP clients also recognize `SSL_CAINFO`. Keep certificate paths readable by the account running scheduled jobs.

## Proxy configuration

Set standard proxy variables when outbound access requires a proxy:

```bash
export HTTP_PROXY="http://proxy.company.example:8080/"
export HTTPS_PROXY="http://proxy.company.example:8080/"
```

Windows PowerShell:

```powershell
$env:HTTP_PROXY = "http://proxy.company.example:8080/"
$env:HTTPS_PROXY = "http://proxy.company.example:8080/"
```

If credentials are required, URL-encode usernames and passwords before embedding them. Avoid storing proxy credentials in committed shell scripts. Some organizations provide credential helpers or unauthenticated local proxy endpoints instead.

## Networking troubleshooting

- **Certificate verification fails:** confirm the CA file exists, contains the complete trust chain, and is visible to the process. Check `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and provider-specific variables such as `AWS_CA_BUNDLE`.
- **Connection times out:** verify DNS, proxy host and port, firewall allow-lists, provider endpoint, and target endpoint. For slow dependency downloads, try `UV_HTTP_TIMEOUT=300` after confirming the network path.
- **Authentication fails:** use the provider's identity command where available (`aws sts get-caller-identity` for AWS), confirm the selected profile/tenant/subscription, and verify that the secret variable name matches the contract.
- **Ollama is unreachable:** confirm the service is running and `OLLAMA_BASE_URL` points to an address accessible from the ASE process.
- **Browser target cannot launch:** install Playwright's required browser, or ensure Microsoft Edge is installed when the contract selects the `edge` channel. Target selectors and browser fields are documented in [Simulation contracts](contracts.md#browser-target).
- **OneDrive hard-link errors on Windows:** set `UV_LINK_MODE=copy` and rerun `uv sync`.

After changing environment configuration, validate the contract and use a dry-run before making live calls.
