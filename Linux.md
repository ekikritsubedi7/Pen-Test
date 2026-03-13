# PentestGPT — Linux Setup & Usage Guide

AI-assisted penetration testing framework designed to help security researchers plan, execute, and document penetration tests using large language models.

This document focuses specifically on **Linux environments** such as:

* Kali Linux
* Ubuntu
* Debian
* Arch Linux

---

# Table of Contents

* Overview
* Features
* Architecture
* Requirements
* Installation
* Docker Setup
* Installing uv
* Cloning the Repository
* Installing Dependencies
* Configuration
* Running PentestGPT
* Example Usage
* Typical Pentesting Workflow
* Using Local LLMs
* Benchmark System
* Development Setup
* Troubleshooting
* Security Notice
* Contributing
* License

---

# Overview

PentestGPT is an AI-powered penetration testing assistant that helps security researchers perform and manage penetration tests more efficiently.

It uses large language models to:

* plan attack paths
* interpret scan results
* recommend tools
* guide exploitation steps
* organize penetration testing notes

PentestGPT does **not automatically exploit systems**. Instead, it acts as an **intelligent assistant** that helps testers reason through complex attack surfaces.

---

# Features

* AI-assisted penetration testing workflow
* Interactive testing sessions
* Context-aware reasoning
* Supports multiple LLM providers
* Works with local or cloud models
* Modular architecture
* Benchmark datasets for evaluation
* Designed for real-world penetration testing scenarios

---

# Architecture

### AI Interaction Layer

Handles communication between the application and the language model provider.

### Session Manager

Maintains conversation history and testing context.

### Prompt Engine

Builds structured prompts for different pentesting stages.

### Workflow Controller

Coordinates reconnaissance, enumeration, exploitation, and reporting stages.

### Benchmark Framework

Evaluates LLM performance on known security challenges.

---

# Requirements

Before installing PentestGPT on Linux, ensure the following tools are available:

* Python 3.10+
* Git
* Make
* Docker (recommended)
* pip

Required Python dependency manager:

* uv

Optional:

* Ollama (for running local AI models)

---

# Installation

## Update system packages

```bash
sudo apt update
sudo apt upgrade -y
```

## Install required tools

```bash
sudo apt install -y git python3 python3-pip make docker.io
```

---

# Docker Setup

Start Docker:

```bash
sudo systemctl start docker
```

Enable Docker at boot:

```bash
sudo systemctl enable docker
```

Add your user to the Docker group:

```bash
sudo usermod -aG docker $USER
```

Log out and log back in.

Verify Docker installation:

```bash
docker run hello-world
```

---

# Installing uv

PentestGPT uses uv for dependency management.

Install with pip:

```bash
pip install uv
```

Or install using the official installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify installation:

```bash
uv --version
```

---

# Cloning the Repository

```bash
git clone --recurse-submodules https://github.com/GreyDGL/PentestGPT.git
cd PentestGPT
```

The `--recurse-submodules` flag downloads benchmark datasets used for evaluation.

---

# Installing Dependencies

```bash
make install
```

This command will:

* create the Python virtual environment
* install required dependencies
* prepare runtime configuration

Installation may take several minutes depending on system speed.

---

# Configuration

```bash
make config
```

You will be asked to select a language model provider. Common options include:

* OpenAI
* Claude
* OpenRouter
* Local models

After configuration completes, the system will store the settings locally.

---

# Running PentestGPT

```bash
make run
```

or

```bash
uv run pentestgpt
```

This launches the interactive PentestGPT interface.

---

# Example Usage

Start a testing session:

```text
Target: http://example.com
```

Ask PentestGPT to begin reconnaissance:

```text
Start reconnaissance on the target.
```

The AI may recommend commands such as:

```bash
nmap -sV target
gobuster dir -u http://target -w wordlist.txt
```

You can paste tool output directly into the conversation for analysis:

```text
Analyze these scan results and suggest next steps.
```

---

# Typical Pentesting Workflow

1. **Reconnaissance**

```bash
nmap -sV target
```

2. **Service Enumeration**

```bash
nmap -sC -sV target
```

3. **Directory Discovery**

```bash
gobuster dir -u target -w wordlist.txt
```

4. **Vulnerability Analysis**

Paste scan results into PentestGPT and ask:

```text
What vulnerabilities are likely present?
```

5. **Exploitation Planning**

PentestGPT suggests possible attack vectors and tools.

---

# Using Local LLMs

Install Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Pull a model:

```bash
ollama pull qwen2.5-coder
```

Start the model server:

```bash
ollama serve
```

Configure PentestGPT to connect to the local model during setup.

---

# Benchmark System

The repository includes benchmark datasets used to evaluate model performance.

Location:

```text
benchmark/
```

Benchmarks simulate real penetration testing scenarios. They help measure:

* reasoning capability
* vulnerability discovery ability
* decision-making accuracy

---

# Development Setup

Install development dependencies:

```bash
uv sync
```

Run the application directly:

```bash
uv run pentestgpt
```

Code structure typically includes:

* pentestgpt/
* benchmark/
* docs/
* configs/

Developers may extend:

* prompt templates
* workflow modules
* model integrations

---

# Troubleshooting

**Docker permission errors**

```text
permission denied while trying to connect to docker.sock
```

Fix:

```bash
sudo usermod -aG docker $USER
```

Log out and back in.

**uv command not found**

```bash
pip install uv
```

Or:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Python version errors**

```bash
python3 --version
```

Ensure version is 3.10+.

---

# Security Notice

PentestGPT is designed only for authorized penetration testing.

Never test systems without explicit permission. Unauthorized testing may violate laws and policies.

---

# Contributing

Common contribution areas:

* improving prompts
* expanding benchmark datasets
* adding model integrations
* improving documentation
* fixing bugs

Workflow:

1. Fork repository
2. Create feature branch
3. Implement changes
4. Submit pull request

---

# License

Refer to the LICENSE file included in the repository for licensing terms.
