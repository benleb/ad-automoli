import os
from typing import List, Optional

from pkg_resources import DistributionNotFound, Requirement, get_provider


def handle_requirements(requirements: List[str], venv: Optional[str] = None,) -> bool:
    """Install a package on PyPi. Accepts pip compatible package strings.
    Return boolean if install successful.
    """
    from subprocess import run
    from sys import executable

    for package in [Requirement.parse(req) for req in requirements]:
        try:
            # version(package.project_name)
            get_provider(package)
        except (ModuleNotFoundError, DistributionNotFound):

            print(f"Installing required package {package}...")

            env = os.environ.copy()
            command = [
                executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--upgrade",
                str(package),
            ]

            if venv:
                # assert not is_virtual_env()
                # This only works if not running in venv
                command += ["--user"]
                env["PYTHONUSERBASE"] = os.path.abspath(venv)
                command += ["--prefix="]

            pip = run(command, universal_newlines=True)

            if pip.returncode != 0:
                print(
                    "Unable to install package %s: %s",
                    package,
                    pip.stderr.lstrip().strip(),
                )
                return False

            print(f"{package} successfully installed!")

        except ValueError:
            continue

    return True
