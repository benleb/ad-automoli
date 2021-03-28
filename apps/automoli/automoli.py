"""AutoMoLi.
   Automatic Motion Lights

  @benleb / https://github.com/benleb/ad-automoli
"""

import asyncio
import logging

from copy import deepcopy
from datetime import time
from enum import Enum, IntEnum
from inspect import stack
from pprint import pformat
from sys import version_info
from typing import Any, Coroutine, Dict, Iterable, List, Optional, Set, Union

import hassapi as hass


__version__ = "0.10.1"

APP_NAME = "AutoMoLi"
APP_ICON = "💡"

ON_ICON = APP_ICON
OFF_ICON = "🌑"
DIM_ICON = "🔜"
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
DEFAULT_LOGLEVEL = "INFO"

EVENT_MOTION_XIAOMI = "xiaomi_aqara.motion"

RANDOMIZE_SEC = 5
SECONDS_PER_MIN: int = 60


class EntityType(Enum):
    LIGHT = "light."
    MOTION = "binary_sensor.motion_sensor_"
    HUMIDITY = "sensor.humidity_"
    ILLUMINANCE = "sensor.illumination_"
    DOOR_WINDOW = "binary_sensor.door_window_sensor_"

    @property
    def idx(self) -> str:
        return self.name.casefold()

    @property
    def prefix(self) -> str:
        return str(self.value).casefold()


SENSORS_REQUIRED = [EntityType.MOTION.idx]
SENSORS_OPTIONAL = [EntityType.HUMIDITY.idx, EntityType.ILLUMINANCE.idx]

KEYWORDS = {
    EntityType.LIGHT.idx: "light.",
    EntityType.MOTION.idx: "binary_sensor.motion_sensor_",
    EntityType.HUMIDITY.idx: "sensor.humidity_",
    EntityType.ILLUMINANCE.idx: "sensor.illumination_",
    EntityType.DOOR_WINDOW.idx: "binary_sensor.door_window_sensor_",
}


# version checks
py3_or_higher = version_info.major >= 3
py37_or_higher = py3_or_higher and version_info.minor >= 7
py38_or_higher = py3_or_higher and version_info.minor >= 8


def install_pip_package(
    pkg: str, version: str = "", install_name: Optional[str] = None, pre_release: bool = False
) -> None:
    import importlib
    import site
    import sys

    from subprocess import check_call  # nosec

    try:
        importlib.import_module(pkg)
    except ImportError:
        install_name = install_name if install_name else pkg
        if pre_release:
            check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "--pre",
                    f"{install_name}{version}",
                ]
            )
        else:
            check_call(
                [sys.executable, "-m", "pip", "install", "--upgrade", f"{install_name}{version}"]
            )
        importlib.reload(site)
    finally:
        importlib.import_module(pkg)


# install adutils library
install_pip_package("adutils", version="==0.5.0")
from adutils import hl, hl_entity, natural_time  # noqa


class DimMethod(IntEnum):
    """IntEnum representing the transition-to-off method used."""

    NONE = 0
    TRANSITION = 1
    STEP = 2


