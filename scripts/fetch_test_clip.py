"""Download Tears of Steel (CC BY 3.0, Blender Foundation) and cut the 150 s test clip.

    python scripts/fetch_test_clip.py [media_dir]
"""

import subprocess
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov"

media = Path(sys.argv[1] if len(sys.argv) > 1 else "media")
media.mkdir(parents=True, exist_ok=True)
full = media / "tears_of_steel_720p.mov"
if not full.exists():
    print(f"downloading {SOURCE} (about 370 MB)")
    urllib.request.urlretrieve(SOURCE, full)
clip = media / "tos_bridge_150s.mp4"
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-t", "150", "-i", str(full),
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", str(clip)],
    check=True,
)
print(f"wrote {clip}")
