"""Run a shell command as an action.

Commands are run without a shell (``shell=False``) so an action's arguments are
passed as a list and never re-parsed. This is deliberate: an action is
configured by the device owner, but not routing user text through ``/bin/sh``
keeps a stray quote or space from turning into shell injection.
"""
from __future__ import annotations

import shlex
import subprocess
from typing import Any

from .base import Driver, DriverResult


class ShellDriver(Driver):
    name = "shell"
    label = "Run a command"
    param_schema = [
        {"key": "command", "label": "Command", "type": "text", "required": True,
         "help": "The program to run, plus arguments (parsed like a shell line, "
                 "but executed without a shell)."},
        {"key": "timeout", "label": "Timeout (seconds)", "type": "number",
         "required": False, "default": 30},
    ]

    def execute(self, params: dict[str, Any]) -> DriverResult:
        command = params.get("command", "")
        if not command or not str(command).strip():
            return DriverResult.failure("No command configured")
        try:
            timeout = float(params.get("timeout", 30) or 30)
        except (TypeError, ValueError):
            timeout = 30.0
        argv = command if isinstance(command, list) else shlex.split(str(command))
        if not argv:
            return DriverResult.failure("Empty command")
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except FileNotFoundError:
            return DriverResult.failure(f"Command not found: {argv[0]}")
        except subprocess.TimeoutExpired:
            return DriverResult.failure(f"Command timed out after {timeout:g}s")
        except OSError as exc:
            return DriverResult.failure(f"Could not run command: {exc}")
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode == 0:
            return DriverResult.success(out or "Command finished", exit_code=0, stdout=out)
        return DriverResult.failure(
            err or f"Exited with code {proc.returncode}",
            exit_code=proc.returncode,
            stdout=out,
            stderr=err,
        )
