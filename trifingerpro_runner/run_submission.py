"""Execute a submission"""

__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import enum
import logging
import os
import pathlib
import subprocess
import tempfile
import time
import typing

# ROS imports
import rclpy
import rclpy.node
import rclpy.qos
from std_msgs.msg import String
from std_srvs.srv import Empty

from . import actions
from . import condor
from . import configuration
from . import DataRunner, UserCodeRunner
from .states import ProcessState, ProcessStateCompareWrapper, LauncherState
from .backend_runner import (
    BaseBackendRunner,
    BackendRunner,
    SimulationBackendRunner,
    LogReplayBackendRunner,
)


#: Time out for the first action to arrive after the robot back end is started.
FIRST_ACTION_TIMEOUT_S = 2 * 60


# some helper types for type hints
Runner = typing.Union[DataRunner, BaseBackendRunner, UserCodeRunner]


class NodeTimeoutError(Exception):
    """Error indicating that a node timed out."""

    pass


class NodeUnexpectedTerminationError(Exception):
    """Error indicating that a node terminated unexpectedly."""

    pass


class BackendType(enum.Enum):
    """Different types of robot back end that can be used."""

    ROBOT = 1
    SIMULATION = 2
    LOG_REPLAY = 3


def clone_user_repository(
    config: configuration.JobConfig, source_path: str
) -> str:
    """Clone the user repository.

    Args:
        config: Configuration specifying the git repository, branch, etc.
        source_path: Path to which the repository is cloned.

    Returns:
        The git revision of the cloned repository.
    """
    git_revision = actions.clone_git_repository(
        repository=config.git_repository,
        branch=config.git_branch,
        destination=os.path.join(source_path, "usercode"),
        git_ssh_command=config.git_ssh_command,
    )

    return git_revision


def json_goal_from_goal_config(
    config: configuration.JobConfig,
    source_path: str,
) -> str:
    """Get a goal based on the users goal.json

    Args:
        config: Configuration containing information about which Singularity
            image to use.
        source_path: Path to the workspace source to find the goal.json in the
            user's repository.

    Returns:
        The JSON-encoded goal as string.
    """
    if config.task is configuration.Task.NONE:
        return ""

    task = config.task.name.lower()

    goal_file = pathlib.Path(
        source_path, "usercode", configuration.OutputFiles.goal
    )

    if goal_file.is_file():
        cmd = "goal_from_config {}".format(goal_file)
    else:
        # If no goal file is given, simply sample a goal
        cmd = "sample_goal"

    run_cmd = [
        config.singularity_binary,
        "run",
        "-eC",
        "-B",
        "{0}:{0}:ro".format(source_path),
        config.singularity_backend_image,
        "python3 -m trifinger_simulation.tasks.{} {}".format(task, cmd),
    ]
    try:
        output_bytes = subprocess.check_output(run_cmd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.stdout.decode("utf-8"))

    # convert bytes to string
    output = output_bytes.decode("utf-8")

    goal_json = output.strip()
    if not goal_json:
        raise RuntimeError("Failed to sample goal.")

    return goal_json


def _get_runner_state(runner: Runner) -> ProcessStateCompareWrapper:
    """Get a comparable state of the given runner."""
    if runner.is_running():
        return ProcessStateCompareWrapper(ProcessState.RUNNING)
    elif runner.returncode == 0:
        return ProcessStateCompareWrapper(ProcessState.TERMINATED_SUCCESS)
    else:
        return ProcessStateCompareWrapper(ProcessState.TERMINATED_ERROR)


