import sys
from pathlib import Path

BASE_DIR = Path(r'C:/Users/afimeenu/project')

LIB_DIR = BASE_DIR / "portable_libs"

if LIB_DIR.exists():
    sys.path.insert(0, str(LIB_DIR))
    print("Found the folder -- portable_libs --")
else:
    raise FileNotFoundError(f"Not Found folder portable_libs at : {LIB_DIR}")
    
    