#!/usr/bin/env python3
"""Compatibility wrapper for the packaged Agent entrypoint installer."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stock_analysis.agent.install import (  # noqa: E402
    AgentEntrypointInstaller,
    InstallError,
    main,
)

__all__ = ["AgentEntrypointInstaller", "InstallError", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
