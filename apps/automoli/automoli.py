"""AutoMoLi.
   Automatic Motion Lights

  https://github.com/benleb/ad-automoli

  config example
  all things can be omitted except the room and delay

bathroom_lights:
  module: automoli
  class: AutoMoLi
  room: bad
  delay: 300
  daytimes:
    - { starttime: "05:30", name: morning, light: 45 }
    - { starttime: "07:30", name: day, light: "Work" }
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
from datetime import time
from typing import Any, Dict, List, Optional, Set, Union

from adutils import ADutils, hl
import hassapi as hass

APP_NAME = "AutoMoLi"
APP_ICON = "💡"
APP_VERSION = "0.5.2"

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
KEYWORD_SENSORS = "binary_sensor.motion_sensor_"
KEYWORD_SENSORS_HUMIDITY = "sensor.humidity_"
KEYWORD_SENSORS_ILLUMINANCE = "sensor.illumination_"


class AutoMoLi(hass.Hass):  # type: ignore
    """Automatic Motion Lights."""

    def initialize(self) -> None:
        """Initialize a room with AutoMoLi."""
        self.room = str(self.args.get("room"))
        # self.delay = int(self.args.get("delay", DEFAULT_DELAY))
        delay = int(self.args.get("delay", DEFAULT_DELAY))
        self.event_motion = self.args.get("motion_event", None)
        self.motion_state_on = self.args.get("motion_state_on", None)
        self.motion_state_off = self.args.get("motion_state_off", None)
        # devices
        self.lights: Set[str] = self.args.get("lights", set())
        self.sensors_motion: Set[str] = self.args.pop("motion", set())
        self.sensors_illuminance: Set[str] = self.args.pop("illuminance", set())
        self.sensors_humidity: Set[str] = self.args.pop("humidity", set())
        # device config
        self.illuminance_threshold: Optional[int] = self.args.get(
            "illuminance_threshold"
        )
        self.humidity_threshold: Optional[int] = self.args.get("humidity_threshold")

        # on/off switch via input.boolean
        self.disable_switch_entity = self.args.get("disable_switch_entity")

        # use user-defined daytimes if available
        daytimes: List[Dict[str, Union[int, str]]] = self.args.get(
            "daytimes", DEFAULT_DAYTIMES
        )

        # currently active daytime settings
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
                    f"No humidity sensors given/found ('{KEYWORD_SENSORS_HUMIDITY}') ",
                    f"→ disabling humidity threshold blocker.",
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
                    f"No illuminance sensors given/found ",
                    f"('{KEYWORD_SENSORS_ILLUMINANCE}') → ",
                    f"disabling illuminance threshold blocker.",
                )
                self.illuminance_threshold = None

        # sanity check
        if not self.sensors_motion:
            raise ValueError(f"No sensors given/found, sorry! ('{KEYWORD_SENSORS}')")
        elif not self.lights:
            raise ValueError(f"No sensors given/found, sorry! ('{KEYWORD_LIGHTS}')")

        starttimes: Set[time] = set()

        # build daytimes dict
        for idx, daytime in enumerate(daytimes):
            dt_name = daytime.get("name", f"{DEFAULT_NAME}_{idx}")
            dt_delay = daytime.get("delay", delay)
            dt_light_setting = daytime.get("light", DEFAULT_LIGHT_SETTING)
            dt_is_hue_group = (
                isinstance(dt_light_setting, str)
                and not dt_light_setting.startswith("scene.")
                and any(
                    [
                        self.get_state(entity_id=entity, attribute="is_hue_group")
                        for entity in self.lights
                    ]
                )
            )

            py37_or_higher = sys.version_info.major >= 3 and sys.version_info.minor >= 7

            dt_start: time
            try:
                if py37_or_higher:
                    dt_start = time.fromisoformat(str(daytime.get("starttime")))
                else:
                    dt_start = self.datetime.strptime(
                        str(daytime.get("starttime")), "%H:%M"
                    ).time()
            except ValueError as error:
                raise ValueError(f"missing start time in daytime '{dt_name}': {error}")

            # configuration for this daytime
            daytime = dict(
                daytime=dt_name,
                delay=dt_delay,
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
                next_dt_start = self.datetime.strptime(
                    str(daytimes[(idx + 1) % len(daytimes)].get("starttime")), "%H:%M"
                ).time()

            # collect all start times for sanity check
            if dt_start in starttimes:
                raise ValueError(
                    f"Start times of all daytimes have to be unique! ",
                    f"Duplicate found: {dt_start}",
                )

            starttimes.add(dt_start)

            # check if this daytime should ne active now
            if self.now_is_between(str(dt_start), str(next_dt_start)):
                self.switch_daytime(dict(daytime=daytime, initial=True))
                self.args["active_daytime"] = daytime.get("daytime")

            # schedule callbacks for daytime switching
            self.run_daily(
                self.switch_daytime, dt_start, random_start=-10, **dict(daytime=daytime)
            )

        # set up event listener for each sensor
        for sensor in self.sensors_motion:
            # listen to xiaomi sensors by default
            if not any([self.motion_state_on, self.motion_state_off]):
                self.listen_event(
                    self.motion_event, event=EVENT_MOTION_XIAOMI, entity_id=sensor
                )
                self.refresh_timer()

                # do not use listen event and listen state below together
                continue

            # on/off-only sensors without events on every motion
            if self.motion_state_on and self.motion_state_off:
                self.listen_state(
                    self.motion_detected_state, entity=sensor, new=self.motion_state_on
                )
                self.listen_state(
                    self.motion_cleared_state, entity=sensor, new=self.motion_state_off
                )

            # listen for non-xiaomi events
            if self.event_motion:
                self.log(f"\nPlease update your config to use `motion_state_on/off'\n")

        # display settings
        self.args.setdefault("listeners", self.sensors_motion)
        self.args.setdefault(
            "sensors_illuminance", list(self.sensors_illuminance)
        ) if self.sensors_illuminance else None
        self.args.setdefault(
            "sensors_humidity", list(self.sensors_humidity)
        ) if self.sensors_humidity else None
        self.args["daytimes"] = daytimes

        # init adutils
        self.adu = ADutils(
            APP_NAME, self.args, icon=APP_ICON, ad=self, show_config=True
        )

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

                self.adu.log(
                    f"set {hl(self.room.capitalize())} to {hl(daytime['daytime'])} → "
                    f"{'scene' if is_scene else 'brightness'}: {hl(light_setting)}"
                    f"{'' if is_scene else '%'}, delay: {hl(delay)}sec",
                    icon=DAYTIME_SWITCH_ICON,
                )

    def motion_cleared_state(
        self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]
    ) -> None:
        # starte the timer if motion is cleared
        if all(
            [
                self.get_state(sensor) == self.motion_state_off
                for sensor in self.sensors_motion
            ]
        ):
            # all motion sensors off, starting timer
            self.refresh_timer()
        else:
            if self._handle:
                # cancelling active timer
                self.cancel_timer(self._handle)

    def motion_detected_state(
        self, entity: str, attribute: str, old: str, new: str, kwargs: Dict[str, Any]
    ) -> None:
        # wrapper function

        if self._handle:
            # cancelling active timer
            self.cancel_timer(self._handle)

        # calling motion event handler
        data: Dict[str, Any] = {"entity_id": entity, "new": new, "old": old}
        self.motion_event("state_changed_detection", data, kwargs)

    def motion_event(
        self, event: str, data: Dict[str, str], kwargs: Dict[str, Any]
    ) -> None:
        """Handle motion events."""
        self.adu.log(
            f"received '{event}' event from "
            f"'{data['entity_id'].replace(KEYWORD_SENSORS, '')}'",
            level="DEBUG",
        )

        # check if automoli is disabled via home assistant entity
        automoli_state = self.get_state(self.disable_switch_entity)
        if automoli_state == "off":
            self.adu.log(
                f"automoli is disabled via {self.disable_switch_entity} ",
                f"(state: {automoli_state})'",
            )
            return

        # turn on the lights if not already
        if not any([self.get_state(light) == "on" for light in self.lights]):
            self.lights_on()
        else:
            self.adu.log(
                f"light in {self.room.capitalize()} already on → ",
                f"refreshing the timer",
                level="DEBUG",
            )

        if event != "state_changed_detection":
            self.refresh_timer()

    def refresh_timer(self) -> None:
        """Refresh delay timer."""
        self.cancel_timer(self._handle)
        if self.active["delay"] != 0:
            self._handle = self.run_in(self.lights_off, self.active["delay"])
        # if self.delay != 0:
        #     self._handle = self.run_in(self.lights_off, self.delay)

    def lights_on(self) -> None:
        """Turn on the lights."""
        if self.illuminance_threshold:
            blocker = [
                sensor
                for sensor in self.sensors_illuminance
                if float(self.get_state(sensor)) >= self.illuminance_threshold
            ]
            if blocker:
                self.adu.log(
                    f"According to {hl(' '.join(blocker))} its already bright enough"
                )
                return

        if isinstance(self.active["light_setting"], str):

            for entity in self.lights:
                if entity.startswith("switch."):
                    self.turn_on(entity)
                if self.active["is_hue_group"] and self.get_state(
                    entity_id=entity, attribute="is_hue_group"
                ):
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
                        self.turn_on(entity)
                    else:
                        self.turn_on(
                            entity, brightness_pct=self.active["light_setting"]
                        )
                        self.adu.log(
                            f"{hl(self.room.capitalize())} turned {hl(f'on')} → "
                            f"brightness: {hl(self.active['light_setting'])}%",
                            icon=ON_ICON,
                        )

        else:
            raise ValueError(
                f"invalid brightness/scene: {self.active['light_setting']!s} "
                f"in {self.room}"
            )

    def lights_off(self, kwargs: Dict[str, Any]) -> None:
        """Turn off the lights."""
        blocker: Any = None

        if self.humidity_threshold:
            blocker = [
                sensor
                for sensor in self.sensors_humidity
                if float(self.get_state(sensor)) >= self.humidity_threshold
            ]
            blocker = blocker.pop() if blocker else None

        # turn off if not blocked
        if blocker:
            self.refresh_timer()
            self.adu.log(
                f"🛁 no motion in {hl(self.room.capitalize())} since "
                f"{hl(self.active['delay'])}s → "
                f"but {hl(float(self.get_state(blocker)))}%RH > "
                f"{self.humidity_threshold}%RH"
            )
        else:
            self.cancel_timer(self._handle)
            if any([(self.get_state(entity)) == "on" for entity in self.lights]):
                for entity in self.lights:
                    self.turn_off(entity)
                self.adu.log(
                    f"no motion in {hl(self.room.capitalize())} since "
                    f"{hl(self.active['delay'])}s → turned {hl(f'off')}",
                    icon=OFF_ICON,
                )

    def find_sensors(self, keyword: str) -> List[str]:
        """Find sensors by looking for a keyword in the friendly_name."""
        return [
            sensor
            for sensor in self.get_state()
            if keyword in sensor
            and self.room in (self.friendly_name(sensor)).lower().replace("ü", "u")
        ]
