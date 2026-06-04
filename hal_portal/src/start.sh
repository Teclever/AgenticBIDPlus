#!/bin/zsh
# HAL project launcher — activates venv, sets API key, then opens Claude Code.
# Usage: ./start.sh

cd "$(dirname "$0")"
source venv/bin/activate

if [[ -z "$ANTHROPIC_API_KEY" ]]; then
    echo -n "Enter ANTHROPIC_API_KEY: "
    read -rs ANTHROPIC_API_KEY
    echo
    export ANTHROPIC_API_KEY
fi

exec claude "$@"
