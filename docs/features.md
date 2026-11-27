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

## Outdoor Siren

The Outdoor Siren (T8970) has a **Siren** entity that works the same way as the
doorbell's: it sounds for 10 seconds, or for the duration you give from 1 to 30 seconds,
and turning it off stops it. It uses the same local command as the doorbell siren, which
other eufy projects use for this siren too. It has not yet been tested on real hardware.

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
