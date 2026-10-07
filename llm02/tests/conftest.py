import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
parent = str(Path(__file__).resolve().parents[2])
os.environ['PYTHONPATH'] = parent + os.pathsep + os.environ.get('PYTHONPATH', '')
