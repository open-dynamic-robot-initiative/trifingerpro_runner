"""TriFinger Runner

Provides the infrastructure for running jobs on the TriFinger robots.  This
involves

- pulling and building the user code in a temporary workspace,
- running data and robot backend as well as the user code in Singularity
  containers,
- monitoring all running processes and managing shutdown in the proper order,
- storing logs, outputs and some meta information.
"""

__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

from .actions import (  # noqa
    clone_git_repository,
    build_workspace,
    store_info_file,
    store_camera_calibration_files,
    store_report,
)

from .data_runner import DataRunner  # noqa
from .backend_runner import BackendRunner  # noqa
from .user_code_runner import UserCodeRunner  # noqa
