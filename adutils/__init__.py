"""adutils - helper functions for AppDaemon apps

  @benleb / https://github.com/benleb/adutils
"""

from pprint import pformat
from typing import Any, Dict, Iterable, Optional


class ADutils:
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        icon: Optional[str] = None,
        ad: Any = None,
    ) -> None:
        self._name = name
        self.icon = icon
        self.config = config
        self.ad = ad

    @property
    def appdaemon_v3(self) -> bool:
        return bool(int(self.ad.get_ad_version()[0]) < 4)

    @property
    def name(self) -> str:
        return self._name

    def log(
        self, msg: str, icon: Optional[str] = None, *args: Any, **kwargs: Any
    ) -> None:

        kwargs.setdefault("ascii_encode", False)

        if self.appdaemon_v3:
            icon = None
            kwargs.pop("ascii_encode", None)

        message = f"{f'{icon} ' if icon else ' '}{msg}"

        try:
            self.ad.log(message, *args, **kwargs)
        except Exception as error:
            print(f"Oh shit! Writing to AD logger failed: {error}")

    def show_info(self) -> None:
        self.log("")
        self.log(f"\033[1m{self.name}\033[0m", icon=self.icon)

        listeners = self.config.pop("listeners", None)

        for key, value in self.config.items():

            if key == "delay":
                value = f"{int(value / 60)}:{int(value % 60):02d}min ≈ {value}sec"
            if isinstance(value, list):
                self.print_collection(key, value, 2)
            elif isinstance(value, dict):
                self.print_collection(key, value, 4)
            else:
                self.log(f"  {key}: \033[1m{value}\033[0m")

        if listeners:
            self.log(f"  event listeners:")
            for listener in sorted(listeners):
                self.log(f"    - \033[1m{listener}\033[0m")

        self.log("")

    def print_collection(
        self, key: str, collection: Iterable[Any], indentation: int = 2
    ) -> None:

        self.log(f"{indentation * ' '}{key}:")
        indentation = indentation + 2

        for item in collection:
            indent = indentation * " "

            if isinstance(item, dict):

                if "name" in item:
                    self.print_collection(item.pop("name", ""), item, indentation)
                else:
                    self.log(f"{indent}\033[1m{pformat(item, compact=True)}\033[0m")

            elif isinstance(collection, dict):
                self.log(f"{indent}{item}: \033[1m{collection[item]}\033[0m")

            else:
                self.log(f"{indent}- \033[1m{item}\033[0m")
