# Added features

These features are not in the integration this one is based on. Each one talks to the
device over your local network. They were tested on an E340 doorbell (T8214) and two
HomeBase 3 units (T8030), except where a section says otherwise.
[CHANGES-FROM-UPSTREAM.md](../CHANGES-FROM-UPSTREAM.md) lists the code behind each one and
where its protocol details came from.

## HomeBase restart

Each HomeBase has a **Restart** button. It is disabled by default because the HomeBase
does not protect the house while it boots, which takes about a minute. To use it, enable
the button on the HomeBase's device page.

While the HomeBase restarts, its entities and the devices paired to it show as
unavailable, and doorbell rings do not reach Home Assistant. They come back on their own
when the HomeBase is running again.

## Night arm

The alarm panel offers **Arm night** on any HomeBase that has the eufy app's Custom 1 mode
set up. Arming Night switches the HomeBase to Custom 1, and a HomeBase in Custom 1 shows
as **armed night**. The arming event also reports `armed_night`. Schedule, geofencing and
Custom 2 and 3 still show as custom bypass.

## Entry and exit delays

Each HomeBase has two sensors, **Entry delay ends** and **Exit delay ends**. While the
alarm panel counts an entry delay or an exit delay, the sensor shows when it ends, and
Home Assistant shows that as a countdown. Otherwise the sensor is unknown.

The entry delay sensor clears when the alarm goes off, when you disarm, or about two
seconds after the delay runs out, when the panel stops showing pending. The exit delay
sensor clears when the delay runs out, even though the panel may show arming a little
longer until the HomeBase confirms its mode. An exit delay running during a restart of
Home Assistant is not shown again afterwards.

The sensors follow the alarm panel, so a delay the panel does not show does not appear
here either. If you disable the alarm panel, both sensors stay unknown.

The length of each delay is set per mode in the eufy app or on the
[HomeBase card](homebase-card.md). These sensors have not yet been seen with a real
delay; the behaviour is covered by automated tests.

## Arming event

Each HomeBase's **Arming** event fires when the mode in force changes. eufy sends a
push for a mode change only when the HomeBase's "Switching notification" for that kind
of change is on, so the event also fires from the HomeBase's own report over the local
network, about three seconds after the change. When a push for the same change arrives
in that time, the event fires once, with **changed_by** saying who changed it (App,
Keypad, Schedule and so on). Without a push, changed_by is left out, and that includes
arming from Home Assistant. A push that arrives later than that is not fired again.

The event always ends on the mode the HomeBase is in: a quick change and change back
fires nothing, and changes keep their order. If Home Assistant missed the HomeBase's
report, for example while the HomeBase was unreachable, the change fires when the next
poll finds it, up to about 45 seconds late, with the time it was found.

## Last visitor

Each camera has a **Last visitor** sensor. It shows the name of the last person the camera
recognised and keeps that name until it recognises someone else. A stranger or an
unrecognised person does not change it. The `detected_at` attribute gives the time of
that detection, and the value survives a restart.

The name comes from eufy's face recognition, so a person only appears here if eufy
recognised them. A recognised name has not yet been seen on real hardware; the
behaviour is covered by automated tests.

## Packages

The doorbell has three sensors: **Package delivered**, **Package taken** and **Package
stranded**. Each one turns on when eufy reports that event and stays on for the detection
hold set in the integration's options (10 seconds by default). A HomeBase 3 sends these
events over the local network, so cloud push does not need to be on.

These sensors report events. They do not show whether a package is still at the door.
Package delivered has been seen on real hardware; taken and stranded have not yet.

## Doorbell siren

The E340 doorbell has a **Siren** entity. Turning it on sounds the doorbell's siren for
10 seconds, or for the duration you give, from 1 to 30 seconds. Turning it off stops it.
The siren shows as on until its time runs out or you turn it off.

```yaml
action: siren.turn_on
target:
  entity_id: siren.front_door_siren
data:
  duration: 5
```

## Doorbell night vision

The E340 doorbell has a **Night vision** select under Configuration: Off, Infrared or
Spotlight. It shows what the doorbell reports, and a change is sent over the local
network as the eufy app sends it. As in the eufy app, a change also sets the doorbell's
**Bottom spotlight** switch. If the doorbell takes only part of a change, Home Assistant
says so; choose the setting again. It has not yet been tested on real hardware.

