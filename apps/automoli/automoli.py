"""AutoMoLi.
   Automatic Motion Lights

  @benleb / https://github.com/benleb/ad-automoli
"""

__version__ = "0.8.3"

import asyncio

from copy import deepcopy
from datetime import time
from pprint import pformat
from sys import version_info
from typing import Any, Coroutine, Dict, Iterable, List, Optional, Set, Union

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
DEFAULT_DIM_METHOD = "step"
DEFAULT_DAYTIMES: List[Dict[str, Union[str, int]]] = [
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
SECONDS_PER_MIN: int = 60


# version checks
py3_or_higher = version_info.major >= 3
py37_or_higher = py3_or_higher and version_info.minor >= 7
py38_or_higher = py3_or_higher and version_info.minor >= 8


def hl(text: Union[int, float, str]) -> str:
    return f"\033[1m{text}\033[0m"


def hl_entity(entity: str) -> str:
    domain, entity = entity.split(".")
    return f"{domain}.{hl(entity)}"


def natural_time(duration: Union[int, float]) -> str:

    duration_min, duration_sec = divmod(duration, float(SECONDS_PER_MIN))

    # append suitable unit
    if duration >= SECONDS_PER_MIN:
        if duration_sec < 10 or duration_sec > 50:
            natural = f"{hl(int(duration_min))}min"
        else:
            natural = f"{hl(int(duration_min))}min {hl(int(duration_sec))}sec"
    else:
        natural = f"{hl(int(duration_sec))}sec"

    return natural


class AutoMoLi(hass.Hass):  # type: ignore
    """Automatic Motion Lights."""

    def lg(self, msg: str, *args: Any, icon: Optional[str] = None, repeat: int = 1, **kwargs: Any) -> None:
        kwargs.setdefault("ascii_encode", False)
        message = f"{f'{icon} ' if icon else ' '}{msg}"
        _ = [self.log(message, *args, **kwargs) for _ in range(repeat)]

    def listr(self, list_or_string: Union[List[str], Set[str], str], entities_exist: bool = True) -> Set[str]:
        entity_list: List[str] = []

        if isinstance(list_or_string, str):
            entity_list.append(list_or_string)
        elif isinstance(list_or_string, list) or isinstance(list_or_string, set):
            entity_list += list_or_string
        elif list_or_string:
            self.lg(f"{list_or_string} is of type {type(list_or_string)} and not 'Union[List[str], Set[str], str]'")

        return set(filter(self.entity_exists, entity_list) if entities_exist else entity_list)

    async def initialize(self) -> None:
        """Initialize a room with AutoMoLi."""
        self.icon = APP_ICON

        # get a real dict for the configuration
        self.args = dict(self.args)

        # python version check
        if not py38_or_higher:
            icon_alert = "⚠️"
            self.lg("", icon=icon_alert)
            self.lg("")
            self.lg(f" please update to {hl('Python >= 3.8')}! 🤪", icon=icon_alert)
            self.lg("")
            self.lg("", icon=icon_alert)
        if not py37_or_higher:
            raise ValueError

        # set room
        self.room = str(self.args.pop("room"))

        # general delay
        self.delay = int(self.args.pop("delay", DEFAULT_DELAY))

        # state values
        self.states = {
            "motion_on": self.args.pop("motion_state_on", None),
            "motion_off": self.args.pop("motion_state_off", None),
        }

        # threshold values
        self.thresholds = {
            "humidity": self.args.pop("humidity_threshold", None),
            "illuminance": self.args.pop("illuminance_threshold", None),
        }

        # experimental dimming features
        self.dim: Optional[Dict[str, Union[float, int]]] = {}
        if (dim := self.args.pop("dim", {})) and (seconds_before := dim.pop("seconds_before", None)):

            brightness_step_pct = dim.pop("brightness_step_pct", None)

            dim_method: Optional[str] = None
            if method := dim.pop("method", None):
                dim_method = method
            elif brightness_step_pct:
                dim_method = DEFAULT_DIM_METHOD

            self.dim = {
                "brightness_step_pct": brightness_step_pct,
                "seconds_before": int(seconds_before),
                "method": str(dim_method),
            }

        # on/off switch via input.boolean
        self.disable_switch_entities: Set[str] = self.listr(self.args.pop("disable_switch_entities", set()))
        self.disable_switch_states: Set[str] = self.listr(self.args.pop("disable_switch_states", set(["off"])))

        self.disable_hue_groups: bool = self.args.pop("disable_hue_groups", False)

        # eol of the old option name
        if "disable_switch_entity" in self.args:
            icon_alert = "⚠️"
            self.lg("", icon=icon_alert)
            self.lg(
                f" please migrate {hl('disable_switch_entity')} to {hl('disable_switch_entities')}", icon=icon_alert
            )
            self.lg("", icon=icon_alert)
            self.args.pop("disable_switch_entity")
            return

        # currently active daytime settings
        self.active: Dict[str, Union[int, str]] = {}

        # entity lists for initial discovery
        states = await self.get_state()

        # define light entities switched by automoli
        self.lights: Set[str] = self.args.pop("lights", set())
        if not self.lights:
            room_light_group = f"light.{self.room}"
            if await self.entity_exists(room_light_group):
                self.lights.add(room_light_group)
            else:
                self.lights.update(await self.find_sensors(KEYWORD_LIGHTS, self.room, states))

        # sensors
        self.sensors: Dict[str, Any] = {}

        # enumerate sensors for motion detection
        self.sensors["motion"] = self.listr(
            self.args.pop("motion", await self.find_sensors(KEYWORD_MOTION, self.room, states))
        )

        # requirements check
        if not self.lights or not self.sensors["motion"]:
            self.lg("")
            self.lg(
                f"{hl('No lights/sensors')} given and none found with name: "
                f"'{hl(KEYWORD_LIGHTS)}*{hl(self.room)}*' or '{hl(KEYWORD_MOTION)}*{hl(self.room)}*'",
                icon="⚠️ ",
            )
            self.lg("")
            self.lg("  docs: https://github.com/benleb/ad-automoli")
            self.lg("")
            return

        # enumerate optional sensors & disable optional features if sensors are not available
        for sensor_type in SENSORS_OPTIONAL:

            if sensor_type in self.thresholds and self.thresholds[sensor_type]:
                self.sensors[sensor_type] = self.listr(self.args.pop("motion", None)) or await self.find_sensors(
                    KEYWORDS[sensor_type], self.room, states
                )

            else:
                self.lg(
                    f"No {sensor_type} sensors → disabling features based on {sensor_type}"
                    f" - {self.thresholds[sensor_type]}.",
                    level="DEBUG",
                )
                del self.thresholds[sensor_type]

        # use user-defined daytimes if available
        daytimes = await self.build_daytimes(self.args.pop("daytimes", DEFAULT_DAYTIMES))

        # set up event listener for each sensor
        listener: Set[Coroutine[Any, Any, Any]] = set()
        for sensor in self.sensors["motion"]:

            # listen to xiaomi sensors by default
            if not any([self.states["motion_on"], self.states["motion_off"]]):
                self.lg("no motion states configured - using event listener", level="DEBUG")
                listener.add(self.listen_event(self.motion_event, event=EVENT_MOTION_XIAOMI, entity_id=sensor))

            # on/off-only sensors without events on every motion
            elif all([self.states["motion_on"], self.states["motion_off"]]):
                self.lg("both motion states configured - using state listener", level="DEBUG")
                listener.add(self.listen_state(self.motion_detected, entity=sensor, new=self.states["motion_on"]))
                listener.add(self.listen_state(self.motion_cleared, entity=sensor, new=self.states["motion_off"]))

        # callback handles to switch lights off
        self.handles: Set[str] = set()

        self.args.update(
            {
                "room": self.room.capitalize(),
                "delay": self.delay,
                "active_daytime": self.active_daytime,
                "daytimes": daytimes,
                "lights": self.lights,
                "sensors": self.sensors,
                "disable_hue_groups": self.disable_hue_groups,
            }
        )

        if self.disable_switch_entities:
            self.args.update({"disable_switch_entities": self.disable_switch_entities})
            self.args.update({"disable_switch_states": self.disable_switch_states})

        # show parsed config
        self.show_info(self.args)

        await asyncio.gather(*listener)
        await self.refresh_timer()

    async def switch_daytime(self, kwargs: Dict[str, Any]) -> None:
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
                    f"{'' if is_scene else '%'}, delay: {hl(natural_time(delay))}",
                    icon=DAYTIME_SWITCH_ICON,
                )

    async def motion_cleared(self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]) -> None:
        # starte the timer if motion is cleared
        self.lg(f"motion cleared: {entity} changed {attribute} from {old} to {new}", level="DEBUG")

        if all([await self.get_state(sensor) == self.states["motion_off"] for sensor in self.sensors["motion"]]):
            # all motion sensors off, starting timer
            await self.refresh_timer()
        else:
            # cancel scheduled callbacks
            await self.clear_handles(deepcopy(self.handles))

    async def motion_detected(self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]) -> None:
        # wrapper function

        self.lg(f"motion detected: {entity} changed {attribute} from {old} to {new}", level="DEBUG")

        # cancel scheduled callbacks
        await self.clear_handles(deepcopy(self.handles))

        self.lg("handles cleared and cancelled all scheduled timers", level="DEBUG")

        # calling motion event handler
        data: Dict[str, Any] = {"entity_id": entity, "new": new, "old": old}
        await self.motion_event("state_changed_detection", data, kwargs)

    async def motion_event(self, event: str, data: Dict[str, str], kwargs: Dict[str, Any]) -> None:
        """Handle motion events."""
        self.lg(f"received '{event}' event from " f"'{data['entity_id'].replace(KEYWORD_MOTION, '')}'", level="DEBUG")

        # check if automoli is disabled via home assistant entity
        if await self.is_disabled():
            return

        # turn on the lights if not already
        if not any([await self.get_state(light) == "on" for light in self.lights]):
            await self.lights_on()
        else:
            self.lg(f"light in {self.room.capitalize()} already on → refreshing the timer", level="DEBUG")

        if event != "state_changed_detection":
            await self.refresh_timer()

    async def clear_handles(self, handles: Set[str]) -> None:
        """clear scheduled timers/callbacks."""
        self.handles.clear()
        [await self.cancel_timer(handle) for handle in handles]

    async def refresh_timer(self) -> None:
        """refresh delay timer."""

        # cancel scheduled callbacks
        await self.clear_handles(deepcopy(self.handles))

        # if no delay is set or delay = 0, lights will not switched off by AutoMoLi
        if delay := self.active.get("delay"):

            if self.dim:
                self.handles.add(await self.run_in(self.dim_lights, (int(delay) - self.dim["seconds_before"] + 2)))

            # schedule "turn off" callback
            self.handles.add(await self.run_in(self.lights_off, delay))

    async def is_disabled(self) -> bool:
        """check if automoli is disabled via home assistant entity"""
        for entity in self.disable_switch_entities:
            if (state := await self.get_state(entity, copy=False)) and state in self.disable_switch_states:
                self.lg(f"{APP_NAME} is disabled by {entity} with {state = }")
                return True

        return False

    async def dim_lights(self, kwargs: Any) -> None:

        message: str = ""
        lights_to_dim: List[Coroutine[Any, Any, Any]] = []

        if not any([await self.get_state(light) == "on" for light in self.lights]):
            return

        if self.dim["method"] == "step":
            message = (
                f"{hl(self.room.capitalize())} → dim to {hl(self.dim['brightness_step_pct'])} | "
                f"{hl('off')} in {natural_time(int(self.dim['seconds_before']))}"
            )
            lights_to_dim = [
                self.call_service("light/turn_on", entity_id=light, brightness_step_pct=self.dim["brightness_step_pct"])
                for light in self.lights
            ]

        elif self.dim["method"] == "transition":
            message = (
                f"{hl(self.room.capitalize())} → transition to {hl('off')} ({natural_time(self.dim['seconds_before'])})"
            )
            lights_to_dim = [
                self.call_service("light/turn_off", entity_id=light, transition=self.dim["seconds_before"])
                for light in self.lights
            ]

        else:
            return

        await asyncio.gather(*lights_to_dim)

        self.lg(message, icon=OFF_ICON)

    async def lights_on(self) -> None:
        """Turn on the lights."""
        if illuminance_threshold := self.thresholds.get("illuminance"):

            # the "eco mode" check
            for sensor in self.sensors["illuminance"]:
                try:
                    if (illuminance := float(await self.get_state(sensor))) >= illuminance_threshold:
                        self.lg(
                            f"According to {hl(sensor)} its already bright enough ¯\\_(ツ)_/¯"
                            f" | {illuminance} >= {illuminance_threshold}"
                        )
                        return

                except ValueError as error:
                    self.lg(f"could not parse illuminance '{await self.get_state(sensor)}' from '{sensor}': {error}")
                    return

        if (light_setting := self.active.get("light_setting")) and isinstance(light_setting, str):

            # last check until we switch the lights on... really!
            if any([await self.get_state(light) == "on" for light in self.lights]):
                self.lg("¯\\_(ツ)_/¯")
                return

            for entity in self.lights:

                if self.active["is_hue_group"] and await self.get_state(entity_id=entity, attribute="is_hue_group"):
                    await self.call_service(
                        "hue/hue_activate_scene", group_name=await self.friendly_name(entity), scene_name=light_setting
                    )
                    continue

                item = light_setting if light_setting.startswith("scene.") else entity

                await self.call_service("homeassistant/turn_on", entity_id=item)

            self.lg(
                f"{hl(self.room.capitalize())} turned {hl(f'on')} → "
                f"{'hue' if self.active['is_hue_group'] else 'ha'} scene: "
                f"{hl(light_setting.replace('scene.', ''))}"
                f" | delay: {hl(natural_time(int(self.active['delay'])))}",
                icon=ON_ICON,
            )

        elif isinstance(self.active["light_setting"], int):

            if self.active["light_setting"] == 0:
                await self.lights_off({})

            else:
                # last check until we switch the lights on... really!
                if any([await self.get_state(light) == "on" for light in self.lights]):
                    self.lg("¯\\_(ツ)_/¯")
                    return

                for entity in self.lights:
                    if entity.startswith("switch."):
                        await self.call_service("homeassistant/turn_on", entity_id=entity)
                    else:
                        await self.call_service(
                            "homeassistant/turn_on", entity_id=entity, brightness_pct=self.active["light_setting"]
                        )

                        self.lg(
                            f"{hl(self.room.capitalize())} turned {hl(f'on')} → "
                            f"brightness: {hl(self.active['light_setting'])}%"
                            f" | delay: {hl(natural_time(int(self.active['delay'])))}",
                            icon=ON_ICON,
                        )

        else:
            raise ValueError(f"invalid brightness/scene: {self.active['light_setting']!s} " f"in {self.room}")

    async def lights_off(self, kwargs: Dict[str, Any]) -> None:
        """Turn off the lights."""

        # check if automoli is disabled via home assistant entity
        if await self.is_disabled():
            return

        # the "shower case" check
        if humidity_threshold := self.thresholds.get("humidity"):
            for sensor in self.sensors["humidity"]:
                try:
                    current_humidity = float(await self.get_state(sensor))
                except ValueError as error:
                    self.lg(f"self.get_state(sensor) raised a ValueError: {error}", level="ERROR")
                    continue

                if current_humidity >= humidity_threshold:
                    # blocker.append(sensor)
                    await self.refresh_timer()
                    self.lg(
                        f"🛁 no motion in {hl(self.room.capitalize())} since "
                        f"{hl(natural_time(int(self.active['delay'])))} → "
                        f"but {hl(current_humidity)}%RH > "
                        f"{hl(humidity_threshold)}%RH"
                    )
                    return

        # cancel scheduled callbacks
        await self.clear_handles(deepcopy(self.handles))

        if any([await self.get_state(entity) == "on" for entity in self.lights]):
            for entity in self.lights:
                await self.call_service("homeassistant/turn_off", entity_id=entity)
            self.lg(
                f"no motion in {hl(self.room.capitalize())} since "
                f"{hl(natural_time(int(self.active['delay'])))} → turned {hl(f'off')}",
                icon=OFF_ICON,
            )

            # experimental | reset for xiaomi "super motion" sensors | idea from @wernerhp
            # app: https://github.com/wernerhp/appdaemon_aqara_motion_sensors
            # mod: https://community.smartthings.com/t/making-xiaomi-motion-sensor-a-super-motion-sensor/139806
            for sensor in self.sensors["motion"]:
                await self.set_state(
                    sensor,
                    state="off",
                    attributes=(await self.get_state(sensor, attribute="all")).get("attributes", {}),
                )

    async def find_sensors(self, keyword: str, room_name: str, states: Dict[str, Dict[str, Any]]) -> List[str]:
        """Find sensors by looking for a keyword in the friendly_name."""

        def lower_umlauts(text: str, single: bool = True) -> str:
            return (
                text.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "s")
                if single
                else text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            ).lower()

        matches: List[str] = []
        for state in states.values():
            if keyword in (entity_id := state.get("entity_id", "")) and lower_umlauts(room_name) in "|".join(
                [entity_id, lower_umlauts(state.get("attributes", {}).get("friendly_name", ""))]
            ):
                matches.append(entity_id)

        return matches

    async def build_daytimes(self, daytimes: List[Any]) -> Optional[List[Dict[str, Union[int, str]]]]:
        starttimes: Set[time] = set()

        for idx, daytime in enumerate(daytimes):
            dt_name = daytime.get("name", f"{DEFAULT_NAME}_{idx}")
            dt_delay = daytime.get("delay", self.delay)
            dt_light_setting = daytime.get("light", DEFAULT_LIGHT_SETTING)
            if self.disable_hue_groups:
                dt_is_hue_group = False
            else:
                dt_is_hue_group = (
                    isinstance(dt_light_setting, str)
                    and not dt_light_setting.startswith("scene.")
                    and any(
                        await asyncio.gather(
                            *[self.get_state(entity_id=entity, attribute="is_hue_group") for entity in self.lights]
                        )
                    )
                )

            dt_start: time
            try:
                dt_start = await self.parse_time(daytime.get("starttime") + ":00", aware=True)
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
                raise ValueError(f"Start times of all daytimes have to be unique! " f"Duplicate found: {dt_start}")

            starttimes.add(dt_start)

            # check if this daytime should ne active now
            if await self.now_is_between(str(dt_start), str(next_dt_start)):
                await self.switch_daytime(dict(daytime=daytime, initial=True))
                self.active_daytime = daytime.get("daytime")

            # schedule callbacks for daytime switching
            await self.run_daily(
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
            room = f" · {hl(self.config['room'].capitalize())}"

        self.lg("")
        self.lg(f"{hl(APP_NAME)} v{hl(__version__)}{room}", icon=self.icon)
        self.lg("")

        listeners = self.config.pop("listeners", None)

        for key, value in self.config.items():

            # hide "internal keys" when displaying config
            if key in ["module", "class"] or key.startswith("_"):
                continue

            if isinstance(value, list) or isinstance(value, set):
                self.print_collection(key, value, 2)
            elif isinstance(value, dict):
                self.print_collection(key, value, 2)
            else:
                self._print_cfg_setting(key, value, 2)

        if listeners:
            self.lg("  event listeners:")
            for listener in sorted(listeners):
                self.lg(f"    · {hl(listener)}")

        self.lg("")

    def print_collection(self, key: str, collection: Iterable[Any], indentation: int = 0) -> None:

        self.lg(f"{indentation * ' '}{key}:")
        indentation = indentation + 2

        for item in collection:
            indent = indentation * " "

            if isinstance(item, dict):

                if "name" in item:
                    self.print_collection(item.pop("name", ""), item, indentation)
                else:
                    self.lg(f"{indent}{hl(pformat(item, compact=True))}")

            elif isinstance(collection, dict):

                if isinstance(collection[item], set):
                    self.print_collection(item, collection[item], indentation)
                else:
                    self._print_cfg_setting(item, collection[item], indentation)

            else:
                self.lg(f"{indent}· {hl(item)}")

    def _print_cfg_setting(self, key: str, value: Union[int, str], indentation: int) -> None:
        unit = prefix = ""
        indent = indentation * " "

        # legacy way
        if key == "delay" and isinstance(value, int):
            unit = "min"
            min_value = f"{int(value / 60)}:{int(value % 60):02d}"
            self.lg(f"{indent}{key}: {prefix}{hl(min_value)}{unit} ≈ " f"{hl(value)}sec", ascii_encode=False)

        else:
            if "_units" in self.config and key in self.config["_units"]:
                unit = self.config["_units"][key]
            if "_prefixes" in self.config and key in self.config["_prefixes"]:
                prefix = self.config["_prefixes"][key]

            self.lg(f"{indent}{key}: {prefix}{hl(value)}{unit}")
