# AutoMoLi - **Auto**matic **Mo**tion **Li**ghts

[![python_badge](https://img.shields.io/static/v1?label=python&message=3.8%20|%203.9&color=blue&style=flat)](https://www.python.org) [![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

Fully *automatic light management* based on motion as [AppDaemon](https://github.com/home-assistant/appdaemon) app.  

## Features

* multiple `daytimes` to define different scenes for morning, noon, ...
* supports **Hue** (for Hue Rooms/Groups) & **Home Assistant** scenes
* switches lights **and** plugs (with lights)
* supports **illumination sensors** to switch the light just if needed
* supports **humidity sensors** as blocker (the "*shower case*")

## Installation

Use [HACS](https://github.com/hacs/integration) or [download](https://github.com/benleb/ad-automoli/releases) the `automoli` directory from inside the `apps` directory here to your local `apps` directory, then add the configuration to enable the `automoli` module.

## Requirements/Usage

### *some things are not yet documented here but the code is commented*

* This must be loaded/configured for every **`room`** separately, see example configuration.

## Auto Detection of Lights and sensors

* if sensors/lights entities are in this form *sensor.illumination_**`room`***, *binary_sensor.motion_sensor_**`room`*** or *binary_sensor.motion_sensor_**`room`**_something* and *light.**`room`***, AutoMoLi will detect them automatically.
Manually configured entities take precedence.

## App configuration

Add your configuration to appdaemon/apps/apps.yaml, an example is below.

```yaml
livingroom:
  module: automoli
  class: AutoMoLi
  room: livingroom
  disable_switch_entities:
    - input_boolean.automoli
    - input_boolean.disable_my_house
  delay: 600
  daytimes:
#This rule "morning" uses a scene, the scene.livingroom_morning Home Assistant scene will be used
    - { starttime: "05:30", name: morning, light: "scene.livingroom_morning" }
    - { starttime: "07:30", name: day, light: "scene.livingroom_working" }
#This rule"evening" uses a percentage brightness value, and the lights specified in lights: below will be set to 90%
    - { starttime: "20:30", name: evening, light: 90 }
    - { starttime: "22:30", name: night, light: 20 }
#This rule has the lights set to 0, so they will no turn on during this time period
    - { starttime: "23:30", name: more_night, light: 0 }
#If you are using an illuminance sensor you can set the lowest value here that blocks the lights turning on if its already light enough
  illuminance_threshold: 100
#You can specify a light group or list of lights here
  lights:
    - light.livingroom
#You can specify a list of motion sensors here
  motion:
    - binary_sensor.motion_sensor_153d000224f421
    - binary_sensor.motion_sensor_128d4101b95fb7
#See below for info on humidity
  humidity:
    - sensor.humidity_128d4101b95fb7

bathroom:
  module: automoli
  class: AutoMoLi
  room: bathroom
  delay: 180
  motion_state_on: "on"
  motion_state_off: "off"
  daytimes:
    - { starttime: "05:30", name: morning, light: 45 }
    - { starttime: "07:30", name: day, light: "Day" }
    - { starttime: "20:30", name: evening, light: 100 }
    - { starttime: "22:30", name: night, light: 0 }
#As this is a bathroom there could be the case that when taking a bath or shower, motion is not detected and the lights turn off, which isnt helpful, so the following settings allow you to use a humidity sensor and humidity threshold to prevent this by detecting the humidity from the shower and blocking the lights turning off.
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
~~`disable_switch_entity`~~ | ~~True~~ | ~~string~~ | | **replaced by `disable_switch_entities`**
`disable_switch_entities` | True | list/string | | One or more Home Assistant Entities as switch for AutoMoLi. If the state of **any** entity is *off*, AutoMoLi is *deactivated*. (Use an *input_boolean* for example)
`disable_hue_groups` | False | boolean | | Disable the use of Hue Groups/Scenes
`delay` | True | integer | 150 | Seconds without motion until lights will switched off. Can be disabled (lights stay always on) with `0`
~~`motion_event`~~ | ~~True~~ | ~~string~~ | | **replaced by `motion_state_on/off`**
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
`light` | False | integer/string | | Light setting (percent integer value (0-100) in or scene entity
