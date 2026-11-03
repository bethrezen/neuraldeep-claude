#!/usr/bin/env python3
"""Run directly from a copied checkout without pip or a virtual environment."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from neuraldeep_claude.cli import main
raise SystemExit(main())
