"""Information about running process."""

import psutil


class ProcessInfo:
    """Provides information about a running process."""

    def __init__(self, pid):
        """Initializes process information.

        Args:
          pid (int): process identifier (PID).

        Raises:
          OSError: If the process identified by the PID does not exist.
        """
        if not psutil.pid_exists(pid):
            raise OSError(f"Process with PID: {pid:d} does not exist")

        self._process = psutil.Process(pid)

    def GetUsedMemory(self):
        """Retrieves data plus shared memory, or resident memory when unavailable.

        Returns:
          int: amount of memory in bytes used by the process or None
              if not available.
        """
        try:
            memory_info = self._process.memory_info()
        except psutil.NoSuchProcess:
            return None

        # Preserve data + shared accounting where both fields are available.
        # macOS and Windows do not provide these fields. Returning zero there
        # would also disable the engine's periodic worker memory-limit check.
        if hasattr(memory_info, "data") and hasattr(memory_info, "shared"):
            return memory_info.data + memory_info.shared

        return memory_info.rss
