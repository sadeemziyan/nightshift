"""Texts to the crew through Photon. Phone numbers live in notifier/.env, never in requests.

send_text(role, message) -> "sent" | "simulated" | "failed"
  simulated: no Photon keys or no phone number configured (nothing was sent)
  sent:      notifier/send.ts reported SENT
  failed:    it tried and did not succeed (reason is printed in the server console)

notifier/.env needs:
  SPECTRUM_PROJECT_ID, SPECTRUM_PROJECT_SECRET   from app.photon.codes -> project Settings
  PHONE_DEFAULT=+1XXXXXXXXXX                     used for every role without its own number
  PHONE_TRUCK_DRIVER / PHONE_FIELD_OPERATOR / PHONE_INSPECTOR   optional, per role
The number must be added as a user in the Photon dashboard first.

Test one text:  python -m backend.api.notify truck_driver "Nightshift test"
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NOTIFIER = Path(__file__).resolve().parents[2] / "notifier"


def _env() -> dict:
    """Variables from notifier/.env (real environment variables win)."""
    out: dict = {}
    path = NOTIFIER / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    out.update({k: v for k, v in os.environ.items() if k.startswith(("SPECTRUM_", "PHONE_"))})
    return out


def phone_for(role: str, env: dict | None = None) -> str | None:
    env = _env() if env is None else env
    return env.get(f"PHONE_{role.upper()}") or env.get("PHONE_DEFAULT") or None


def photon_configured(env: dict | None = None) -> bool:
    env = _env() if env is None else env
    return bool(env.get("SPECTRUM_PROJECT_ID") and env.get("SPECTRUM_PROJECT_SECRET"))


def send_text(role: str, message: str) -> str:
    env = _env()
    phone = phone_for(role, env)
    if not photon_configured(env) or not phone:
        return "simulated"
    npx = shutil.which("npx")
    if npx is None:
        print("[notify] npx not found; install Node.js to send real texts", file=sys.stderr)
        return "failed"
    run_env = {**os.environ, **env, "NIGHTSHIFT_TO": phone, "NIGHTSHIFT_MSG": message}
    try:
        r = subprocess.run([npx, "tsx", "send.ts"], cwd=NOTIFIER, env=run_env,
                           capture_output=True, text=True, timeout=60)
    except Exception as exc:  # timeout, missing files, ...
        print(f"[notify] {type(exc).__name__}: {exc}", file=sys.stderr)
        return "failed"
    if r.returncode == 0 and "SENT" in r.stdout:
        return "sent"
    print(f"[notify] send failed (exit {r.returncode}): {(r.stderr or r.stdout).strip()[:400]}", file=sys.stderr)
    return "failed"


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "truck_driver"
    msg = sys.argv[2] if len(sys.argv) > 2 else "Nightshift test: this text came from our backend."
    print(role, "->", send_text(role, msg))
