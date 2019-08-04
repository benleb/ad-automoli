"""automatic motion lights.

  config example
  all things can be omitted except the room and delay

bathroom_lights:
  module: automoli
  class: AutoMoLi
  room: bad
  delay: 300
  daytimes:
    - { starttime: "05:30", name: morning, light: 45 }
    - { starttime: "07:30", name: day, light: "Arbeiten" }
    - { starttime: "20:30", name: evening, light: 90 }
    - { starttime: "22:30", name: night, light: 0 }
  humidity_threshold: 75
  lights:
    - light.bad
  motion:
    - binary_sensor.motion_sensor_158d000224f441
  humidity:
    - sensor.humidity_158d0001b95fb7
"""

import sys
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Set, Union

import appdaemon.plugins.hass.hassapi as hass

import adutils

APP_NAME = "AutoMoLi"
APP_ICON = "💡"

ON_ICON = APP_ICON
OFF_ICON = "🤷‍♀️"

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

EVENT_MOTION = "xiaomi_aqara.motion"

KEYWORD_LIGHTS = "light."
KEYWORD_SENSORS = "binary_sensor.motion_sensor_"
KEYWORD_SENSORS_HUMIDITY = "sensor.humidity_"


class AutoMoLi(hass.Hass):  # type: ignore
    """Automatic Motion Lights."""

    def initialize(self) -> None:
        """Initialize a room with AutoMoLi."""
        self.room = str(self.args.get("room"))
        self.delay = int(self.args.get("delay", DEFAULT_DELAY))
        # devices
        self.lights: Set[str] = self.args.get("lights", set())
        self.sensors_motion: Set[str] = self.args.get("motion", set())
        self.sensors_humidity: Set[str] = self.args.get("humidity", set())
        # device config
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
        if self.humidity_threshold is not None:
            if not self.sensors_humidity:
                self.sensors_humidity.update(
                    self.find_sensors(KEYWORD_SENSORS_HUMIDITY)
                )

            if not self.sensors_humidity:
                self.log(
                    f"No humidity sensors given or found ('{KEYWORD_SENSORS_HUMIDITY}'), disabling humidity threshold blocker."
                )
                self.humidity_threshold = None

        # sanity check
        if not self.sensors_motion:
            raise ValueError(f"No sensors given/found, sorry! ('{KEYWORD_SENSORS}')")
        elif not self.lights:
            raise ValueError(f"No sensors given/found, sorry! ('{KEYWORD_LIGHTS}')")

        for idx, daytime in enumerate(daytimes):
            # self.log(daytime)
            dt_name = daytime.get("name", f"{DEFAULT_NAME}_{idx}")
            dt_light_setting = daytime.get("light", DEFAULT_LIGHT_SETTING)
            dt_is_hue_group = all(
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
            self.listen_event(self.motion_event, event=EVENT_MOTION, entity_id=sensor)

        # start timer on appdaemon start
        self.refresh_timer()

        # display settings
        adutils.show_info(self.log, f"{APP_NAME} {self.room.capitalize()}", self.args, self.sensors_motion, icon=APP_ICON)

    def switch_daytime(self, kwargs: Dict[str, Any]) -> None:
        """Set new light settings according to daytime."""
        daytime = kwargs.get("daytime")

        if daytime is not None:
            self.active = daytime
            if not kwargs.get("initial"):
                self.log(
                    f"Switched {self.room.capitalize()} to '{daytime['daytime']}' | settings: {daytime['light_setting']}, {self.delay}s delay"
                )

    def motion_event(self, event: str, data: Dict[str, str], kwargs: Dict[str, Any]) -> None:
        """Handle motion events."""
        self.log(
            f"received '{event}' event from '{data['entity_id'].replace(KEYWORD_SENSORS, '')}'",
            level="DEBUG"
        )

        # check if automoli is disabled via home assistant entity
        automoli_state = self.get_state(self.disable_switch_entity)
        if automoli_state == "off":
            self.log(
                f"automoli is disabled via {self.disable_switch_entity} (state: {automoli_state})'"
            )
            return

        # turn on the lights if not already
        if not any([self.get_state(light) == "on" for light in self.lights]):
            self.lights_on()
        else:
            self.log(
                f"light in {self.room.capitalize()} already on, just refreshing the timer",
                level="DEBUG"
            )

        self.refresh_timer()

    def refresh_timer(self) -> None:
        """Refresh delay timer."""
        self.cancel_timer(self._handle)
        self._handle = self.run_in(self.lights_off, self.delay)

    def lights_on(self) -> None:
        """Turn on the lights."""
        if isinstance(self.active["light_setting"], str):

            if self.active["is_hue_group"] is True:
                for entity in self.lights:
                    self.call_service(
                        "hue/hue_activate_scene",
                        group_name=self.friendly_name(entity),
                        scene_name=self.active["light_setting"],
                    )
            else:
                for entity in self.lights:
                    if self.split_entity(entity)[0] == "switch":
                        self.turn_on(entity)
                    else:
                        self.turn_on(self.active["light_setting"])

            self.log(
                f"{ON_ICON} \033[1m{self.room.capitalize()}\033[0m turned \033[1mon\033[0m ({'hue' if self.active['is_hue_group'] else 'ha'} scene: \033[1m{self.active['light_setting']}\033[0m)",
                ascii_encode=False
            )

        elif isinstance(self.active["light_setting"], int):

            if self.active["light_setting"] != 0:
                for entity in self.lights:
                    if self.split_entity(entity)[0] == "switch":
                        self.turn_on(entity)
                    else:
                        self.turn_on(entity, brightness_pct=self.active["light_setting"])
                        self.log(
                            f"{ON_ICON} \033[1m{self.room.capitalize()}\033[0m turned \033[1mon\033[0m (brightness: \033[1m{self.active['light_setting']}\033[0m%)",
                            ascii_encode=False
                        )

        else:
            raise ValueError(
                f"invalid brightness/scene: {self.active['light_setting']!s} in {self.room}"
            )

    def lights_off(self, kwargs: Dict[str, Any]) -> None:
        """Turn off the lights."""
        blocker = None

        if self.humidity_threshold is not None:
            blocker = [
                (sensor, float(self.get_state(sensor)))
                for sensor in self.sensors_humidity
                if float(self.get_state(sensor)) >= self.humidity_threshold
            ]

        # turn off if not blocked
        if not blocker:
            for light in self.lights:
                self.turn_off(light)
            self.log(f"no motion since \033[1m{self.delay}s\033[0m {OFF_ICON} lights in \033[1m{self.room.capitalize()}\033[0m turned \033[1moff\033[0m", ascii_encode=False)
        else:
            self.refresh_timer()
            self.log(
                f"no motion since \033[1m{self.delay}s\033[0m but shutdown prevented by \033[1m{blocker}\033[0m, refreshing the timer"
            )

    def find_sensors(self, keyword: str) -> List[str]:
        """Find sensors by looking for a keyword in the friendly_name."""
        return [
            sensor
            for sensor in self.get_state()
            if keyword in sensor and
            self.room in self.friendly_name(sensor).lower().replace("ü", "u")
        ]

    @staticmethod
    def single_item(settings_list: List[str]) -> Optional[str]:
        """Convert list item to str if len(list) == 1 else joins the list."""
        return (
            (
                f", ".join(settings_list)
                if len(settings_list) > 1
                else list(settings_list)[0]
            )
            if settings_list
            else None
        )
