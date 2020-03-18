__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import argparse
import enum
import typing
import os
import logging
import json
import getpass

from . import condor


# max. allowed number of steps in one run
MAX_EPISODE_LENGTH = 5 * 60 * 1000
# default number of steps in one run (used if no custom value is provided)
DEFAULT_EPISODE_LENGTH = 2 * 60 * 1000


class OutputFiles:
    """Names of the output files that are generated (e.g. logs)."""

    robot_data = "robot_data.dat"
    camera_data = "camera_data.dat"

    camera_info = "camera{camera_id}.yml"

    meta_info = "info.json"
    report = "report.json"

    build_output = "build_output.txt"

    user_stdout = "user_stdout.txt"
    user_stderr = "user_stderr.txt"

    goal = "goal.json"


class Task(enum.Enum):
    """Tasks that are supported by the system.

    Apart from "NONE", which means "no specific task", the names must match
    with the corresponding task sub-package in ``trifinger_simulation.tasks``
    which is expected to have ``goal_from_config`` and ``sample_goal`` commands
    in its ``__main__.py``.
    """

    NONE = 0
    MOVE_CUBE = 1
    MOVE_CUBE_ON_TRAJECTORY = 2
    REARRANGE_DICE = 3

    def needs_object_tracking(self) -> bool:
        """Check whether the task requires object tracking to be enabled."""
        return self in [self.MOVE_CUBE, self.MOVE_CUBE_ON_TRAJECTORY]


class JobConfig(typing.NamedTuple):
    #: Path to the singularity image used to run the back end.
    singularity_backend_image: str

    #: Path to the singularity image used to build and run the user code.
    singularity_user_image: str

    #: Path to the output directory (for logs, etc.) on the host.
    host_output_dir: str

    #: URL of the git repository.
    git_repository: str
    #: Name of the branch that is used.
    git_branch: str = "master"
    git_ssh_command: typing.Optional[str] = None

    #: The singularity binary
    singularity_binary: str = "singularity"

    #: Directory on the host that is bound to the container when running the
    #: user code.
    host_user_data_dir: typing.Optional[str] = None

    #: Number of actions that the robot executes in one run.  After this, the
    #: backend shuts down automatically.
    episode_length: int = DEFAULT_EPISODE_LENGTH

    #: Which task to execute (affects goal sampling and whether object tracking
    #: is used or not).
    task: Task = Task.NONE

    #: Enable visualization (only relevant for simulation).
    sim_visualize: bool = False
    #: Enable rendering of camera images (only for simulation).
    sim_render_images: bool = False
    #: If true, pass --nv to singularity when running the simulation backend.
    singularity_nv: bool = False


def make_submission_system_config():
    _userconf = "roboch.json"

    # a few static settings are read from the arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend-image",
        type=str,
        required=True,
        help="Path to the Singularity image for the backend.",
    )
    parser.add_argument(
        "--task",
        type=str,
        choices=[x.name for x in Task],
        default=Task.NONE.name,
        help="""Which task to execute (affects type of goals and whether object
            tracking is used or not).
        """,
    )
    args = parser.parse_args()

    if not os.path.exists(args.backend_image):
        raise FileNotFoundError(
            "Backend Singularity image {} does not exist".format(
                args.backend_image
            )
        )

    host_output_dir = os.path.join(
        "/shared/output/",
        getpass.getuser(),
        "data",
        condor.get_condor_job_id(),
    )

    # The "host_output_dir" contains the unique job id, so if it already
    # exists, something is wrong.
    if os.path.exists(host_output_dir):
        raise RuntimeError(
            "Output directory {} already exists".format(host_output_dir)
        )

    # create job-specific "host_output_dir"
    os.mkdir(host_output_dir)

    # load user config
    user_config_file = os.path.expanduser(
        os.path.join("~", "payload", _userconf)
    )
    with open(user_config_file) as fh:
        user_config = json.load(fh)

    # Check if user configured custom user image.  If not, use the backend
    # image.
    try:
        singularity_user_image = os.path.expanduser(
            os.path.join("~", "payload", user_config["singularity_image"])
        )
    except KeyError:
        singularity_user_image = args.backend_image

    if not os.path.exists(singularity_user_image):
        raise FileNotFoundError(
            "User Singularity image {} does not exist".format(
                singularity_user_image
            )
        )

    logging.info("Using singularity image %s", singularity_user_image)

    # If configured, use the "git_deploy_key" for git commands.
    try:
        user_key = os.path.expanduser(
            os.path.join("~", "payload", user_config["git_deploy_key"])
        )
        git_ssh_command = "ssh -i {} -o StrictHostKeyChecking=no".format(
            user_key
        )
    except KeyError:
        git_ssh_command = "ssh -o StrictHostKeyChecking=no"

    # directory from the user home that is bound into the container (can be
    # used to provide files that are too large for git)
    host_user_data_dir = os.path.expanduser(os.path.join("~", "payload"))

    # make sure the episode length does not exceed the allowed maximum
    episode_length = user_config.get("episode_length", DEFAULT_EPISODE_LENGTH)
    episode_length = min(int(episode_length), MAX_EPISODE_LENGTH)

    config = JobConfig(
        singularity_binary="singularity",
        singularity_backend_image=args.backend_image,
        singularity_user_image=singularity_user_image,
        host_output_dir=host_output_dir,
        git_repository=user_config["repository"],
        git_branch=user_config.get("branch", "master"),
        git_ssh_command=git_ssh_command,
        host_user_data_dir=host_user_data_dir,
        episode_length=episode_length,
        task=Task[args.task],
    )

    return config


