"""Classes to represent process states."""

__copyright__ = "Copyright (c) 2021 Max Planck Gesellschaft"
__license__ = "BSD 3-Clause"

import enum


class ProcessState(enum.Enum):
    """Process state."""

    #: Terminated cleanly (i.e. returncode == 0)
    TERMINATED_SUCCESS = 0

    #: Terminated with error (returncode != 0)
    TERMINATED_ERROR = 1

    #: Still running
    RUNNING = 2

    #: Terminated (no matter which returncode)
    TERMINATED_ANY = 3


class ProcessStateCompareWrapper:
    """Wrapper around ProcessState to provide proper ``__eq__`` handling of GOOD_OR_BAD.

    Wraps around the ProcessState enum and provides a custom ``__eq__`` where
    ``GOOD == GOOD_OR_BAD`` and ``BAD == GOOD_OR_BAD`` evaluate to True.  This helps
    to simplify the state machine in cases where it only matters that a process has
    terminated, no matter if good or bad.
    """

    def __init__(self, state: ProcessState):
        self.state = state

    def __eq__(self, other):
        if self.state == other.state:
            return True
        elif self.state == ProcessState.TERMINATED_ANY and other.state in (
            ProcessState.TERMINATED_SUCCESS,
            ProcessState.TERMINATED_ERROR,
        ):
            return True
        elif other.state == ProcessState.TERMINATED_ANY and self.state in (
            ProcessState.TERMINATED_SUCCESS,
            ProcessState.TERMINATED_ERROR,
        ):
            return True
        else:
            return False

    def __repr__(self):
        # only print the plain state name
        return str(self.state.name)


class LauncherState:
    """Represents the combined state of all nodes monitored by the launcher."""

    def __init__(self, data_state, backend_state, user_state):
        self.data_state = data_state
        self.backend_state = backend_state
        self.user_state = user_state

    def __repr__(self):
        return "(Data: {}, Robot: {}, User: {})".format(
            self.data_state, self.backend_state, self.user_state
        )

    def __eq__(self, other):
        # allow comparison with tuple by converting it
        if type(other) is tuple:
            try:
                other = type(self)(*other)
            except Exception:
                return False

        return (
            (self.data_state == other.data_state)
            and (self.backend_state == other.backend_state)
            and (self.user_state == other.user_state)
        )
