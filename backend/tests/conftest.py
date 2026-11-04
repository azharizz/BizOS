import os
import tempfile

# Tests never touch the real long-term memory in ~/.bizos.
os.environ.setdefault("BIZOS_MEMORY", os.path.join(tempfile.mkdtemp(prefix="bizos-test-"), "memory.db"))
