#!/bin/bash
set -e

# Start the LiveKit Agent worker in the background
echo "Starting LiveKit Agent Worker..."
python run_agent.py start &
AGENT_PID=$!

# Start the FastAPI Server in the foreground
echo "Starting FastAPI Server..."
python run_server.py

# Cleanup agent process on exit
kill $AGENT_PID
