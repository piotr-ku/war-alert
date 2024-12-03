#!/bin/sh

if [ ! -f .venv/bin/activate ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    python3 -m pip install -r requirements.txt
fi

source .venv/bin/activate
python3 war-alert.py