class TrifingerLauncherNode(rclpy.node.Node):
    """Launch, monitor and shutdown all parts of the TriFinger software.


    Starts data backend, robot backend and user code in the proper order
    monitors them and, when on of them terminates, shuts down the others in the
    proper order.

    Uses ROS topics/services for communication with the backend nodes.

    Args:
        name: Name of the ROS node.
    """

    STATUS_MSG_READY = "READY"

    def __init__(self, name: str):
        super().__init__(name)

        self.data_node_ready = False
        self.backend_node_ready = False

        # Quality of service profile for subscribers to ensure messages are not
        # missed.
        # Note: Names are a bit ugly here for ROS Dashing.  This will need be
        # nicer in Foxy.
        QoSDurability = rclpy.qos.QoSDurabilityPolicy
        QoSHistory = rclpy.qos.QoSHistoryPolicy
        QoSReliability = rclpy.qos.QoSReliabilityPolicy
        qos_profile = rclpy.qos.QoSProfile(
            depth=5,
            durability=QoSDurability.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL,
            history=QoSHistory.RMW_QOS_POLICY_HISTORY_KEEP_LAST,
            reliability=QoSReliability.RMW_QOS_POLICY_RELIABILITY_RELIABLE,
        )

        self._sub_data_node_status = self.create_subscription(
            String,
            "/trifinger_data/status",
            self._data_node_status_callback,
            qos_profile,
        )
        self._sub_data_node_status  # prevent unused variable warning

        self._sub_backend_node_status = self.create_subscription(
            String,
            "/trifinger_backend/status",
            self._backend_node_status_callback,
            qos_profile,
        )
        self._sub_data_node_status  # prevent unused variable warning

        self.data_shutdown = self.create_client(
            Empty, "/trifinger_data/shutdown"
        )
        self.backend_shutdown = self.create_client(
            Empty, "/trifinger_backend/shutdown"
        )

    def _data_node_status_callback(self, msg):
        """Callback for the status topic of the data node."""
        if msg.data == self.STATUS_MSG_READY:
            self.data_node_ready = True
            self.get_logger().info("Data node is ready")

    def _backend_node_status_callback(self, msg):
        """Callback for the status topic of the robot back end node."""
        if msg.data == self.STATUS_MSG_READY:
            self.backend_node_ready = True
            self.get_logger().info("Backend node is ready")

    def _wait_until_node_is_ready(
        self,
        runner: typing.Union[DataRunner, BaseBackendRunner],
        ready_check: typing.Callable,
    ):
        """Wait until the node started by runner is ready.

        Calls ``ready_check()`` in a loop until it returns True.  If the node
        terminates before that or if the timeout configured for the runner
        expires an error is raised.

        Args:
            runner: Runner class for either the data or the robot node.
            ready_check: Executable that returns True when the corresponding
                node reported that it is ready.

        Raises:
            NodeUnexpectedTerminationError: If the node started by runner
                terminates before reporting its readiness.
            NodeTimeoutError: If the timeout configured in runner expires
                before the node is ready.
        """
        start_time = time.time()
        while not ready_check():
            if not runner.is_running():
                raise NodeUnexpectedTerminationError(str(type(runner)))

            # if the node takes too long to initialize, abort
            if (time.time() - start_time) > runner.READY_TIMEOUT_SEC:
                raise NodeTimeoutError(str(type(runner)))

            rclpy.spin_once(self, timeout_sec=3)

    def _shutdown_data(self):
        """Ask the data node to shut down."""
        self.get_logger().info("Shut down data node.")
        self.data_shutdown.call_async(Empty.Request())

    def _shutdown_backend(self):
        """Ask the robot back end node to shut down."""
        self.get_logger().info("Shut down robot backend node.")
        self.backend_shutdown.call_async(Empty.Request())

    def _terminate_user(self, user_code_runner: UserCodeRunner):
        """Kill the user node."""
        self.get_logger().info("Kill user node.")
        user_code_runner.kill()

    def _monitor_nodes(
        self,
        data_runner: DataRunner,
        backend_runner: BaseBackendRunner,
        user_code_runner: UserCodeRunner,
    ) -> bool:
        """Monitor running nodes and wait until all have terminated.

        Checks the status of data, robot backend and user nodes in a loop.  If
        one of them terminates, the other two are shut down in the appropriate
        order.
        """
        # state constants to simplify the code below
        RUNNING = ProcessStateCompareWrapper(ProcessState.RUNNING)
        SUCCESS = ProcessStateCompareWrapper(ProcessState.TERMINATED_SUCCESS)
        ERROR = ProcessStateCompareWrapper(ProcessState.TERMINATED_ERROR)
        TERMINATED_ANY = ProcessStateCompareWrapper(
            ProcessState.TERMINATED_ANY
        )

        # monitor running nodes and handle shutdown using a state machine
        self.get_logger().info("Monitor nodes...")
        error = False
        previous_state = LauncherState(RUNNING, RUNNING, RUNNING)
        while True:
            time.sleep(3)

            # update state
            state = LauncherState(
                _get_runner_state(data_runner),
                _get_runner_state(backend_runner),
                _get_runner_state(user_code_runner),
            )

            # only take action if state changes
            if state != previous_state:
                self.get_logger().info(
                    "State %s --> %s" % (previous_state, state)
                )
                previous_state = state

                if state == (RUNNING, RUNNING, RUNNING):
                    # while all nodes are running, do nothing
                    pass

                # If user code terminated while the robot is still running,
                # stop the robot immediately.
                elif state == (RUNNING, RUNNING, TERMINATED_ANY):

                    # TODO: This case is tricky.  It might be all right if the
                    # user code terminates immediately after sending the last
                    # action (which would be a successful run) but it might
                    # also mean that the run is aborted somewhere in the
                    # middle, which means it should be considered as failed.

                    self._shutdown_backend()

                # If the robot back end terminates before the user node, give
                # the latter some time to wrap up and stop by itself.  If it is
                # still running after this time, kill it.
                elif state == (RUNNING, SUCCESS, RUNNING):
                    time.sleep(10)
                    self._terminate_user(user_code_runner)
                elif state == (RUNNING, ERROR, RUNNING):
                    # report the error of the robot back end
                    error = True
                    time.sleep(10)
                    self._terminate_user(user_code_runner)

                # After both user node and robot back end have terminated, the
                # data node can be stopped.
                elif state == (RUNNING, SUCCESS, TERMINATED_ANY):
                    self._shutdown_data()
                elif state == (RUNNING, ERROR, TERMINATED_ANY):
                    # report the error of the robot back end
                    error = True
                    self._shutdown_data()

                # If the data node terminates while any of the other is still
                # running, this is an error.  Shut down the other nodes (first
                # user node then robot back end) and report the error.
                elif state == (TERMINATED_ANY, RUNNING, RUNNING):
                    error = True
                    self._terminate_user(user_code_runner)
                elif state == (TERMINATED_ANY, RUNNING, TERMINATED_ANY):
                    error = True
                    self._shutdown_backend()
                elif state == (TERMINATED_ANY, TERMINATED_ANY, RUNNING):
                    error = True
                    self._terminate_user(user_code_runner)

                # terminal states

                elif state == (SUCCESS, SUCCESS, TERMINATED_ANY):
                    # end with success :)
                    break

                elif state in (
                    (ERROR, SUCCESS, TERMINATED_ANY),
                    (TERMINATED_ANY, ERROR, TERMINATED_ANY),
                ):
                    # end with failure
                    error = True
                    break

                else:
                    raise RuntimeError("Unexpected state %s" % state)

        return not error

    def run(
        self,
        config: configuration.JobConfig,
        ws_dir: str,
        backend_type: BackendType,
        backend_kwargs: dict = {},
    ):
        """Run a job on the robot.

        Based on the given configuration the user code is fetched and built.
        Then the robot is started and, when ready, the user code is executed.
        Then the running nodes are monitored and terminated in the appropriate
        order.

        Args:
            config: Configuration containing information about the user's git
                repository, which Singularity images to use, etc.
            ws_dir: Directory in which the user code is cloned and built.
            backend_type: Which type of back end to use (e.g. robot or
                simulation).
            backend_kwargs: Optional arguments that are passed to the backend
                constructor as kwargs.
        """
        self.get_logger().info("Starting...")

        data_runner = DataRunner(config, logger=self.get_logger())

        backend_runner: BaseBackendRunner
        if backend_type == BackendType.ROBOT:
            backend_runner = BackendRunner(config, **backend_kwargs)
        elif backend_type == BackendType.SIMULATION:
            backend_runner = SimulationBackendRunner(config, **backend_kwargs)
        elif backend_type == BackendType.LOG_REPLAY:
            backend_runner = LogReplayBackendRunner(config, **backend_kwargs)
        else:
            raise ValueError(
                "Unsupported backend type {}".format(backend_type.name)
            )

        user_code_runner = UserCodeRunner(
            config,
            ws_dir,
        )

        #
        # Preparation
        #

        # create "src" directory and clone user repository to it
        src_dir = os.path.join(ws_dir, "src")
        os.mkdir(src_dir)
        git_revision = clone_user_repository(config, src_dir)

        # load goal
        goal = json_goal_from_goal_config(config, src_dir)
        self.get_logger().info("Goal: {}".format(goal))

        # create meta data files
        actions.store_info_file(config, git_revision)
        # camera files are only meaningful on the real robot
        if backend_type == BackendType.ROBOT:
            actions.store_camera_calibration_files(config)

        # build user code
        actions.build_workspace(config, ws_dir)

        #
        # Starting Nodes
        #

        # run data node and wait until it is ready
        data_runner.start()
        self._wait_until_node_is_ready(
            data_runner, lambda: self.data_node_ready
        )

        # run robot backend and wait until it is ready
        backend_runner.start(FIRST_ACTION_TIMEOUT_S)
        self._wait_until_node_is_ready(
            backend_runner, lambda: self.backend_node_ready
        )

        # run user code
        user_code_runner.start(goal)

        #
        # Monitor running nodes and handle shutdown
        #
        success = self._monitor_nodes(
            data_runner, backend_runner, user_code_runner
        )

        if success:
            self.get_logger().info("Done.")
        else:
            self.get_logger().error("Finished with error.")

        # create the report last, so it can be used as indicator that
        # the execution is over
        backend_error = backend_runner.returncode != 0
        actions.store_report(
            config, backend_error, user_code_runner.returncode
        )


