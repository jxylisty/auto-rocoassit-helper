# -*- coding: utf-8 -*-
"""pytest 引导:把项目根目录加进 sys.path,保证 src 包可导入"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
