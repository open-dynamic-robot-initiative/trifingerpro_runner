Simulation Submission Runner
============================

Launcher scripts to execute user code provided in the form of a "submission" on
a simulated TriFingerPro robot.


Structure of the User Code Package
----------------------------------

The package provided by the user needs to be a package that can be built be
colcon and needs to provide an executable (e.g. a shell or Python script) called
`run` at its root directory.  This `run` executable is what is going to be
executed on the robot.


How to Run
----------

To execute a job in simulation, run `run_simulation.py`:

    ./run_simulation.py --output-dir ~/output \
                        --repository git@github.com:myuser/myrepo.git \
                        --backend-image path/to/rrc2021.sif
                        --task MOVE_CUBE_ON_TRAJECTORY

Use `--help` for a complete list of arguments.

Note that when executed from the root directory of this package, there is
actually no need to install it.


The Execution Procedure
-----------------------

When running a job, the following actions are performed:

1. Create a temporary colcon workspace structure.  The user code will be built
   inside there and it will be deleted in the end.
2. Clone a configured repository into the workspace.
3. Build the workspace by running `colcon` in a Singularity container.
4. Run the data and robot backend in Singularity containers and wait until they
   are ready.
5. Run the `run` script from the user repository in a Singularity container.
6. Monitor the running processes.  When one of them terminates, shut down the
   others in the appropriate order.
7. Store logs, outputs and some meta information in the output directory.


Singularity Images
------------------

There are two different Singularity images in use:

1. The "backend image".  This is our standard robot image.  Used to run the
   backend nodes.  Cannot be changed by the user.
2. The user image.  Used to build and run the user code.  By default this is the
   same as 1. but it can be extended by the user, e.g. to add custom
   dependencies.  It is in the responsibility of the user to ensure that when
   doing this, the image is still compatible with our setup.
