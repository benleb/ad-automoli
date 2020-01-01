"""AutoMoLi.
   Automatic Motion Lights

  https://github.com/benleb/ad-automoli
"""

import sys
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Set, Union

import adutils
import hassapi as hass

APP_NAME = "AutoMoLi"
APP_ICON = "💡"
APP_VERSION = "0.4.6"

ON_ICON = APP_ICON
OFF_ICON = "🌑"
DAYTIME_SWITCH_ICON = "⏰"

# default values
DEFAULT_NAME = "daytime"
DEFAULT_LIGHT_SETTING = 100
DEFAULT_DELAY = 150
DEFAULT_DAYTIMES = [
    dict(start="05:30", name="morning", light=0),
    dict(start="07:30", name="day", light="Arbeiten"),
    dict(start="20:30", name="evening", light=90),
    dict(start="22:30", name="night", light=0),
]

EVENT_MOTION_XIAOMI = "xiaomi_aqara.motion"

KEYWORD_LIGHTS = "light."
KEYWORD_SENSORS = "binary_sensor.motion_sensor_"
KEYWORD_SENSORS_HUMIDITY = "sensor.humidity_"
KEYWORD_SENSORS_ILLUMINANCE = "sensor.illumination_"


class AutoMoLi(hass.Hass):  # type: ignore
    """Automatic Motion Lights."""

    def initialize(self) -> None:
        """Initialize a room with AutoMoLi."""
        self.room = str(self.args.get("room"))
        self.delay = int(self.args.get("delay", DEFAULT_DELAY))
        self.event_motion = self.args.get("motion_event", None)
        # devices
        self.lights: Set[str] = self.args.get("lights", set())
        self.sensors_motion: Set[str] = self.args.get("motion", set())
        self.sensors_illuminance: Set[str] = self.args.pop("illuminance", set())
        self.sensors_humidity: Set[str] = self.args.pop("humidity", set())
        # device config
        self.illuminance_threshold: Optional[int] = self.args.get("illuminance_threshold")
        self.humidity_threshold: Optional[int] = self.args.get("humidity_threshold")

        # on/off switch via input.boolean
        self.disable_switch_entity = self.args.get("disable_switch_entity")

        daytimes: List[Dict[str, Union[int, str]]] = self.args.get("daytimes", DEFAULT_DAYTIMES)
        starttimes: Set[time] = set()

        self.active: Dict[str, Union[int, str]] = {}
        self._handle = None

        # define light entities switched by automoli
        if self.lights:
            self.lights = set(self.lights)
        elif self.entity_exists(f"light.{self.room}"):
            self.lights.update([f"light.{self.room}"])
        else:
            self.lights.update(self.find_sensors(KEYWORD_LIGHTS))

        # define sensor entities monitored by automoli
        if not self.sensors_motion:
            self.sensors_motion.update(self.find_sensors(KEYWORD_SENSORS))

        # enumerate humidity sensors if threshold given
        if self.humidity_threshold:
            if not self.sensors_humidity:
                self.sensors_humidity.update(
                    self.find_sensors(KEYWORD_SENSORS_HUMIDITY)
                )

            if not self.sensors_humidity:
                self.log(
                    f"No humidity sensors given or found ('{KEYWORD_SENSORS_HUMIDITY}') → disabling humidity threshold blocker."
                )
                self.humidity_threshold = None

        # enumerate illuminance sensors if threshold given
        if self.illuminance_threshold:
            if not self.sensors_illuminance:
                self.sensors_illuminance.update(
                    self.find_sensors(KEYWORD_SENSORS_ILLUMINANCE)
                )

            if not self.sensors_illuminance:
                self.log(
                    f"No illuminance sensors given or found ('{KEYWORD_SENSORS_ILLUMINANCE}') → disabling illuminance threshold."
                )
                self.illuminance_threshold = None

        # sanity check
        if not self.sensors_motion:
            raise ValueError(f"No sensors given/found, sorry! ('{KEYWORD_SENSORS}')")
        elif not self.lights:
            raise ValueError(f"No sensors given/found, sorry! ('{KEYWORD_LIGHTS}')")

        for idx, daytime in enumerate(daytimes):
            dt_name = daytime.get("name", f"{DEFAULT_NAME}_{idx}")
            dt_light_setting = daytime.get("light", DEFAULT_LIGHT_SETTING)
            dt_is_hue_group = isinstance(dt_light_setting, str) and not dt_light_setting.startswith("scene.") and any(
                [
                    self.get_state(entity_id=entity, attribute="is_hue_group")
                    for entity in self.lights
                ]
            )

            py37_or_higher = sys.version_info.major >= 3 and sys.version_info.minor >= 7

            dt_start: time
            try:
                if py37_or_higher:
                    dt_start = time.fromisoformat(str(daytime.get("starttime")))
                else:
                    dt_start = datetime.strptime(
                        str(daytime.get("starttime")), "%H:%M"
                    ).time()
            except ValueError as verror:
                raise ValueError(f"missing start time in daytime '{dt_name}': {verror}")

            # configuration for this daytime
            daytime = dict(
                daytime=dt_name,
                # starttime=dt_start,  # datetime is not serializable
                starttime=dt_start.isoformat(),
                light_setting=dt_light_setting,
                is_hue_group=dt_is_hue_group,
            )

            # info about next daytime
            if py37_or_higher:
                next_dt_start = time.fromisoformat(
                    str(daytimes[(idx + 1) % len(daytimes)].get("starttime"))
                )
            else:
                next_dt_start = datetime.strptime(
                    str(daytimes[(idx + 1) % len(daytimes)].get("starttime")), "%H:%M"
                ).time()

            # collect all start times for sanity check
            if dt_start in starttimes:
                raise ValueError(
                    f"Start times of all daytimes have to be unique! Duplicate found: {dt_start}"
                )

            starttimes.add(dt_start)

            # check if this daytime should ne active now
            if self.now_is_between(str(dt_start), str(next_dt_start)):
                self.switch_daytime(dict(daytime=daytime, initial=True))
                self.args["active_daytime"] = daytime.get("daytime")

            # schedule callbacks for daytime switching
            self.run_daily(self.switch_daytime, dt_start, random_start=-10, **dict(daytime=daytime))

        # set up event listener for each sensor
        for sensor in self.sensors_motion:
            # listen to xiaomi sensors by default
            self.listen_event(self.motion_event, event=EVENT_MOTION_XIAOMI, entity_id=sensor)

            if self.event_motion:
                self.listen_event(self.motion_event, event=self.event_motion, entity_id=sensor)

        # start timer on appdaemon start
        self.refresh_timer()

        # display settings
        self.args.setdefault("listeners", self.sensors_motion)
        self.args.setdefault("sensors_illuminance", list(self.sensors_illuminance)) if self.sensors_illuminance else None
        self.args.setdefault("sensors_humidity", list(self.sensors_humidity)) if self.sensors_humidity else None

        # init adutils
        self.adu = adutils.ADutils(APP_NAME, self.args, icon=APP_ICON, ad=self, show_config=True)

    def switch_daytime(self, kwargs: Dict[str, Any]) -> None:
        """Set new light settings according to daytime."""
        daytime = kwargs.get("daytime")

        if daytime is not None:
            self.active = daytime
            if not kwargs.get("initial"):

                light_setting = daytime['light_setting']
                if isinstance(light_setting, str):
                    is_scene = True
                    # if its a ha scene, remove the "scene." part
                    if "." in light_setting:
                        light_setting = (light_setting.split("."))[1]
                else:
                    is_scene = False

                self.adu.log(
                    f"set \033[1m{self.room.capitalize()}\033[0m to \033[1m{daytime['daytime']}\033[0m → "
                    f"{'scene' if is_scene else 'brightness'}: \033[1m{light_setting}\033[0m"
                    f"{'' if is_scene else '%'}, delay: \033[1m{self.delay}\033[0msec",
                    icon=DAYTIME_SWITCH_ICON
                )

    def motion_event(self, event: str, data: Dict[str, str], kwargs: Dict[str, Any]) -> None:
        """Handle motion events."""
        self.adu.log(
            f"received '{event}' event from '{data['entity_id'].replace(KEYWORD_SENSORS, '')}'",
            level="DEBUG"
        )

        # check if automoli is disabled via home assistant entity
        automoli_state = self.get_state(self.disable_switch_entity)
        if automoli_state == "off":
            self.adu.log(
                f"automoli is disabled via {self.disable_switch_entity} (state: {automoli_state})'"
            )
            return

        # turn on the lights if not already
        if not any([self.get_state(light) == "on" for light in self.lights]):
            self.lights_on()
        else:
            self.adu.log(
                f"light in {self.room.capitalize()} already on → refreshing the timer",
                level="DEBUG"
            )

        self.refresh_timer()

    def refresh_timer(self) -> None:
        """Refresh delay timer."""
        self.cancel_timer(self._handle)
        self._handle = self.run_in(self.lights_off, self.delay)

    def lights_on(self) -> None:
        """Turn on the lights."""
        if self.illuminance_threshold:
            blocker = [
                sensor for sensor in self.sensors_illuminance
                if float(self.get_state(sensor)) >= self.illuminance_threshold
            ]
            if blocker:
                self.adu.log(f"According to  \033[1m{blocker}\033[0m its already bright enough")
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

                self.turn_on(item)

            self.adu.log(
                f"\033[1m{self.room.capitalize()}\033[0m turned \033[1mon\033[0m → {'hue' if self.active['is_hue_group'] else 'ha'} scene: \033[1m{self.active['light_setting'].replace('scene.', '')}\033[0m",
                icon=ON_ICON
            )

        elif isinstance(self.active["light_setting"], int):

            if self.active["light_setting"] == 0:
                self.lights_off(dict())

            else:
                for entity in self.lights:
                    if entity.startswith("switch."):
                        self.turn_on(entity)
                    else:
                        self.turn_on(entity, brightness_pct=self.active["light_setting"])
                        self.adu.log(
                            f"\033[1m{self.room.capitalize()}\033[0m turned \033[1mon\033[0m → brightness: \033[1m{self.active['light_setting']}%\033[0m",
                            icon=ON_ICON
                        )

        else:
            raise ValueError(
                f"invalid brightness/scene: {self.active['light_setting']!s} in {self.room}"
            )

    def lights_off(self, kwargs: Dict[str, Any]) -> None:
        """Turn off the lights."""
        blocker: Any = None

        if self.humidity_threshold:
            blocker = [
                sensor for sensor in self.sensors_humidity
                if float(self.get_state(sensor)) >= self.humidity_threshold
            ]
            blocker = blocker.pop() if blocker else None

        # turn off if not blocked
        if blocker:
            self.refresh_timer()
            self.adu.log(
                f"🛁 no motion in \033[1m{self.room.capitalize()}\033[0m since "
                f"\033[1m{self.delay}s\033[0m → but \033[1m{float(self.get_state(blocker))}%\033[0mRH > "
                f"{self.humidity_threshold}%RH"
            )
        else:
            self.cancel_timer(self._handle)
            if any([self.get_state(entity) == "on" for entity in self.lights]):
                for entity in self.lights:
                    self.turn_off(entity)
                self.adu.log(f"no motion in \033[1m{self.room.capitalize()}\033[0m since \033[1m{self.delay}s\033[0m → turned \033[1moff\033[0m", icon=OFF_ICON)

    def find_sensors(self, keyword: str) -> List[str]:
        """Find sensors by looking for a keyword in the friendly_name."""
        return [
            sensor
            for sensor in self.get_state()
            if keyword in sensor and
            self.room in self.friendly_name(sensor).lower().replace("ü", "u")
        ]
