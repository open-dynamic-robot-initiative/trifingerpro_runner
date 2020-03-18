# TODO better name for this module?

__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import shutil
import time
import socket
import json
import logging
import os
import subprocess
import typing

from .configuration import JobConfig, OutputFiles


def clone_git_repository(
    repository: str,
    branch: str,
    destination: str,
    git_ssh_command: typing.Optional[str] = None,
) -> str:
    """Clone a git repository.

    Args:
        repository:  The repository URL.
        branch:  Name of the branch that is cloned.
        destination:  Path to which the repository is cloned.
        git_ssh_command:  Optional.  If given, this is set to the
            $GIT_SSH_COMMAND environment variable before calling git clone.

    Returns:
        The hash of the current commit.
    """
    logging.info(
        "Clone user git repository %s (%s)",
        repository,
        branch,
    )

    if git_ssh_command:
        os.environ["GIT_SSH_COMMAND"] = git_ssh_command

    git_cmd = [
        "git",
        "clone",
        "--recurse-submodules",
        "-b",
        branch,
        repository,
        destination,
    ]
    try:
        subprocess.run(
            git_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "Failed to clone git repository:\n{}".format(
                e.stdout.decode("utf-8")
            )
        )

    # get current revision
    git_cmd = [
        "git",
        "--git-dir",
        os.path.join(destination, ".git"),
        "rev-parse",
        "HEAD",
    ]
    revision_bytes = subprocess.check_output(git_cmd)
    git_revision = revision_bytes.decode("utf-8").strip()

    return git_revision


def build_workspace(config: JobConfig, workspace_path: str):
    logging.info("Build the user code")
    build_cmd = [
        config.singularity_binary,
        "exec",
        "--cleanenv",
        "--contain",
        "--net",
        "--network",
        "none",
        "-B",
        "{}:/ws".format(workspace_path),
        config.singularity_user_image,
        "bash",
        "-c",
        ". /setup.bash; cd /ws; colcon build",
    ]
    proc = subprocess.run(
        build_cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # store output
    stdout_file = os.path.join(
        config.host_output_dir, OutputFiles.build_output
    )
    with open(stdout_file, "wb") as fh:
        fh.write(proc.stdout)


def store_info_file(config: JobConfig, git_revision: str):
    """Store some information about this submission into a file."""
    info = {
        "git_revision": git_revision,
        "robot_name": socket.gethostname(),
        "timestamp": time.asctime(),
    }
    info_file = os.path.join(config.host_output_dir, OutputFiles.meta_info)
    with open(info_file, "w") as fh:
        json.dump(info, fh, indent=4)


def store_camera_calibration_files(config: JobConfig):
    """Copy the camera calibration files to the output directory."""
    for camera_id in (60, 180, 300):
        src = "/etc/trifingerpro/camera{}_cropped_and_downsampled.yml".format(
            camera_id
        )
        dest = os.path.join(
            config.host_output_dir,
            OutputFiles.camera_info.format(camera_id=camera_id),
        )
        shutil.copyfile(src, dest)


def store_report(
    config: JobConfig,
    has_backend_error: bool,
    user_returncode: typing.Optional[int],
):
    """Store a "report" file with some information about the result.

    This file contains some information whether execution was successful or
    if there was some error.  It is created at the very end, so it also
    serves as a indicator that the execution is over.
    """
    report: typing.Dict[str, typing.Any] = {
        "backend_error": has_backend_error,
    }

    if user_returncode is not None:
        report["user_returncode"] = user_returncode

    report_file = os.path.join(config.host_output_dir, OutputFiles.report)
    with open(report_file, "w") as fh:
        json.dump(report, fh, indent=4)
