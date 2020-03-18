#!/usr/bin/env python3
"""Execute a submission in simulation."""

__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import sys
import trifingerpro_runner.run_submission as rs


if __name__ == "__main__":
    sys.exit(
        rs.run(
            use_condor_config=False,
            backend_type=rs.BackendType.SIMULATION,
        )
    )
