# The name of the events we only care about from the socket

IMPORTANT_EVENTS = [
    "openwindow",
    "closewindow",
    "changefloatingmode",
    "workspacev2",
    "activewindowv2",
    "windowtitlev2",
    "activespecialv2",
    "movewindowv2"
    ]

DEFAULT_CONFIG_VALUES = {
    "size": (1050, 630),
    "offset": (0, 0)
}

KEYS_TO_KEEP = [
    "address",
    "workspace",
    "floating",
    "class",
    "title",
    "xwayland"
    ]

