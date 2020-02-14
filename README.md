# AutoMoLi - **Auto**matic **Mo**tion **Li**ghts

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

Fully *automatic light management* based on motion as [AppDaemon](https://github.com/home-assistant/appdaemon) app.  

## Features

* multiple `daytimes` to define different scenes for morning, noon, ...
* supports **Hue** (for Hue Rooms/Groups) & **Home Assistant** scenes
* switches lights **and** plugs (with lights)
* supports **illumination sensors** to switch the light just if needed
* supports **humidity sensors** as blocker (the "*shower case*")

## Installation

Use [HACS](https://github.com/custom-components/hacs) or [download](https://github.com/benleb/ad-automoli/releases) the `automoli` directory from inside the `apps` directory here to your local `apps` directory, then add the configuration to enable the `automoli` module.

## Requirements/Usage

### *some things are not yet documented here but the code is commented*

* This must be loaded/configured for every **`room`** separately, see example configuration.
* if sensors/lights entities are in this form *sensor.illumination_**`room`***, *binary_sensor.motion_sensor_**`room`*** or *binary_sensor.motion_sensor_**`room`**_something* and *light.**`room`***, AutoMoLi will detect them automatically. Manually configured entities have precedence.

## App configuration

Add your configuration to appdaemon/apps/apps.yaml, an example is below.

```yaml
livingroom:
  module: automoli
  class: AutoMoLi
  room: livingroom
  disable_switch_entity: input_boolean.automoli
  delay: 600
  daytimes:
    - { starttime: "05:30", name: morning, light: "Morning" }
    - { starttime: "07:30", name: day, light: "Working" }
    - { starttime: "20:30", name: evening, light: 90 }
    - { starttime: "22:30", name: night, light: 20 }
    - { starttime: "23:30", name: more_night, light: 0 }
  illuminance_threshold: 100
  lights:
    - light.livingroom
  motion:
    - binary_sensor.motion_sensor_153d000224f421
    - binary_sensor.motion_sensor_128d4101b95fb7
  humidity:
    - sensor.humidity_128d4101b95fb7

bathroom:
  module: automoli
  class: AutoMoLi
  room: bathroom
  disable_switch_entity: input_boolean.automoli
  delay: 180
  motion_state_on: "on"
  motion_state_off: "off"
  daytimes:
    - { starttime: "05:30", name: morning, light: 45 }
    - { starttime: "07:30", name: day, light: "Day" }
    - { starttime: "20:30", name: evening, light: 100 }
    - { starttime: "22:30", name: night, light: 0 }
  humidity:
    - sensor.humidity_128d4101b95fb7
  humidity_threshold: 75
  lights:
    - light.bathroom
    - switch.plug_68fe8b4c9fa1
  motion:
    - binary_sensor.motion_sensor_158d033224e141
```

key | optional | type | default | description
-- | -- | -- | -- | --
`module` | False | string | automoli | The module name of the app.
`class` | False | string | AutoMoLi | The name of the Class.
`room` | False | string | | The "room" used to find matching sensors/light
`disable_switch_entity` | True | str | | A Home Assistant Entity as switch for AutoMoLi. If the state of the entity if *off*, AutoMoLi is *deactivated*. (Use an *input_boolean* for example)
`delay` | True | integer | 150 | Seconds without motion until lights will switched off. Can be disabled (lights stay always on) with `0`
`motion_event` | True | string | | *Please update your config to use **motion_state_on/off***
`daytimes` | True | list | *see code* | Different daytimes with light settings (see below)
`lights` | True | list/string | *auto detect* | Light entities
`motion` | True | list/string | *auto detect* | Motion sensor entities
`illuminance` | True | list/string |  | Illuminance sensor entities
`illuminance_threshold` | True | integer |  | If illuminance is *above* this value, lights will *not switched on*
`humidity` | True | list/string |  | Humidity sensor entities
`humidity_threshold` | True | integer |  | If humidity is *above* this value, lights will *not switched off*
`motion_state_on` | True | integer | | If using motion sensors which don't send events if already activated, like Xiaomi do, add this to your config with "on". This will listen to state changes instead
`motion_state_off` | True | integer | | If using motion sensors which don't send events if already activated, like Xiaomi do, add this to your config with "off". This will listen to the state changes instead.

### daytimes

key | optional | type | default | description
-- | -- | -- | -- | --
`starttime` | False | string | | Time this daytime starts
`name` | False | string | | A name for this daytime
`delay` | True | integer | 150 | Seconds without motion until lights will switched off. Can be disabled (lights stay always on) with `0`. Setting this will overwrite the global `delay` setting for this daytime.
`light` | False | integer/string | | Light setting (percent integer value (0-100) in or scene name)
