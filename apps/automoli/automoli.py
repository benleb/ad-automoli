"""AutoMoLi.
   Automatic Motion Lights

  @benleb / https://github.com/benleb/ad-automoli
"""

__version__ = "0.7.1"

from collections import defaultdict
from datetime import time
from pprint import pformat
from sys import version_info
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Union

import hassapi as hass


APP_NAME = "AutoMoLi"
APP_ICON = "💡"

ON_ICON = APP_ICON
OFF_ICON = "🌑"
DAYTIME_SWITCH_ICON = "⏰"

# default values
DEFAULT_NAME = "daytime"
DEFAULT_LIGHT_SETTING = 100
DEFAULT_DELAY = 150
DEFAULT_DAYTIMES = [
    dict(starttime="05:30", name="morning", light=25),
    dict(starttime="07:30", name="day", light=100),
    dict(starttime="20:30", name="evening", light=90),
    dict(starttime="22:30", name="night", light=0),
]

EVENT_MOTION_XIAOMI = "xiaomi_aqara.motion"

KEYWORD_LIGHTS = "light."
KEYWORD_MOTION = "binary_sensor.motion_sensor_"
KEYWORD_HUMIDITY = "sensor.humidity_"
KEYWORD_ILLUMINANCE = "sensor.illumination_"

KEYWORDS = {
    "humidity": "sensor.humidity_",
    "illuminance": "sensor.illumination_",
    "light": "light.",
    "motion": "binary_sensor.motion_sensor_",
}

SENSORS_REQUIRED = ["motion"]
SENSORS_OPTIONAL = ["humidity", "illuminance"]

RANDOMIZE_SEC = 5


# version checks
py3_or_higher = version_info.major >= 3
py37_or_higher = py3_or_higher and version_info.minor >= 7
py38_or_higher = py3_or_higher and version_info.minor >= 8


def hl(text: Union[int, float, str]) -> str:
    return f"\033[1m{text}\033[0m"


def hl_entity(entity: str) -> str:
    domain, entity = entity.split(".")
    return f"{domain}.{hl(entity)}"


