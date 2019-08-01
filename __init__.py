"""adutils - helper functions for AppDaemon apps

  @benleb / https://github.com/benleb/adutils
"""

import pprint
from typing import Callable, Optional


def show_info(
    log: Callable, app_name: str, config: dict, sensors: set, icon: Optional[str] = None
) -> None:
    # output initialized values
    log("")

    # enable non-ascii chars like emoji
    ascii_encode = True

    if icon:
        app_name = f"{icon} \033[1m{app_name}\033[0m"
        ascii_encode = False

    log(app_name, ascii_encode=ascii_encode)

    # output app configuration
    for key, value in config.items():

        if key == "delay":
            value = f"{int(value / 60)}:{int(value % 60):02d} minutes ~ {value} seconds"

        if isinstance(value, list):

            log(f"  {key}:")

            for list_value in value:

                if isinstance(list_value, dict):
                    name = list_value.pop("name", "")
                    log(
                        f"    - \033[1m{name}\033[0m: {pprint.pformat(list_value, compact=True)}"
                    )
                else:
                    log(f"    - \033[1m{list_value}\033[0m")

                continue
        else:
            log(f"  {key}: \033[1m{value}\033[0m")

    if sensors:
        log(f"  state listener:")
        [log(f"    - \033[1m{sensor}\033[0m") for sensor in sorted(sensors)]

    log("")
