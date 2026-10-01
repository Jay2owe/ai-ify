"""``python -m aiify ...`` is the same as the ``aiify`` command."""
import sys

from .cli import main

sys.exit(main())
