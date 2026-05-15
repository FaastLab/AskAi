"""Enable `python -m faastlab_askai_watcher ...` invocation."""

from __future__ import annotations

import sys

from faastlab_askai_watcher.cli import main

if __name__ == "__main__":
    sys.exit(main())
