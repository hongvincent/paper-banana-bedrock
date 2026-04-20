"""Playwright-based automation for driving nano-banana (Google AI Studio) web UI.

Two-step flow:
  1. automation.session_setup  - one-time manual login to capture storageState
  2. automation.run_tabs       - open N tabs, paste N variant prompts in parallel

Credentials are NEVER handled by this package. Authentication state is reused
from a browser session you log into yourself, saved to .auth/ (gitignored).
"""
