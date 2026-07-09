"""Random delays for anti-block."""

import random
import time

from recon.config import AMAZON_MIN_DELAY_SEC, MAX_DELAY_SEC, MIN_DELAY_SEC


def random_delay(platform: str = "default") -> None:
    lo = AMAZON_MIN_DELAY_SEC if platform == "amazon" else MIN_DELAY_SEC
    time.sleep(random.uniform(lo, MAX_DELAY_SEC))
