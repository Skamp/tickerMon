#!/usr/bin/env bash
# Helper script to activate virtual environment in bash / WSL / Git Bash

if [ -f ".venv/Scripts/activate" ]; then
    source ".venv/Scripts/activate"
elif [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
else
    echo "Error: Virtual environment '.venv' not found."
    echo "Run 'python -m venv .venv' to create one."
fi
