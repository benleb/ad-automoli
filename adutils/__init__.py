"""adutils - helper functions for AppDaemon apps

  @benleb / https://github.com/benleb/adutils
"""

from pprint import pformat
from typing import Any, Callable, Dict, Iterable, Optional


def show_info(
    log: Callable[[Any], None],
    app_name: str,
    config: Dict[str, Any],
    sensors: Iterable[str],
    appdaemon_version: str = "",
    icon: Optional[str] = None,
) -> None:
    # output initialized values
    log("")

    appdaemon_v3: bool = bool(int(appdaemon_version[0]) < 4)

    if appdaemon_v3:
        log(app_name)
    else:
        app_name = f"{icon if icon else ''} \033[1m{app_name}\033[0m"
        log(app_name, ascii_encode=False)

    for key, value in config.items():

        if key == "delay":
            value = f"{int(value / 60)}:{int(value % 60):02d} minutes ~ {value} seconds"

        if isinstance(value, list):
            print_collection(log, key, value, 2)

        elif isinstance(value, dict):
            print_collection(log, key, value, 4)

        else:
            log(f"  {key}: \033[1m{value}\033[0m")

    if sensors:
        log(f"  state listener:")
        _ = [log(f"    - \033[1m{sensor}\033[0m") for sensor in sorted(sensors)]

    log("")


def print_collection(
    log: Callable[[Any], None],
    key: str,
    collection: Iterable[Any],
    indentation: int = 0,
) -> None:

    log(f"{indentation * ' '}{key}:")
    indentation = indentation + 2

    for item in collection:
        indent = indentation * " "

        if isinstance(item, dict):

            if "name" in item:
                print_collection(log, item.pop("name", ""), item, indentation)
            else:
                log(f"{indent}\033[1m{pformat(item, compact=True)}\033[0m")

        elif isinstance(collection, dict):
            log(
                f"{indent}{item}: \033[1m{pformat(collection[item], compact=True)}\033[0m"
            )

        else:
            log(f"{indent}- \033[1m{item}\033[0m")
