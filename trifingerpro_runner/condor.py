"""Condor-related utility functions."""

__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import os
import re


def is_condor_running() -> bool:
    return os.environ.get("BATCH_SYSTEM") == "HTCondor"


def get_condor_job_id() -> str:
    """Get the ID of the current job on the cluster."""
    # $JOB_ID is set by the Condor and is used to identify the job
    job_id = os.environ["JOB_ID"]

    # The given job_id is something like "sched#12345.0".  Cut out the actual
    # ID (the number between # and .)
    match = re.search(r"#([0-9]*)\.", job_id)
    if match:
        job_id = match.group(1)
    else:
        raise RuntimeError("Failed to parse $JOB_ID: '{}'".format(job_id))

    return job_id
