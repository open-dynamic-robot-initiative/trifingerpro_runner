__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import json
import logging
import os
import subprocess

from .configuration import JobConfig, OutputFiles


class UserCodeRunner:
    def __init__(self, config: JobConfig, workspace_path: str):
        self.config = config
        self.workspace_path = workspace_path

    def start(self, goal):
        """Run the user script."""
        logging.info("Run the user code.")

        # create user output directory if it does not yet exist
        user_output_dir = os.path.join(self.config.host_output_dir, "user")
        if not os.path.exists(user_output_dir):
            os.mkdir(user_output_dir)

        # store the goal to a file
        goal_file = os.path.join(self.config.host_output_dir, OutputFiles.goal)
        goal_info = {
            "goal": json.loads(goal) if goal else None,
        }
        with open(goal_file, "w") as fh:
            json.dump(goal_info, fh, indent=4)

        exec_cmd = (
            ". /setup.bash;"
            ". /ws/install/local_setup.bash;"
            "/ws/src/usercode/run {!r}"
        )

        # binding full /dev as only binding /dev/shm does not work with
        # --contain
        bindings = [
            "{}:/ws".format(self.workspace_path),
            "/dev",
            "/etc/trifingerpro:/etc/trifingerpro:ro",
            "{}:/output".format(user_output_dir),
        ]
        if self.config.host_user_data_dir:
            # FIXME 'userhome' might not be the best name
            bindings.append(
                "{}:/userhome:ro".format(self.config.host_user_data_dir)
            )

        run_user_cmd = [
            self.config.singularity_binary,
            "exec",
            "--cleanenv",
            "--contain",
            "--net",
            "--network",
            "none",
            "-B",
            ",".join(bindings),
            self.config.singularity_user_image,
            "bash",
            "-c",
            exec_cmd.format(goal),
        ]

        # open the output files
        stdout_filename = os.path.join(
            self.config.host_output_dir, OutputFiles.user_stdout
        )
        stderr_filename = os.path.join(
            self.config.host_output_dir, OutputFiles.user_stderr
        )
        self.stdout_file = open(stdout_filename, "wb")
        self.stderr_file = open(stderr_filename, "wb")

        self._proc = subprocess.Popen(
            run_user_cmd,
            stdout=self.stdout_file,
            stderr=self.stderr_file,
        )

    def is_running(self):
        self.returncode = self._proc.poll()
        return self.returncode is None

    def _wait(self, timeout=None):
        self.returncode = self._proc.wait(timeout=timeout)

        if self.returncode == 0:
            logging.info("User code terminated.")
        else:
            logging.error(
                "User code exited with non-zero exist status: %d",
                self.returncode,
            )

    def wait(self, timeout=None):
        try:
            self._wait(timeout)
            return True
        except subprocess.TimeoutExpired as e:
            return False

    def kill(self):
        self._proc.kill()
        self._wait()
