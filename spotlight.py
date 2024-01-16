import os
import pathlib

from PIL import Image


SIZE_MIN = 200 * 1024
WIDTH_MIN = 1920

dest = pathlib.Path(os.environ["USERPROFILE"]).joinpath(
    "Pictures", "Spotlight")
dest.mkdir()
dir_src = pathlib.Path(os.environ["LocalAppData"]).joinpath("Packages",
    "Microsoft.Windows.ContentDeliveryManager_cw5n1h2txyewy", "LocalState",
    "Assets")

def filter_file_size(_filename):
    return os.path.isfile(_filename) and os.path.getsize(_filename) > SIZE_MIN

files = list(filter(filter_file_size, dir_src.iterdir()))
files.sort(key=lambda x: os.path.getmtime(x))
for filename in files:
    with Image.open(filename, mode="r", formats=None) as img:
        if img.width < WIDTH_MIN or img.width < img.height:
            continue
        file_basename = os.path.basename(filename)
        file_dest = dest.joinpath(f"f{file_basename}.{img.format.lower()}")
        if file_dest.exists():
            print(f"{file_dest} already exists")
        else:
            img.save(file_dest)
            print(f"Saved {file_dest}")
