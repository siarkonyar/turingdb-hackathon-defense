"""Test-wide environment. A developer's .env may set OPSMAP_BACKEND=turingdb for the app; tests build their
own backends, so pin the mock here (a real variable always beats .env). FEATHERLESS_API_KEY from .env still
reaches the live agent tests."""

import os

os.environ["OPSMAP_BACKEND"] = "mock"
