#!/usr/bin/env python3
"""
Vercel serverless entrypoint for TV Remote
This file imports and exposes the Flask app for Vercel's runtime
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import main
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the Flask app from main.py
from main import app

# Vercel serverless entry point
# The app is already configured and ready to use
handler = app
