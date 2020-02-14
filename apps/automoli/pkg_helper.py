import os
import sys
# from site import getuserbase
from typing import Dict, List, Set

from pkg_resources import Distribution, Requirement
from pkg_resources import parse_requirements as parse
from pkg_resources import working_set


def missing_requirements(requirements: Set[str]) -> Set[Requirement]:
    required = {req for req in parse(requirements) if not working_set.find(req)}
    installed = {pkg.as_requirement() for pkg in working_set}
    missing = {req for req in required - installed}
    return missing


def is_virtual_env() -> bool:
    """Check if we run in a venv/virtualenv."""
    return getattr(sys, "base_prefix", sys.prefix) != sys.prefix or hasattr(
        sys, "real_prefix"
    )


def install_packages(requirements: Set[Requirement]) -> bool:
    """Install a package on PyPi."""
    from subprocess import run

    package_list = [str(r) for r in requirements]
    print(f"installing packages: {', '.join(package_list)}")

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--upgrade",
        *package_list,
    ]

    # if not is_virtual_env():
    #     os.environ.copy()["PYTHONUSERBASE"] = os.path.abspath(getuserbase())
    #     command.append("--user")
    #     command.append("--prefix=")

    print(f"installing via: {' '.join(command)}")
    pip = run(command, universal_newlines=True)

    if pip.returncode != 0:
        print(f"unable to install packages: {', '.join(package_list)}")
        print(pip.stderr)
        return False

    print(f"packages installed: {', '.join(package_list)}")
    return True