def run(
    use_condor_config: bool,
    backend_type: BackendType,
    args=None,
):
    """Run a job on the robot.

    This can be used either in "condor mode" (use_condor_config=True) where the
    configuration is read from the user's config file (``roboch.json``) or in
    "manual mode" where the configuration is read from command line arguments.

    Args:
        use_condor_config:  If True, run in "condor mode", otherwise in "manual
            mode".
        backend_type: Which type of back end to use (e.g. robot or simulation).
        args:  Optional arguments for initialising the ROS node.
    """
    returncode = 0

    rclpy.init(args=args)

    if use_condor_config:
        if not condor.is_condor_running():
            raise RuntimeError("Condor is not running.")

        config = configuration.make_submission_system_config()
    else:
        config = configuration.make_local_execution_config()

    if not os.path.isdir(config.host_output_dir):
        logging.fatal(
            "Output directory {} does not exist or is not a directory.".format(
                config.host_output_dir
            )
        )
        return 1

    try:
        with tempfile.TemporaryDirectory(prefix="run_submission-") as ws_dir:
            logging.info("Use temporary workspace %s", ws_dir)

            node = TrifingerLauncherNode("trifinger_launcher")
            node.run(config, ws_dir, backend_type)

            logging.info("Finished.")
    except Exception as e:
        logging.critical("FAILURE: %s", e)

        import traceback

        traceback.print_exc()

        error_report_file = os.path.join(
            config.host_output_dir, "error_report.txt"
        )
        with open(error_report_file, "w") as fh:
            fh.write(
                "Submission failed with the following error:\n{}\n".format(e)
            )

        returncode = 1

    # tear down
    node.destroy_node()
    rclpy.shutdown()

    return returncode
