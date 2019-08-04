## App configuration

```yaml
livingroom:
  module: automoli
  class: AutoMoLi
  room: livingroom
  delay: 600
  daytimes:
    - { starttime: "05:30", name: morning, light: "Morning" }
    - { starttime: "07:30", name: day, light: "Working" }
    - { starttime: "20:30", name: evening, light: 90 }
    - { starttime: "22:30", name: night, light: 20 }
    - { starttime: "23:30", name: more_night, light: 0 }
  humidity_threshold: 75
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
  delay: 180
  daytimes:
    - { starttime: "05:30", name: morning, light: 45 }
    - { starttime: "07:30", name: day, light: "Day" }
    - { starttime: "20:30", name: evening, light: 100 }
    - { starttime: "22:30", name: night, light: 0 }
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
`delay` | True | integer | 150 | Seconds without motion until lights will switched off
`daytimes` | True | list | *see code* | Different daytimes with light settings (see below)
`lights` | True | list/string | *auto detect* | Light entities
`motion` | True | list/string | *auto detect* | Motion sensor entities
`humidity` | True | list/string |  | Humidity sensor entities
`humidity_threshold` | True | integer |  | If humidity is above this value, lights will not switched off

#### daytimes
key | optional | type | default | description
-- | -- | -- | -- | --
`starttime` | False | string | | Time this daytime starts
`name` | False | string | | A name for this daytime
`light` | False | integer/string | | Light setting (integer value or scene name)
