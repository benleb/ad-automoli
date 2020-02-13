import sys
from os import environ
from os.path import abspath  # , dirname
from typing import Iterable, Optional

from pkg_resources import working_set

# get requirements from file
# required = required_versions = set()
# for req in open(f"{dirname(__file__)}/requirements.txt"):
#     required_versions.add(req.rstrip("\n"))
#     required.add(req.split("~"))

required = {"adutils"}
installed = {pkg.key for pkg in working_set}
missing_packages = required - installed


def is_venv() -> bool:
    return getattr(sys, "base_prefix", sys.prefix) != sys.prefix or hasattr(
        sys, "real_prefix"
    )


def install_packages(requirements: Iterable[str], target: Optional[str] = None) -> bool:
    """Install a package on PyPi. Accepts pip compatible package strings.
    Return boolean if install successful.
    """
    from subprocess import run
    from sys import executable

    print(f"installing required packages: {', '.join([r for r in requirements])}")

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

    if not is_venv() and target:
        command += ["--user"]
        environ.copy()["PYTHONUSERBASE"] = abspath(target)
        command += ["--prefix="]

    pip = run(command, universal_newlines=True)

    if pip.returncode != 0:
        print(f"unable to install packages: {', '.join([r for r in requirements])}")
        print(f"{pip.stderr}")
        return False

    print(f"{', '.join([r for r in requirements])} successfully installed!")

    return True
