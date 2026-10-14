"""Where the live tests find the test film. Fetch it with scripts/fetch_test_clip.py."""

import os
from pathlib import Path

MEDIA = Path(os.environ.get("SOTTOVOCE_MEDIA", Path(__file__).resolve().parent.parent / "media"))
CLIP = MEDIA / "tos_bridge_150s.mp4"  # the first 150 s of Tears of Steel
RUN = MEDIA / "out_it"  # a finished Italian run of CLIP
