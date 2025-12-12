#!/usr/bin/env bash
# PentestGPT Container Entrypoint
# Sets up authentication based on PENTESTGPT_AUTH_MODE environment variable

set -e

AUTH_MODE="${PENTESTGPT_AUTH_MODE:-manual}"
CCR_CONFIG_DIR="/home/pentester/.claude-code-router"
CCR_CONFIG_FILE="${CCR_CONFIG_DIR}/config.json"
BASHRC_FILE="/home/pentester/.bashrc"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

setup_openrouter() {
    local api_key="$1"

    # Create CCR config directory if needed
    mkdir -p "$CCR_CONFIG_DIR"

    # Generate CCR config with OpenRouter
    cat > "$CCR_CONFIG_FILE" << EOF
{
  "LOG": false,
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "API_TIMEOUT_MS": "600000",
  "Providers": [
    {
      "name": "openrouter",
      "api_base_url": "https://openrouter.ai/api/v1/chat/completions",
      "api_key": "${api_key}",
      "models": [
        "google/gemini-2.5-pro-preview",
        "google/gemini-3-pro-preview",
        "openai/gpt-5.1"
      ],
      "transformer": {
        "use": ["openrouter"]
      }
    }
  ],
  "Router": {
    "default": "openrouter,openai/gpt-5.1",
    "background": "openrouter,openai/gpt-5.1",
    "think": "openrouter,openai/gpt-5.1",
    "longContext": "openrouter,openai/gpt-5.1",
    "longContextThreshold": 60000,
    "webSearch": "openrouter,google/gemini-3-pro-preview"
  }
}
EOF

    echo -e "${BLUE}Starting Claude Code Router...${NC}"

    # Start CCR daemon (nohup to keep it running)
    nohup ccr start > /tmp/ccr.log 2>&1 &

    # Wait for CCR to be ready
    sleep 2

    # Check if CCR is running by testing the port
    if nc -z 127.0.0.1 3456 2>/dev/null; then
        echo -e "${GREEN}CCR daemon running on port 3456${NC}"
    else
        echo -e "${YELLOW}Warning: CCR may not have started properly. Check /tmp/ccr.log${NC}"
    fi

    # Add CCR activation to .bashrc so it persists in interactive shells
    # Remove any existing ccr activation lines first
    sed -i '/# CCR activation/d' "$BASHRC_FILE" 2>/dev/null || true
    sed -i '/eval "$(ccr activate)"/d' "$BASHRC_FILE" 2>/dev/null || true

    # Add ccr activation to bashrc
    echo '# CCR activation for OpenRouter' >> "$BASHRC_FILE"
    echo 'eval "$(ccr activate 2>/dev/null)" || true' >> "$BASHRC_FILE"

    # Also export for the current session (will be inherited by exec'd shell)
    eval "$(ccr activate 2>/dev/null)" || true

    echo -e "${GREEN}CCR activated with OpenRouter backend${NC}"
    echo -e "${BLUE}Default model: openai/gpt-5.1${NC}"
}

echo ""
echo -e "${BLUE}=== PentestGPT Authentication ===${NC}"

case "$AUTH_MODE" in
    openrouter)
        if [ -z "$OPENROUTER_API_KEY" ]; then
            echo -e "${YELLOW}Error: OPENROUTER_API_KEY not set${NC}"
            echo "Please run 'make config' and select OpenRouter option"
            exit 1
        fi
        setup_openrouter "$OPENROUTER_API_KEY"
        ;;
    anthropic)
        if [ -z "$ANTHROPIC_API_KEY" ]; then
            echo -e "${YELLOW}Warning: ANTHROPIC_API_KEY not set${NC}"
            echo "Please run 'make config' and select Anthropic option"
        else
            echo -e "${GREEN}Using Anthropic API key${NC}"
        fi
        ;;
    manual)
        echo -e "${YELLOW}Manual login mode${NC}"
        echo -e "Run ${GREEN}claude login${NC} to authenticate"
        ;;
    *)
        echo -e "${YELLOW}Unknown auth mode: $AUTH_MODE${NC}"
        echo "Defaulting to manual login mode"
        echo -e "Run ${GREEN}claude login${NC} to authenticate"
        ;;
esac

echo -e "${BLUE}=================================${NC}"
echo ""

# Execute the passed command or start bash
# Use bash -l to ensure .bashrc is sourced (for ccr activation)
if [ "$1" = "/bin/bash" ]; then
    exec /bin/bash --login
else
    exec "$@"
fi