## Quick replies

The E340 doorbell has a button for each of eufy's three built-in replies: "Excuse me, can
I help you", "Please leave it at the door" and "We will be right there". Pressing a button
plays that reply through the doorbell's speaker.

The `anker_eufy_integration.quick_response` action plays any reply by its number. Numbers
1 to 3 are the built-in replies, and replies you recorded in the eufy app start at 100.

```yaml
action: anker_eufy_integration.quick_response
target:
  entity_id: camera.front_door
data:
  voice_id: 100
```

## Playing a sound file

The `anker_eufy_integration.play_audio` action plays a sound file through the E340
doorbell's speaker. The file must be in a folder Home Assistant is allowed to read, such
as `/media`. Any format that ffmpeg can read will work, and playback stops after 60
seconds.

```yaml
action: anker_eufy_integration.play_audio
target:
  entity_id: camera.front_door
data:
  media_path: /media/doorbell/hello.mp3
```

Home Assistant opens the doorbell's live stream while the sound plays and closes it
afterwards, which uses some battery. The HomeBase may report an alarm event as the sound
starts; this does not sound an alarm.

## Calibrate and turn 360°

The SoloCam S340 has two more buttons. **Calibrate** re-centres the camera's pan and tilt;
it is under Configuration on the camera's device page. **Turn 360°** turns the camera once
round. Both are sent over the local network, as other eufy projects send them to this
camera. They have not yet been tested on real hardware.

## Connected

Each HomeBase has a **Connected** sensor. It is on while Home Assistant holds the
HomeBase's local connection, and turns off about ten seconds after that connection is
lost. It stays visible while the HomeBase is unreachable, so you can use it in an
automation.

Each camera and sensor paired to a HomeBase also has a **Connected** sensor. It shows
whether the HomeBase still reaches that device. When the HomeBase reports the device
offline, the sensor is off, and any reason code the HomeBase gives is in its
`offline_code` attribute. The device's other entities show as unavailable at that point,
as before. While the HomeBase itself is unreachable, the device's Connected sensor is
unavailable too, because nothing is known about the device then.

## Battery health

Every camera that reports its battery health has a **Battery health** sensor, in percent.
That includes the S3 Pro (T8162) and the SoloCam S340 (T8170), whose battery health the
eufy app does not show. On a eufyCam 3 (T8160) it replaces the earlier "Battery healthy"
sensor and keeps that sensor's entity ID and history.

## Firmware updates

Each device's **Firmware update** entity now shows the version eufy offers. This is the
one feature here that uses eufy's cloud, because only eufy knows what it has published.
The check runs at most once every 12 hours, and not during start-up. It is remembered
across restarts, so a restart does not cause another check.

- An offer shows as an update, with eufy's release notes and a `forced` attribute.
- The entity shows **up to date** only when eufy confirmed the version the device is
  running now. Otherwise it stays unknown.
- While a HomeBase installs firmware, the entity shows it as in progress. That comes from
  the HomeBase over the local network.
- The `secondary_firmware` attribute shows the device's second firmware version.

Home Assistant cannot install firmware here: eufy installs it, or you start it in the
eufy app.

## H.264 live view

Most of these cameras send H.265 video. Some players cannot show it, such as Firefox
and some Android phones. The **Live view format** option, under **Live view and
recording** in the integration's options, converts it to H.264:

- **Native** (the default) sends the camera's own video, untouched.
- **H.264, low CPU** keeps every second picture, at most 720 lines high. Use this on a
  small machine.
- **H.264, full quality** keeps the camera's own size and picture rate. This uses much
  more processor time, most of all on a 4K camera.

The conversion uses Home Assistant's own ffmpeg and runs only while a live view is open.
A camera that already sends H.264 is never converted. If ffmpeg cannot start, the view
carries on in H.265 and the log says why. Changing the option ends running live views.
It runs in software, so if a converted view falls behind, choose the low CPU choice or
lower the camera's streaming quality.

The idea and the encoder settings follow the "Low-CPU H.265 live view conversion" of
Eufy Mega Security. This was tested with ffmpeg on sample H.265 video, not yet on a
camera.
