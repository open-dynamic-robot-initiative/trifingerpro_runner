__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import logging
import subprocess

from .configuration import JobConfig, OutputFiles


class DataRunner:

    #: Timeout for the data node to get ready after being started.
    READY_TIMEOUT_SEC = 60

    def __init__(self, config: JobConfig, logger=logging):
        self.config = config
        self.logger = logger

    def start(self):
        self.logger.info("Start data node")

        # decide whether to use object tracking or not depending on the task
        if self.config.task.needs_object_tracking():
            camera_flag = "--cameras-with-tracker"
        else:
            camera_flag = "--cameras"

        rosrun_cmd = " ".join(
            [
                "ros2 run robot_fingers trifinger_data_backend",
                camera_flag,
                "--robot-logfile /output/{}".format(OutputFiles.robot_data),
                "--camera-logfile /output/{}".format(OutputFiles.camera_data),
                "--max-number-of-actions {}".format(
                    self.config.episode_length
                ),
            ]
        )

        singularity_cmd = [
            self.config.singularity_binary,
            "run",
            "--cleanenv",
            "--contain",
            "-B",
            "/dev,/etc/trifingerpro,{}:/output".format(
                self.config.host_output_dir
            ),
            self.config.singularity_backend_image,
            rosrun_cmd,
        ]
        self.logger.debug(" ".join(singularity_cmd))
        self._proc = subprocess.Popen(
            singularity_cmd, start_new_session=True, stderr=subprocess.STDOUT
        )

    def is_running(self):
        self.returncode = self._proc.poll()
        return self.returncode is None