def make_local_execution_config():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        required=True,
        help="""Path to the output directory.  All output files will be
                stored there.""",
    )
    parser.add_argument(
        "--repository",
        "-r",
        type=str,
        required=True,
        help="Git repository with the user code.",
    )
    parser.add_argument(
        "--branch",
        "-b",
        type=str,
        default="master",
        help="Branch of the Git repository that is used.",
    )
    parser.add_argument(
        "--backend-image",
        type=str,
        required=True,
        help="Path to the Singularity image for the backend.",
    )
    parser.add_argument(
        "--user-image",
        type=str,
        help="""Path to the Singularity image for the user code.  If not
        specified, the same image as for the backend is used.""",
    )
    parser.add_argument(
        "--user-data-dir",
        type=str,
        help="If set, bind this to '/userhome' when running the user code.",
    )
    parser.add_argument(
        "--episode-length",
        type=int,
        default=DEFAULT_EPISODE_LENGTH,
        help="Number of actions that are executed on the robot.",
    )
    parser.add_argument(
        "--task",
        type=str,
        choices=[x.name for x in Task],
        default=Task.NONE.name,
        help="""Which task to execute (affects type of goals and whether object
            tracking is used or not).
        """,
    )
    parser.add_argument(
        "--sim-visualize",
        action="store_true",
        help="Enable visualisation (only relevant when using simulation).",
    )
    parser.add_argument(
        "--sim-render-images",
        action="store_true",
        help="""Enable rendering of camera images (only relevant when using
            simulation).
        """,
    )
    parser.add_argument(
        "--singularity-nv",
        action="store_true",
        help="""Run Singularity container for the simulation backend with --nv.
            This is needed when running on a machine that uses Nvidia drivers.
        """,
    )
    args = parser.parse_args()

    singularity_backend_image = os.path.abspath(args.backend_image)
    if args.user_image:
        singularity_user_image = os.path.abspath(args.user_image)
    else:
        singularity_user_image = singularity_backend_image

    if args.episode_length > MAX_EPISODE_LENGTH:
        logging.warning(
            "Episode length is reduced to not exceed the maximum of %d steps",
            MAX_EPISODE_LENGTH,
        )
        episode_length = MAX_EPISODE_LENGTH
    else:
        episode_length = args.episode_length

    config = JobConfig(
        singularity_binary="singularity",
        singularity_backend_image=singularity_backend_image,
        singularity_user_image=singularity_user_image,
        host_output_dir=args.output_dir,
        git_repository=args.repository,
        git_branch=args.branch,
        host_user_data_dir=args.user_data_dir,
        episode_length=episode_length,
        task=Task[args.task],
        sim_visualize=args.sim_visualize,
        sim_render_images=args.sim_render_images,
        singularity_nv=args.singularity_nv,
    )

    return config