class AutoMoLi(hass.Hass):  # type: ignore
    """Automatic Motion Lights."""

    def lg(
        self,
        msg: str,
        *args: Any,
        level: Optional[int] = None,
        icon: Optional[str] = None,
        repeat: int = 1,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("ascii_encode", False)

        level = level if level else self.loglevel

        if level >= self.loglevel:
            message = f"{f'{icon} ' if icon else ' '}{msg}"
            _ = [self.log(message, *args, **kwargs) for _ in range(repeat)]
            return

    def listr(
        self, list_or_string: Union[List[str], Set[str], str, Any], entities_exist: bool = True
    ) -> Set[str]:
        entity_list: List[str] = []

        if isinstance(list_or_string, str):
            entity_list.append(list_or_string)
        elif isinstance(list_or_string, list) or isinstance(list_or_string, set):
            entity_list += list_or_string
        elif list_or_string:
            self.lg(
                f"{list_or_string} is of type {type(list_or_string)} and "
                f"not 'Union[List[str], Set[str], str]'"
            )

        return set(filter(self.entity_exists, entity_list) if entities_exist else entity_list)

    async def initialize(self) -> None:
        """Initialize a room with AutoMoLi."""
        self.icon = APP_ICON

        # get a real dict for the configuration
        self.args: Dict[str, Any] = dict(self.args)

        self.loglevel = logging.DEBUG if self.args.get("debug_log", False) else logging.INFO

        self.lg(f"setting log level to {logging.getLevelName(self.loglevel)}", level=logging.DEBUG)

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

        # directly switch to new daytime light settings
        self.transition_on_daytime_switch: bool = bool(
            self.args.pop("transition_on_daytime_switch", False)
        )

        # state values
        self.states = {
            "motion_on": self.args.pop("motion_state_on", None),
            "motion_off": self.args.pop("motion_state_off", None),
        }

        # threshold values
        self.thresholds = {
            "humidity": self.args.pop("humidity_threshold", None),
            EntityType.ILLUMINANCE.idx: self.args.pop("illuminance_threshold", None),
        }

        # experimental dimming features
        self.dimming: bool = False
        self.dim: Optional[Dict[str, Union[float, int]]] = {}
        if (dim := self.args.pop("dim", {})) and (
            seconds_before := dim.pop("seconds_before", None)
        ):

            brightness_step_pct = dim.pop("brightness_step_pct", None)

            dim_method: Optional[DimMethod] = None
            if method := dim.pop("method", None):
                dim_method = (
                    DimMethod.TRANSITION if method.lower() == "transition" else DimMethod.STEP
                )
            elif brightness_step_pct:
                dim_method = DimMethod.TRANSITION
            else:
                dim_method = DimMethod.NONE

            self.dim = {
                "brightness_step_pct": brightness_step_pct,
                "seconds_before": int(seconds_before),
                "method": dim_method.value,
            }

        # night mode settings
        self.night_mode: Dict[str, Union[int, str]] = {}
        if night_mode := self.args.pop("night_mode", {}):
            self.night_mode = await self.configure_night_mode(night_mode)

        # on/off switch via input.boolean
        self.disable_switch_entities: Set[str] = self.listr(
            self.args.pop("disable_switch_entities", set())
        )
        self.disable_switch_states: Set[str] = self.listr(
            self.args.pop("disable_switch_states", set(["off"]))
        )

        # store if an entity has been switched on by automoli
        self.only_own_events: bool = bool(self.args.pop("only_own_events", False))
        self._switched_on_by_automoli: Set[str] = set()

        self.disable_hue_groups: bool = self.args.pop("disable_hue_groups", False)

        # eol of the old option name
        if "disable_switch_entity" in self.args:
            icon_alert = "⚠️"
            self.lg("", icon=icon_alert)
            self.lg(
                f" please migrate {hl('disable_switch_entity')} to {hl('disable_switch_entities')}",
                icon=icon_alert,
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
                self.lights.update(
                    await self.find_sensors(EntityType.LIGHT.prefix, self.room, states)
                )

        # sensors
        self.sensors: Dict[str, Any] = {}

        # enumerate sensors for motion detection
        self.sensors[EntityType.MOTION.idx] = self.listr(
            self.args.pop(
                "motion", await self.find_sensors(EntityType.MOTION.prefix, self.room, states)
            )
        )

        # requirements check
        if not self.lights or not self.sensors[EntityType.MOTION.idx]:
            self.lg("")
            self.lg(
                f"{hl('No lights/sensors')} given and none found with name: "
                f"'{hl(EntityType.LIGHT.prefix)}*{hl(self.room)}*' or "
                f"'{hl(EntityType.MOTION.prefix)}*{hl(self.room)}*'",
                icon="⚠️ ",
            )
            self.lg("")
            self.lg("  docs: https://github.com/benleb/ad-automoli")
            self.lg("")
            return

        # enumerate optional sensors & disable optional features if sensors are not available
        for sensor_type in SENSORS_OPTIONAL:

            self.lg(f"{sensor_type = } | {self.thresholds = }", level=logging.DEBUG)

            if sensor_type in self.thresholds and self.thresholds[sensor_type]:
                self.sensors[sensor_type] = self.listr(
                    self.args.pop(sensor_type, None)
                ) or await self.find_sensors(KEYWORDS[sensor_type], self.room, states)

                self.lg(f"{self.sensors[sensor_type] = }", level=logging.DEBUG)

            else:
                self.lg(
                    f"No {sensor_type} sensors → disabling features based on {sensor_type}"
                    f" - {self.thresholds[sensor_type]}.",
                    level=logging.DEBUG,
                )
                del self.thresholds[sensor_type]

        # use user-defined daytimes if available
        daytimes = await self.build_daytimes(self.args.pop("daytimes", DEFAULT_DAYTIMES))

        # set up event listener for each sensor
        listener: Set[Coroutine[Any, Any, Any]] = set()
        for sensor in self.sensors[EntityType.MOTION.idx]:

            # listen to xiaomi sensors by default
            if not any([self.states["motion_on"], self.states["motion_off"]]):
                self.lg("no motion states configured - using event listener", level=logging.DEBUG)
                listener.add(
                    self.listen_event(
                        self.motion_event, event=EVENT_MOTION_XIAOMI, entity_id=sensor
                    )
                )

            # on/off-only sensors without events on every motion
            elif all([self.states["motion_on"], self.states["motion_off"]]):
                self.lg("both motion states configured - using state listener", level=logging.DEBUG)
                listener.add(
                    self.listen_state(
                        self.motion_detected, entity=sensor, new=self.states["motion_on"]
                    )
                )
                listener.add(
                    self.listen_state(
                        self.motion_cleared, entity=sensor, new=self.states["motion_off"]
                    )
                )

        # callback handles to switch lights off
        self.handles: Set[str] = set()

        self.args.update(
            {
                "room": self.room.capitalize(),
                "delay": self.delay,
                "active_daytime": self.active_daytime,
                "daytimes": daytimes,
                "lights": self.lights,
                "dim": self.dim,
                "threshold": self.thresholds,
                "sensors": self.sensors,
                "disable_hue_groups": self.disable_hue_groups,
                "only_own_events": self.only_own_events,
                "loglevel": self.loglevel,
            }
        )

        # add night mode to config if enabled
        if self.night_mode:
            self.args.update({"night_mode": self.night_mode})

        # add disable entity to config if given
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
                    f"{stack()[0][3]}() {self.transition_on_daytime_switch = }", level=logging.DEBUG
                )

                action_done = "set"

                if self.transition_on_daytime_switch and any(
                    [await self.get_state(light) == "on" for light in self.lights]
                ):
                    await self.lights_on(force=True)
                    action_done = "activated"

                self.lg(
                    f"{action_done} daytime {hl(daytime['daytime'])} → "
                    f"{'scene' if is_scene else 'brightness'}: {hl(light_setting)}"
                    f"{'' if is_scene else '%'}, delay: {hl(natural_time(delay))}",
                    icon=DAYTIME_SWITCH_ICON,
                )

    async def motion_cleared(
        self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]
    ) -> None:
        """wrapper for motion sensors that do not push a certain event but.
        instead the default HA `state_changed` event is used for presence detection

        schedules the callback to switch the lights off after a `state_changed` callback
        of a motion sensors changing to "cleared" is received
        """

        # starte the timer if motion is cleared
        self.lg(
            f"{stack()[0][3]}() {entity} changed {attribute} from {old} to {new}",
            level=logging.DEBUG,
        )

        if all(
            [
                await self.get_state(sensor) == self.states["motion_off"]
                for sensor in self.sensors[EntityType.MOTION.idx]
            ]
        ):
            # all motion sensors off, starting timer
            await self.refresh_timer()
        else:
            # cancel scheduled callbacks
            await self.clear_handles(deepcopy(self.handles))

    async def motion_detected(
        self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]
    ) -> None:
        """wrapper for motion sensors that do not push a certain event but.
        instead the default HA `state_changed` event is used for presence detection

        maps the `state_changed` callback of a motion sensors changing to "detected"
        to the `event` callback`
        """

        self.lg(
            f"{stack()[0][3]}() {entity} changed {attribute} from {old} to {new}",
            level=logging.DEBUG,
        )

        # cancel scheduled callbacks
        await self.clear_handles(deepcopy(self.handles))

        self.lg(
            f"{stack()[0][3]}() handles cleared and cancelled all scheduled timers"
            f" | {self.dimming = }",
            level=logging.DEBUG,
        )

        # calling motion event handler
        data: Dict[str, Any] = {"entity_id": entity, "new": new, "old": old}
        await self.motion_event("state_changed_detection", data, kwargs)

    async def motion_event(self, event: str, data: Dict[str, str], kwargs: Dict[str, Any]) -> None:
        """Main handler for motion events."""

        self.lg(
            f"{stack()[0][3]}() received '{hl(event)}' event from "
            f"'{data['entity_id'].replace(EntityType.MOTION.prefix, '')}' | {self.dimming = }",
            level=logging.DEBUG,
        )

        # check if automoli is disabled via home assistant entity
        self.lg(
            f"{stack()[0][3]}() {await self.is_disabled() = } | {self.dimming = }",
            level=logging.DEBUG,
        )
        if await self.is_disabled():
            return

        # turn on the lights if not already
        if self.dimming or not any([await self.get_state(light) == "on" for light in self.lights]):
            self.lg(f"{stack()[0][3]}() switching on | {self.dimming = }", level=logging.DEBUG)
            await self.lights_on()
        else:
            self.lg(
                f"{stack()[0][3]}() light in {self.room.capitalize()} already on → refreshing timer"
                f" | {self.dimming = }",
                level=logging.DEBUG,
            )

        if event != "state_changed_detection":
            await self.refresh_timer()

    async def clear_handles(self, handles: Set[str]) -> None:
        """clear scheduled timers/callbacks."""
        self.handles.clear()
        self.lg(
            f"{stack()[0][3]}() {self.handles = } cleared, canceling {handles = }",
            level=logging.DEBUG,
        )

        await asyncio.gather(
            *[self.cancel_timer(handle) for handle in handles if await self.timer_running(handle)]
        )

    async def refresh_timer(self) -> None:
        """refresh delay timer."""

        self.dimming = False

        # cancel scheduled callbacks
        await self.clear_handles(deepcopy(self.handles))
        self.lg(f"{stack()[0][3]}() handles cleared → {self.handles = }", level=logging.DEBUG)

        # if no delay is set or delay = 0, lights will not switched off by AutoMoLi
        if delay := self.active.get("delay"):

            self.lg(f"{stack()[0][3]}() {self.active = }", level=logging.DEBUG)

            if self.dim:
                dim_in_sec = int(delay) - self.dim["seconds_before"] + 2
                self.lg(
                    f"{stack()[0][3]}() {self.dim = }, dimming in {dim_in_sec}", level=logging.DEBUG
                )

                dim_handle = await self.run_in(self.dim_lights, (dim_in_sec))
                self.handles.add(dim_handle)
                self.lg(f"{stack()[0][3]}() {dim_handle = } -> {self.handles}", level=logging.DEBUG)

            # schedule "turn off" callback
            off_handle = await self.run_in(self.lights_off, delay)
            self.handles.add(off_handle)
            self.lg(f"{stack()[0][3]}() {off_handle = } -> {self.handles}", level=logging.DEBUG)

    async def is_disabled(self) -> bool:
        """check if automoli is disabled via home assistant entity"""
        for entity in self.disable_switch_entities:
            if (
                state := await self.get_state(entity, copy=False)
            ) and state in self.disable_switch_states:
                self.lg(f"{APP_NAME} is disabled by {entity} with {state = }")
                return True

        return False

    async def is_blocked(self) -> bool:

        # the "shower case"
        self.lg(f"{self.thresholds.get(EntityType.HUMIDITY.idx) = }", level=logging.DEBUG)

        if humidity_threshold := self.thresholds.get("humidity"):

            self.lg(f"{self.sensors[EntityType.HUMIDITY.idx] = }", level=logging.DEBUG)

            for sensor in self.sensors[EntityType.HUMIDITY.idx]:
                try:
                    current_humidity = float(await self.get_state(sensor))
                except ValueError as error:
                    self.lg(
                        f"self.get_state(sensor) raised a ValueError: {error}", level=logging.ERROR
                    )
                    continue

                self.lg(
                    f"{current_humidity = } >= {humidity_threshold = } "
                    f"= {current_humidity >= humidity_threshold}",
                    level=logging.DEBUG,
                )

                if current_humidity >= humidity_threshold:
                    # blocker.append(sensor)
                    await self.refresh_timer()
                    self.lg(
                        f"🛁 no motion in {hl(self.room.capitalize())} since "
                        f"{hl(natural_time(int(self.active['delay'])))} → "
                        f"but {hl(current_humidity)}%RH > "
                        f"{hl(humidity_threshold)}%RH"
                    )
                    return True

        return False

    async def dim_lights(self, kwargs: Any) -> None:

        message: str = ""

        self.lg(
            f"{stack()[0][3]}() {await self.is_disabled() = } | {await self.is_blocked() = }",
            level=logging.DEBUG,
        )

        # check if automoli is disabled via home assistant entity or blockers like the "shower case"
        if (await self.is_disabled()) or (await self.is_blocked()):
            return

        if not any([await self.get_state(light) == "on" for light in self.lights]):
            return

        if (
            self.dim
            and (dim_method := DimMethod(self.dim["method"]))
            and dim_method != DimMethod.NONE
        ):

            seconds_before = int(self.dim["seconds_before"])
            dim_attributes: Dict[str, int] = {}

            self.lg(f"{stack()[0][3]}() {dim_method = } - {seconds_before = }", level=logging.DEBUG)

            if dim_method == DimMethod.STEP:
                dim_attributes = {"brightness_step_pct": int(self.dim["brightness_step_pct"])}
                message = (
                    f"{hl(self.room.capitalize())} → dim to {hl(self.dim['brightness_step_pct'])} |"
                    f" {hl('off')} in {natural_time(seconds_before)}"
                )

            elif dim_method == DimMethod.TRANSITION:
                dim_attributes = {"transition": int(seconds_before)}
                message = (
                    f"{hl(self.room.capitalize())} → transition to "
                    f"{hl('off')} ({natural_time(seconds_before)})"
                )

            self.dimming = True

            self.lg(
                f"{stack()[0][3]}() {dim_attributes = } | {self.dimming = }", level=logging.DEBUG
            )

            self.lg(
                f"dimming {hl(self.room.capitalize())} | method: {dim_method.name.capitalize()}",
                icon=DIM_ICON,
            )

            for light in self.lights:
                await self.call_service("light/turn_off", entity_id=light, **dim_attributes)
                await self.set_state(entity=light, state="off")

        else:
            return

        self.lg(message, icon=OFF_ICON, level=logging.DEBUG)

    async def lights_on(self, force: bool = False) -> None:
        """Turn on the lights."""

        self.lg(
            f"{stack()[0][3]}() {self.thresholds.get(EntityType.ILLUMINANCE.idx) = }"
            f" | {self.dimming = } | {force = } | {bool(force or self.dimming) = }",
            level=logging.DEBUG,
        )

        force = bool(force or self.dimming)

        if illuminance_threshold := self.thresholds.get(EntityType.ILLUMINANCE.idx):

            # the "eco mode" check
            for sensor in self.sensors[EntityType.ILLUMINANCE.idx]:
                self.lg(
                    f"{stack()[0][3]}() {self.thresholds.get(EntityType.ILLUMINANCE.idx) = } | "
                    f"{float(await self.get_state(sensor)) = }",
                    level=logging.DEBUG,
                )
                try:
                    if (
                        illuminance := float(await self.get_state(sensor))
                    ) >= illuminance_threshold:
                        self.lg(
                            f"According to {hl(sensor)} its already bright enough ¯\\_(ツ)_/¯"
                            f" | {illuminance} >= {illuminance_threshold}"
                        )
                        return

                except ValueError as error:
                    self.lg(
                        f"could not parse illuminance '{await self.get_state(sensor)}' "
                        f"from '{sensor}': {error}"
                    )
                    return

        light_setting = (
            self.active.get("light_setting")
            if not (self.night_mode and await self.get_state(self.night_mode["entity"]) == "off")
            else self.night_mode.get("light")
        )

        if isinstance(light_setting, str):

            # last check until we switch the lights on... really!
            if not force and any([await self.get_state(light) == "on" for light in self.lights]):
                self.lg("¯\\_(ツ)_/¯")
                return

            for entity in self.lights:

                if self.active["is_hue_group"] and await self.get_state(
                    entity_id=entity, attribute="is_hue_group"
                ):
                    await self.call_service(
                        "hue/hue_activate_scene",
                        group_name=await self.friendly_name(entity),
                        scene_name=light_setting,
                    )
                    if self.only_own_events:
                        self._switched_on_by_automoli.add(entity)
                    continue

                item = light_setting if light_setting.startswith("scene.") else entity

                await self.call_service("homeassistant/turn_on", entity_id=item)
                if self.only_own_events:
                    self._switched_on_by_automoli.add(item)

            self.lg(
                f"{hl(self.room.capitalize())} turned {hl(f'on')} → "
                f"{'hue' if self.active['is_hue_group'] else 'ha'} scene: "
                f"{hl(light_setting.replace('scene.', ''))}"
                f" | delay: {hl(natural_time(int(self.active['delay'])))}",
                icon=ON_ICON,
            )

        elif isinstance(light_setting, int):

            if light_setting == 0:
                await self.lights_off({})

            else:
                # last check until we switch the lights on... really!
                if not force and any(
                    [await self.get_state(light) == "on" for light in self.lights]
                ):
                    self.lg("¯\\_(ツ)_/¯")
                    return

                for entity in self.lights:
                    if entity.startswith("switch."):
                        await self.call_service("homeassistant/turn_on", entity_id=entity)
                    else:
                        await self.call_service(
                            "homeassistant/turn_on",
                            entity_id=entity,
                            brightness_pct=light_setting,
                        )

                        self.lg(
                            f"{hl(self.room.capitalize())} turned {hl(f'on')} → "
                            f"brightness: {hl(light_setting)}%"
                            f" | delay: {hl(natural_time(int(self.active['delay'])))}",
                            icon=ON_ICON,
                        )
                    if self.only_own_events:
                        self._switched_on_by_automoli.add(entity)

        else:
            raise ValueError(f"invalid brightness/scene: {light_setting!s} " f"in {self.room}")

    async def lights_off(self, kwargs: Dict[str, Any]) -> None:
        """Turn off the lights."""

        self.lg(
            f"{stack()[0][3]}() {await self.is_disabled()} | {await self.is_blocked() = }",
            level=logging.DEBUG,
        )

        # check if automoli is disabled via home assistant entity or blockers like the "shower case"
        if (await self.is_disabled()) or (await self.is_blocked()):
            return

        # cancel scheduled callbacks
        await self.clear_handles(deepcopy(self.handles))

        self.lg(
            f"{stack()[0][3]}() "
            f"{any([await self.get_state(entity) == 'on' for entity in self.lights]) = }"
            f" | {self.lights = }",
            level=logging.DEBUG,
        )

        if any([await self.get_state(entity) == "on" for entity in self.lights]):
            at_least_one_turned_off = False
            for entity in self.lights:
                if self.only_own_events:
                    if entity in self._switched_on_by_automoli:
                        await self.call_service("homeassistant/turn_off", entity_id=entity)
                        self._switched_on_by_automoli.remove(entity)
                        at_least_one_turned_off = True
                else:
                    await self.call_service("homeassistant/turn_off", entity_id=entity)
                    at_least_one_turned_off = True
            if at_least_one_turned_off:
                self.lg(
                    f"no motion in {hl(self.room.capitalize())} since "
                    f"{hl(natural_time(int(self.active['delay'])))} → turned {hl(f'off')}",
                    icon=OFF_ICON,
                )

            # experimental | reset for xiaomi "super motion" sensors | idea from @wernerhp
            # app: https://github.com/wernerhp/appdaemon_aqara_motion_sensors
            # mod:
            # https://community.smartthings.com/t/making-xiaomi-motion-sensor-a-super-motion-sensor/139806
            for sensor in self.sensors[EntityType.MOTION.idx]:
                await self.set_state(
                    sensor,
                    state="off",
                    attributes=(await self.get_state(sensor, attribute="all")).get(
                        "attributes", {}
                    ),
                )

    async def find_sensors(
        self, keyword: str, room_name: str, states: Dict[str, Dict[str, Any]]
    ) -> List[str]:
        """Find sensors by looking for a keyword in the friendly_name."""

        def lower_umlauts(text: str, single: bool = True) -> str:
            return (
                text.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "s")
                if single
                else text.replace("ä", "ae")
                .replace("ö", "oe")
                .replace("ü", "ue")
                .replace("ß", "ss")
            ).lower()

        matches: List[str] = []
        for state in states.values():
            if keyword in (entity_id := state.get("entity_id", "")) and lower_umlauts(
                room_name
            ) in "|".join(
                [entity_id, lower_umlauts(state.get("attributes", {}).get("friendly_name", ""))]
            ):
                matches.append(entity_id)

        return matches

    async def configure_night_mode(
        self, night_mode: Dict[str, Union[int, str]]
    ) -> Dict[str, Union[int, str]]:

        # check if a enable/disable entity is given and exists
        if not ((nm_entity := night_mode.pop("entity")) and await self.entity_exists(nm_entity)):
            self.lg("no night_mode entity given", level=logging.DEBUG)
            return {}

        if not (nm_light_setting := night_mode.pop("light")):
            return {}

        return {"entity": nm_entity, "light": nm_light_setting}

    async def build_daytimes(
        self, daytimes: List[Any]
    ) -> Optional[List[Dict[str, Union[int, str]]]]:
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
                            *[
                                self.get_state(entity_id=entity, attribute="is_hue_group")
                                for entity in self.lights
                            ]
                        )
                    )
                )

            dt_start: time
            try:
                starttime = daytime.get("starttime")
                if starttime.count(":") == 1:
                    starttime += ":00"
                dt_start = (await self.parse_time(starttime, aware=True)).replace(microsecond=0)
                daytime["starttime"] = dt_start
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
            next_dt_name = DEFAULT_NAME
            try:
                next_starttime = str(daytimes[(idx + 1) % len(daytimes)].get("starttime"))
                if next_starttime.count(":") == 1:
                    next_starttime += ":00"
                next_dt_name = str(daytimes[(idx + 1) % len(daytimes)].get("name"))
                next_dt_start = (await self.parse_time(next_starttime, aware=True)).replace(
                    microsecond=0
                )
            except ValueError as error:
                raise ValueError(f"missing start time in daytime '{next_dt_name}': {error}")

            # collect all start times for sanity check
            if dt_start in starttimes:
                raise ValueError(
                    f"Start times of all daytimes have to be unique! "
                    f"Duplicate found: {dt_start}"
                )

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
            self.lg("no configuration available", icon="‼️", level=logging.ERROR)
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
            self.lg(
                f"{indent}{key}: {prefix}{hl(min_value)}{unit} ≈ " f"{hl(value)}sec",
                ascii_encode=False,
            )

        else:
            if "_units" in self.config and key in self.config["_units"]:
                unit = self.config["_units"][key]
            if "_prefixes" in self.config and key in self.config["_prefixes"]:
                prefix = self.config["_prefixes"][key]

            self.lg(f"{indent}{key}: {prefix}{hl(value)}{unit}")
