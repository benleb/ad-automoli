import sys
from os.path import dirname
from typing import Iterable, Optional

from pkg_resources import working_set

# get requirements from file
required = {req.rstrip("\n") for req in open(f"{dirname(__file__)}/requirements.txt")}
installed = {pkg.key for pkg in working_set}
missing_packages = required - installed


def is_venv() -> bool:
    return hasattr(sys, "real_prefix")


def install_packages(requirements: Iterable[str], venv: Optional[str] = None) -> bool:
    """Install a package on PyPi. Accepts pip compatible package strings.
    Return boolean if install successful.
    """
    from subprocess import run
    from sys import executable

    print(f"installing required packages: {requirements}")

    command = [
        executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--upgrade",
        *requirements,
    ]

    if not is_venv():
        command += ["--user"]

    pip = run(command, universal_newlines=True)

    if pip.returncode != 0:
        print(
            f"unable to install packages: {requirements}"
            f"{pip.stderr.lstrip().strip()}"
        )
        return False

    print(f"{requirements} successfully installed!")

    return True
