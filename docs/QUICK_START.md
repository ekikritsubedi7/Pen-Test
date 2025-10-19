# PentestGPT Quick Start Guide

This guide walks you through preparing a local environment, configuring credentials, validating the installation, and launching PentestGPT for the first time.

## 1. Prerequisites

- **Python**: 3.10 – 3.12 (the project is routinely tested on Python 3.11)
- **Git**: required to clone the repository or install from source
- **OpenAI (or compatible) API access**: PentestGPT relies on an LLM backend
- Optional services:
  - [Langfuse](https://langfuse.com/) for telemetry and experiment tracking
  - [Ollama](https://ollama.ai/) for local model execution

> ℹ️ **Offline environments**: If you work behind a proxy or without public internet access, make sure the required wheels are present in your package cache before installing. Otherwise `pip` cannot retrieve them.

## 2. Clone and install

```bash
# Clone
git clone https://github.com/GreyDGL/PentestGPT.git
cd PentestGPT

# Create an isolated environment (recommended)
python -m venv .venv
source .venv/bin/activate  # Linux / macOS
.venv\Scripts\activate    # Windows PowerShell

# Install PentestGPT in editable mode
pip install --upgrade pip
pip install -e .
```

If your environment already provides some dependencies (for example through a company mirror), you can skip installation of optional extras:

```bash
pip install -e . --no-deps
pip install -r requirements.txt  # or an internal mirror with equivalent packages
```

## 3. Configure credentials

Set the API keys for the providers you plan to use:

```bash
export OPENAI_API_KEY="sk-..."          # OpenAI or compatible endpoint
export OPENAI_BASEURL="https://api.openai.com/v1"  # Optional override
export GOOGLE_API_KEY="..."              # Gemini support (optional)
export DEEPSEEK_API_KEY="..."            # Deepseek support (optional)
export LANGFUSE_PUBLIC_KEY="..."         # Langfuse telemetry (optional)
export LANGFUSE_SECRET_KEY="..."         # Langfuse telemetry (optional)
```

For Ollama-based local models, ensure the Ollama daemon is running and configure:

```bash
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="llama3.1:latest"
```

## 4. Validate your installation

Run the built-in diagnostics to verify that the CLI resolves and a model is reachable:

```bash
# Confirm the package exposes CLI entry points
pentestgpt --help

# Validate OpenAI connectivity
pentestgpt-connection
```

If the connection test fails, double-check the API key, base URL, and proxy settings. Errors are logged to `logs/chatgpt_connection_test.log` for further inspection.

## 5. Run the automated tests

Before making changes, confirm the local test suite passes:

```bash
pytest
```

The tests use mocks and do not call external APIs, so they are safe to run in CI and offline environments.

## 6. Launch PentestGPT

With credentials configured, start an interactive session:

```bash
# Default GPT-4o workflow
pentestgpt

# Explicit reasoning/parsing model selection
pentestgpt --reasoning o3 --parsing gpt-4o

# Target a local Ollama model
pentestgpt --ollama llama3.1:latest
```

Logs are stored in the `logs/` directory. Review them for troubleshooting or auditing purposes.

## 7. Next steps

- Explore the [design document](../PentestGPT_design.md) for architectural details
- Configure Langfuse or other observability tooling for production deployments
- Review the `benchmark/` pipeline to measure task performance

Happy testing!
