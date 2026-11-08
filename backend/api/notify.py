"""Texts to the crew (Photon). Phone numbers live in the server's .env, never in requests.

send_text() returns "sent", "simulated" (no Photon key set) or "failed".
Right now it only simulates: sending a text to a number that has not texted us first still
needs to be worked out with Photon's docs (see notifier/). Nothing here pretends a text went out.
"""
from __future__ import annotations

import os


def photon_configured() -> bool:
    return bool(os.getenv("SPECTRUM_PROJECT_ID") and os.getenv("SPECTRUM_PROJECT_SECRET"))


def send_text(role: str, message: str) -> str:
    # TODO: call notifier/send.ts once proactive sending works. Until then, never claim "sent".
    return "simulated"
