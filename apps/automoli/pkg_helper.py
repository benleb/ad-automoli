import sys
from typing import Dict, List

from pkg_resources import Requirement, working_set


def get_requirements() -> Dict[str, Requirement]:
    from os.path import dirname

    requirements: Dict[str, Requirement] = {}
    for required_package in open(f"{dirname(__file__)}/requirements.txt"):
        req: Requirement = Requirement.parse(required_package.rstrip("\n"))
        requirements[req.key] = req
    return requirements


def missing_requirements() -> List[Requirement]:
    requirements = get_requirements()
    required = {req for req in requirements.keys()}
    installed = {pkg.key for pkg in working_set}
    missing = [requirements[req] for req in required - installed]
    return missing


def install_packages(requirements: List[Requirement]) -> bool:
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

    pip = run(command, universal_newlines=True)

    if pip.returncode != 0:
        print(f"unable to install packages: {', '.join(package_list)}")
        print(pip.stderr)
        return False

    print(f"packages installed: " f"{', '.join(package_list)}")
    return True