class AutoMoLi(hass.Hass):  # type: ignore
    """Automatic Motion Lights."""

    def lg(self, msg: str, *args: Any, icon: Optional[str] = None, repeat: int = 1, **kwargs: Any) -> None:
        kwargs.setdefault("ascii_encode", False)
        message = f"{f'{icon} ' if icon else ' '}{msg}"
        [self.log(message, *args, **kwargs) for _ in range(repeat)]

    def initialize(self) -> None:
        """Initialize a room with AutoMoLi."""
        self.icon = APP_ICON

        # python version check
        if not py38_or_higher:
            icon_alert = "⚠️"
            self.lg("", icon=icon_alert)
            self.lg("")
            self.lg(f"please update to {hl('Python >= 3.8.0')}! 🤪", icon=icon_alert)
            self.lg("")
            self.lg("", icon=icon_alert)
        if not py37_or_higher:
            raise ValueError

        # set room
        self.room = str(self.args.get("room"))

        # state values
        self.states = {
            "motion_on": self.args.get("motion_state_on", None),
            "motion_off": self.args.get("motion_state_off", None),
        }

        # threshold values
        self.thresholds = {
            "humidity": self.args.get("humidity_threshold"),
            "illuminance": self.args.get("illuminance_threshold"),
        }

        # on/off switch via input.boolean
        self.disable_switch_entity = self.args.get("disable_switch_entity")

        # currently active daytime settings
        self.active: Dict[str, Union[int, str]] = {}

        # lights_off callback handle
        self._handle = None

        # define light entities switched by automoli
        self.lights: Set[str] = self.args.get("lights", set())
        if not self.lights:
            room_light_group = f"light.{self.room}"
            if self.entity_exists(room_light_group):
                self.lights.add(room_light_group)
            else:
                self.lights.update(self.find_sensors(KEYWORD_LIGHTS))

        # sensors
        self.sensors: DefaultDict[str, Any] = defaultdict(set)
        # enumerate sensors for motion detection
        self.sensors["motion"] = set(self.args.get("motion", self.find_sensors(KEYWORD_MOTION)))

        # requirements check
        if not self.lights or not self.sensors["motion"]:
            raise ValueError(f"No lights/sensors given/found, sorry! ('{KEYWORD_LIGHTS}'/'{KEYWORD_MOTION}')")

        # enumerate optional sensors & disable optional features if sensors are not available
        for sensor_type in SENSORS_OPTIONAL:
            self.sensors[sensor_type] = set(self.args.get(sensor_type, self.find_sensors(KEYWORDS[sensor_type])))
            if self.thresholds[sensor_type] and not self.sensors[sensor_type]:
                self.log(f"No {sensor_type} sensors → disabling features based on {sensor_type}.")
                self.thresholds[sensor_type] = None

        # use user-defined daytimes if available
        self.build_daytimes(self.args.get("daytimes", DEFAULT_DAYTIMES))

        # set up event listener for each sensor
        for sensor in self.sensors["motion"]:

            # listen to xiaomi sensors by default
            if not any((self.states["motion_on"], self.states["motion_off"])):
                self.listen_event(self.motion_event, event=EVENT_MOTION_XIAOMI, entity_id=sensor)

            # on/off-only sensors without events on every motion
            elif all((self.states["motion_on"], self.states["motion_off"])):
                self.listen_state(self.motion_detected, entity=sensor, new=self.states["motion_on"])
                self.listen_state(self.motion_cleared, entity=sensor, new=self.states["motion_off"])

            self.refresh_timer()

        # self.adu.show_info(self.args)
        self.show_info(self.args)

    def switch_daytime(self, kwargs: Dict[str, Any]) -> None:
        """Set new light settings according to daytime."""
        daytime = kwargs.get("daytime")

        if daytime is not None:
            self.active = daytime
            if not kwargs.get("initial"):

                delay = daytime["delay"]
                light_setting = daytime["light_setting"]
                if isinstance(light_setting, str):
                    is_scene = True
                    # if its a ha scene, remove the "scene." part
                    if "." in light_setting:
                        light_setting = (light_setting.split("."))[1]
                else:
                    is_scene = False

                self.lg(
                    f"set {hl(self.room.capitalize())} to {hl(daytime['daytime'])} → "
                    f"{'scene' if is_scene else 'brightness'}: {hl(light_setting)}"
                    f"{'' if is_scene else '%'}, delay: {hl(delay)}sec",
                    icon=DAYTIME_SWITCH_ICON,
                )

    def motion_cleared(self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]) -> None:
        # starte the timer if motion is cleared
        if all((self.get_state(sensor) == self.states["motion_off"] for sensor in self.sensors["motion"])):
            # all motion sensors off, starting timer
            self.refresh_timer()
        else:
            if self._handle:
                # cancelling active timer
                self.cancel_timer(self._handle)

    def motion_detected(self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]) -> None:
        # wrapper function

        if self._handle:
            # cancelling active timer
            self.cancel_timer(self._handle)

        # calling motion event handler
        data: Dict[str, Any] = {"entity_id": entity, "new": new, "old": old}
        self.motion_event("state_changed_detection", data, kwargs)

    def motion_event(self, event: str, data: Dict[str, str], kwargs: Dict[str, Any]) -> None:
        """Handle motion events."""
        self.lg(
            f"received '{event}' event from " f"'{data['entity_id'].replace(KEYWORD_MOTION, '')}'", level="DEBUG",
        )

        # check if automoli is disabled via home assistant entity
        if self.get_state(self.disable_switch_entity, copy=False) == "off":
            self.lg(f"AutoMoLi disabled via {self.disable_switch_entity}",)
            return

        # turn on the lights if not already
        if not any((self.get_state(light) == "on" for light in self.lights)):
            self.lights_on()
        else:
            self.lg(
                f"light in {self.room.capitalize()} already on → refreshing the timer", level="DEBUG",
            )

        if event != "state_changed_detection":
            self.refresh_timer()

    def refresh_timer(self) -> None:
        """Refresh delay timer."""
        self.cancel_timer(self._handle)
        if self.active["delay"] != 0:
            self._handle = self.run_in(self.lights_off, self.active["delay"])

    def lights_on(self) -> None:
        """Turn on the lights."""
        if self.thresholds["illuminance"]:
            blocker = []
            for sensor in self.sensors["illuminance"]:
                try:
                    if float(self.get_state(sensor)) >= self.thresholds["illuminance"]:
                        blocker.append(sensor)
                except ValueError as error:
                    self.lg(f"could not parse illuminance '{self.get_state(sensor)}' from " f"'{sensor}': {error}")
                    return

            if blocker:
                self.lg(f"According to {hl(' '.join(blocker))} its already bright enough")
                return

        if isinstance(self.active["light_setting"], str):

            for entity in self.lights:

                if self.active["is_hue_group"] and self.get_state(entity_id=entity, attribute="is_hue_group"):
                    self.call_service(
                        "hue/hue_activate_scene",
                        group_name=self.friendly_name(entity),
                        scene_name=self.active["light_setting"],
                    )
                    continue

                item = entity

                if self.active["light_setting"].startswith("scene."):
                    item = self.active["light_setting"]

                # self.turn_on(item)
                self.call_service("homeassistant/turn_on", entity_id=item)

            self.lg(
                f"{hl(self.room.capitalize())} turned {hl(f'on')} → "
                f"{'hue' if self.active['is_hue_group'] else 'ha'} scene: "
                f"{hl(self.active['light_setting'].replace('scene.', ''))}",
                icon=ON_ICON,
            )

        elif isinstance(self.active["light_setting"], int):

            if self.active["light_setting"] == 0:
                self.lights_off(dict())

            else:
                for entity in self.lights:
                    if entity.startswith("switch."):
                        self.call_service("homeassistant/turn_on", entity_id=entity)
                    else:
                        self.call_service(
                            "homeassistant/turn_on", entity_id=entity, brightness_pct=self.active["light_setting"],
                        )

                        self.lg(
                            f"{hl(self.room.capitalize())} turned {hl(f'on')} → "
                            f"brightness: {hl(self.active['light_setting'])}%",
                            icon=ON_ICON,
                        )

        else:
            raise ValueError(f"invalid brightness/scene: {self.active['light_setting']!s} " f"in {self.room}")

    def lights_off(self, kwargs: Dict[str, Any]) -> None:
        """Turn off the lights."""

        # check if automoli is disabled via home assistant entity
        if self.get_state(self.disable_switch_entity, copy=False) == "off":
            self.lg(f"AutoMoLi disabled via {self.disable_switch_entity}",)
            return

        blocker: List[str] = []

        if self.thresholds["humidity"]:
            blocker = [
                sensor
                for sensor in self.sensors["humidity"]
                if float(self.get_state(sensor)) >= self.thresholds["humidity"]
            ]

        # turn off if not blocked
        if blocker:
            self.refresh_timer()
            self.lg(
                f"🛁 no motion in {hl(self.room.capitalize())} since "
                f"{hl(self.active['delay'])}s → "
                f"but {hl(float(self.get_state(blocker)))}%RH > "
                f"{self.thresholds['humidity']}%RH"
            )
        else:
            self.cancel_timer(self._handle)
            if any(((self.get_state(entity)) == "on" for entity in self.lights)):
                for entity in self.lights:
                    self.turn_off(entity)
                self.lg(
                    f"no motion in {hl(self.room.capitalize())} since "
                    f"{hl(self.active['delay'])}s → turned {hl(f'off')}",
                    icon=OFF_ICON,
                )

    def find_sensors(self, keyword: str) -> List[str]:
        """Find sensors by looking for a keyword in the friendly_name."""
        return [
            sensor
            for sensor in self.get_state()
            if keyword in sensor and self.room in (self.friendly_name(sensor)).lower().replace("ü", "u")
        ]

    def build_daytimes(self, daytimes: List[Any]) -> Optional[List[Dict[str, Union[int, str]]]]:
        starttimes: Set[time] = set()
        delay = int(self.args.get("delay", DEFAULT_DELAY))

        for idx, daytime in enumerate(daytimes):
            dt_name = daytime.get("name", f"{DEFAULT_NAME}_{idx}")
            dt_delay = daytime.get("delay", delay)
            dt_light_setting = daytime.get("light", DEFAULT_LIGHT_SETTING)
            dt_is_hue_group = (
                isinstance(dt_light_setting, str)
                and not dt_light_setting.startswith("scene.")
                and any((self.get_state(entity_id=entity, attribute="is_hue_group") for entity in self.lights))
            )

            dt_start: time
            try:
                dt_start = time.fromisoformat(str(daytime.get("starttime")))
            except ValueError as error:
                raise ValueError(f"missing start time in daytime '{dt_name}': {error}")

            # configuration for this daytime
            daytime = dict(
                daytime=dt_name,
                delay=dt_delay,
                starttime=dt_start.isoformat(),  # datetime is not serializable
                light_setting=dt_light_setting,
                is_hue_group=dt_is_hue_group,
            )

            # info about next daytime
            next_dt_start = time.fromisoformat(str(daytimes[(idx + 1) % len(daytimes)].get("starttime")))

            # collect all start times for sanity check
            if dt_start in starttimes:
                raise ValueError(f"Start times of all daytimes have to be unique! " f"Duplicate found: {dt_start}",)

            starttimes.add(dt_start)

            # check if this daytime should ne active now
            if self.now_is_between(str(dt_start), str(next_dt_start)):
                self.switch_daytime(dict(daytime=daytime, initial=True))
                self.args["active_daytime"] = daytime.get("daytime")

            # schedule callbacks for daytime switching
            self.run_daily(
                self.switch_daytime,
                dt_start,
                random_start=-RANDOMIZE_SEC,
                random_end=RANDOMIZE_SEC,
                **dict(daytime=daytime),
            )

        return daytimes

    def show_info(self, config: Optional[Dict[str, Any]] = None) -> None:
        # check if a room is given
        if config:
            self.config = config

        if not self.config:
            self.lg("no configuration available", icon="‼️", level="ERROR")
            return

        room = ""
        if "room" in self.config:
            room = f" - {hl(self.config['room'].capitalize())}"

        self.lg("")
        self.lg(f"{hl(APP_NAME)}{room}", icon=self.icon)
        self.lg("")

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
            self.lg("  event listeners:")
            for listener in sorted(listeners):
                self.lg(f"    - {hl(listener)}")

        self.lg("")

    def print_collection(self, key: str, collection: Iterable[Any], indentation: int = 2) -> None:

        self.log(f"{indentation * ' '}{key}:")
        indentation = indentation + 2

        for item in collection:
            indent = indentation * " "

            if isinstance(item, dict):
                if "name" in item:
                    self.print_collection(item.pop("name", ""), item, indentation)
                else:
                    self.log(f"{indent}{hl(pformat(item, compact=True))}")

            elif isinstance(collection, dict):
                self._print_cfg_setting(item, collection[item], indentation)

            else:
                self.log(f"{indent}- {hl(item)}")

    def _print_cfg_setting(self, key: str, value: Union[int, str], indentation: int) -> None:
        unit = prefix = ""
        indent = indentation * " "

        # legacy way
        if key == "delay" and isinstance(value, int):
            unit = "min"
            min_value = f"{int(value / 60)}:{int(value % 60):02d}"
            self.log(f"{indent}{key}: {prefix}{hl(min_value)}{unit} ~≈ " f"{hl(value)}sec")

        else:
            if "_units" in self.config and key in self.config["_units"]:
                unit = self.config["_units"][key]
            if "_prefixes" in self.config and key in self.config["_prefixes"]:
                prefix = self.config["_prefixes"][key]

            self.log(f"{indent}{key}: {prefix}{hl(value)}{unit}")
