"""adutils - helper functions for AppDaemon apps

  @benleb / https://github.com/benleb/adutils
"""

from pprint import pformat
from typing import Any, Dict, Iterable, Optional, Union


class ADutils:
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        icon: Optional[str] = None,
        ad: Any = None,
        show_config: bool = False,
    ) -> None:
        self._name = name
        self.icon = icon
        self.config = config
        self.ad = ad

        if show_config:
            self.show_info()

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
        # check if a room is given
        room = ""
        if "room" in self.config:
            room = f" - \033[1m{self.config['room'].capitalize()}\033[0m"

        self.log("")
        self.log(f"\033[1m{self.name}\033[0m{room}", icon=self.icon)
        self.log("")

        listeners = self.config.pop("listeners", None)

        for key, value in self.config.items():

            # hide "internal keys" when displaying config
            if key in ["module", "class"] or key.startswith("_"):
                continue

            if isinstance(value, list):
                self.print_collection(key, value, 2)
            elif isinstance(value, dict):
                self.print_collection(key, value, 2)
            else:
                self._print_cfg_setting(key, value, 2)

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
                self._print_cfg_setting(item, collection[item], indentation)

            else:
                self.log(f"{indent}- \033[1m{item}\033[0m")

    @staticmethod
    def hl(text: str) -> str:
        return f"\033[1m{text}\033[0m"

    @staticmethod
    def hl_entity(entity: str) -> str:
        domain, entity = entity.split(".")
        return f"{domain}.{ADutils.hl(entity)}"

    def _print_cfg_setting(
        self, key: str, value: Union[int, str], indentation: int
    ) -> None:
        unit = prefix = ""
        indent = indentation * " "

        # legacy way
        if key == "delay" and isinstance(value, int):
            unit = "min"
            min_value = f"{int(value / 60)}:{int(value % 60):02d}"
            self.log(
                f"{indent}{key}: {prefix}\033[1m{min_value}\033[0m{unit} ≈ "
                f"\033[1m{value}\033[0msec"
            )

        else:
            if "_units" in self.config and key in self.config["_units"]:
                unit = self.config["_units"][key]
            if "_prefixes" in self.config and key in self.config["_prefixes"]:
                prefix = self.config["_prefixes"][key]

            self.log(f"{indent}{key}: {prefix}\033[1m{value}\033[0m{unit}")
