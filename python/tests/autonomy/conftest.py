import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from autonomy_helpers import make_controller  # noqa: E402


@pytest.fixture
def ctl():
    return make_controller()
