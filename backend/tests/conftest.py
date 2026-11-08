import os
import tempfile

# Tests never touch the real long-term memory in ~/.bizos.
os.environ.setdefault("BIZOS_MEMORY", os.path.join(tempfile.mkdtemp(prefix="bizos-test-"), "memory.db"))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def full_scale_payouts(monkeypatch):
    """The real .env may run the Sandbox demo at a smaller payout scale; tests assume full amounts."""
    from bizos import config
    monkeypatch.setattr(config, "PAYPAL_DEMO_SCALE", 1.0)
