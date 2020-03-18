"""Classes for running different types of robot backends."""

__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import signal
import logging
import os
import subprocess

from .configuration import JobConfig, Task


class BaseBackendRunner:
    #: Timeout for the backend to get ready after being started.
    READY_TIMEOUT_SEC = 60

    returncode: int

    def start(self, first_action_timeout: int):
        raise NotImplementedError()

    def is_running(self) -> bool:
        raise NotImplementedError()


class BackendRunner(BaseBackendRunner):
    def __init__(self, config: JobConfig, logger=logging):
        self.config = config
        self.logger = logger

    def start(self, first_action_timeout: int):
        self.logger.info("Start the robot backend")

        # decide whether to use object tracking or not depending on the task
        if self.config.task.needs_object_tracking():
            camera_flag = "--cameras-with-tracker"
        else:
            camera_flag = "--cameras"

        backend_rosrun_cmd = " ".join(
            [
                "ros2 run robot_fingers trifinger_robot_backend",
                camera_flag,
                "--first-action-timeout {}".format(first_action_timeout),
                "--max-number-of-actions {}".format(
                    self.config.episode_length
                ),
                "--fail-on-incomplete-run",
            ]
        )

        bindings = [
            "/dev",
            "/etc/trifingerpro:/etc/trifingerpro:ro",
            "/var/log/trifinger:/log",
        ]

        run_backend_cmd = [
            self.config.singularity_binary,
            "run",
            "--cleanenv",
            "--contain",
            "-B",
            ",".join(bindings),
            self.config.singularity_backend_image,
            backend_rosrun_cmd,
        ]
        self.logger.debug(" ".join(run_backend_cmd))
        self._proc = subprocess.Popen(
            run_backend_cmd, start_new_session=True, stderr=subprocess.STDOUT
        )

    def is_running(self):
        self.returncode = self._proc.poll()
        return self.returncode is None

    # FIXME not used anymore?
    def kill(self):
        self.logger.info("Backend still running.  Send SIGINT.")
        # the backend spawns several subprocesses by itself, so kill the whole
        # process group instead of just the main process (otherwise some
        # processes will keep running in the backgound).
        backend_pgid = os.getpgid(self._proc.pid)
        os.killpg(backend_pgid, signal.SIGINT)
        try:
            self.returncode = self._proc.wait(10)
        except subprocess.TimeoutExpired:
            self.logger.warning("Backend still running.  Send SIGTERM.")
            try:
                os.killpg(backend_pgid, signal.SIGTERM)
                self.returncode = self._proc.wait(3)
            except subprocess.TimeoutExpired:
                self.logger.error("Backend still running.  Send SIGKILL.")
                # FIXME this does not seem to kill everything, the pybullet gui
                # is still running when this script terminates...
                os.killpg(backend_pgid, signal.SIGKILL)
                self.returncode = self._proc.wait()

        self.logger.info(
            "Backend process terminated with returncode %d.", self.returncode
        )
        return self.returncode == 0


class SimulationBackendRunner(BaseBackendRunner):
    def __init__(self, config: JobConfig, logger=logging):
        self.config = config
        self.logger = logger

    def start(self, first_action_timeout: int):
        self.logger.info("Start the simulation backend")

        # choose object type depending on task
        object_type = "none"
        if self.config.task in [Task.MOVE_CUBE, Task.MOVE_CUBE_ON_TRAJECTORY]:
            object_type = "cube"
        elif self.config.task == Task.REARRANGE_DICE:
            object_type = "dice"

        backend_rosrun_cmd = " ".join(
            [
                "ros2 run robot_fingers pybullet_backend",
                "--cameras",
                "--render-images" if self.config.sim_render_images else "",
                "--object={}".format(object_type),
                "--real-time-mode",
                "--visualize" if self.config.sim_visualize else "",
                "--max-number-of-actions={}".format(
                    self.config.episode_length
                ),
                "--first-action-timeout={}".format(first_action_timeout),
            ]
        )

        run_backend_cmd = [
            self.config.singularity_binary,
            "run",
            "--cleanenv",
            "--contain",
            "--nv" if self.config.singularity_nv else "",
            "-B",
            "/dev",
            self.config.singularity_backend_image,
            backend_rosrun_cmd,
        ]
        self.logger.debug(" ".join(run_backend_cmd))
        self._proc = subprocess.Popen(
            run_backend_cmd, stderr=subprocess.STDOUT
        )

    def is_running(self):
        self.returncode = self._proc.poll()
        return self.returncode is None


class LogReplayBackendRunner(BaseBackendRunner):
    def __init__(self, config: JobConfig, logger=logging):
        self.config = config
        self.logger = logger

    def start(self, first_action_timeout: int):
        self.logger.info("Start the log replay backend")

        backend_rosrun_cmd = " ".join(
            [
                "ros2 run robot_fingers log_replay_backend",
                "--robot-log-file TODO",
                "--camera-log-file TODO",
                "--first-action-timeout {}".format(first_action_timeout),
            ]
        )

        run_backend_cmd = [
            self.config.singularity_binary,
            "run",
            "--cleanenv",
            "--contain",
            "-B",
            "/dev",
            self.config.singularity_backend_image,
            backend_rosrun_cmd,
        ]
        self.logger.debug(" ".join(run_backend_cmd))
        self._proc = subprocess.Popen(
            run_backend_cmd, stderr=subprocess.STDOUT
        )

    def is_running(self):
        self.returncode = self._proc.poll()
        return self.returncode is None
