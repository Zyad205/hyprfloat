import os
import json
import re
from socket import socket, AF_UNIX, SOCK_STREAM
from .db_helper import DbHelper
from .utils import hyprctl
from .settings import CONF_DIR, SOCKET_PATH

# The name of the events we only care about from the socket
IMPORTANT_EVENTS = [
    "movewindowv2",
    "openwindow",
    "closewindow",
    "changefloatingmode",
    "workspacev2",
    "activewindowv2",
    "windowtitlev2",
    "urgent",
    "activespecialv2",
    "focusedmon"
    ]


def event_parser(events):
    """It gives a list of events turned into list for each one made
    of ['Event Name', its other return values either one or two]
    """
    events_list = []
    for event in events:
        event_name, event_args = event.split('>>')
        if event_name in IMPORTANT_EVENTS:
            event_args_list = event_args.split(',')
            events_list.append([event_name, *event_args_list])
    return events_list

def format_window(window, width: int = 1050, height:int= 630, offset: tuple(int) = (0, 0)) -> None:
    address = window['address']

    # If the window is not floating, float it.
    if not window['floating']:
        hyprctl(['dispatch', f'hl.dsp.window.float{{action = "enable", window = "address:{address}"}}'])
        # 'hl.dsp.window.float{ action = "enable", window = "address:0x559896e6cd30" }'
        # hl.dsp.window.float({ action = "toggle" }))


    # Resize the window
    hyprctl(['dispatch', f'hl.dsp.window.resize({{x = {width}, y= {height}, window = "address:{address}"}})'])
    # hl.dsp.window.resize({ x, y, relative?, window? })
    # hyprctl dispatch 'hl.dsp.window.resize({ x = 500, y = 400, window = "address:0x559896e6c3b0" })'

    # Center the window
    hyprctl(['dispatch', f'gl.dsp.window.center({{"address:{address}"}})'])
    # hl.dsp.window.center({ "address:0x00" })


    # Offset the window if needed.
    hyprctl(['dispatch', f'hl.dsp.window.move({{x= {offset[0]}, y = {offset[1]}, window = "address:{address}}})'])
    # hl.dsp.window.move({ x, y, relative?, window? })


def query_workspace(id):
    clients = hyprctl(['clients'])
    active_clients_list = []

    # Exits if there is no windows
    if not clients: return

    for client in clients:
        if client['workspace']['id'] == id:
            active_clients_list.append(sanitize_window(client))
            
    return active_clients_list

def sanitize_window(window: dict) -> dict:
    keys_to_keep = ["address", "workspace", "floating", "class", "title"]
    # Keep only keys that exist in the original dictionary
    filtered_window_dict = {k: window[k] for k in keys_to_keep if k in window}

    return filtered_window_dict

class Hyprfloat:
    def __init__(self):
        '''Initialize the database and the list of windows to ignore.'''
        self.db = DbHelper()
        self.address_to_ignore = []
        # self.user_tiled_windows = {
        #     1: [],
        #     2: [],
        #     3: [],
        #     4: [],
        #     5: [],
        #     6: [],
        #     7: [],
        #     8: [],
        #     9: [],
        #     -98: [],
            # }
        self.active_workspace_id = None  # Track the last active workspace
        self.user_tiled_windows = []
        
        self.monitors = self.db.get('monitors') or {}
        self.terminals = self.db.get('terminal_classes') or []
        self.ignore_titles = self.db.get('ignore_titles', []) or []
        # To be implemented to get from config file
        self.ignore_special_workspaces = False 

        self.program_tiled_windows = []
        self.ignore_next_float_event_counter = 0
        self.in_special_workspace = False
        self.special_workspace_id = -98

        # width = self.monitors[active_monitor]['width']
        # height = self.monitors[active_monitor]['height']
        # offset = self.monitors[active_monitor]['offset']

    def change_floating_handler(self, event):
        window_address = "0x" + event[1]
        is_floated = int(event[2])
        if not is_floated:            
            self.user_tiled_windows.append(window_address)

        elif is_floated:
            if window_address in self.user_tiled_windows:
                self.user_tiled_windows.remove(window_address)


    def make_windows_normal(self, windows):
        for window in windows:
            address = window['address']
            if window['floating']:
                hyprctl(['dispatch', f'hl.dsp.window.float{{action = "disable", window = "address:{address}"}}'])
                self.program_tiled_windows.append(address)

    def floation_manager(self, windows):
        if len(windows) == 1:
            window = windows[0]
            window_address = window['address']
            if ( window["class"] in self.terminals and
                 not window['title'] in self.ignore_titles and
                 not window_address in self.user_tiled_windows ):

                format_window(window)

            elif window["title"] in self.ignore_titles:
                self.make_windows_normal([window])

        else:
            windows = [sanitize_window(window) for window in windows]
            self.make_windows_normal(windows)
            

    def custom_handler(self, event):
        event_type = event[0]
        IMP = ["workspacev2", "openwindow", "closewindow", "windowtitlev2"]

        if self.in_special_workspace: active_workspace_id = self.special_workspace_id
        else: active_workspace_id = hyprctl(['activeworkspace'])['id']
        windows = query_workspace(active_workspace_id)

        if event_type in IMP:
            self.floation_manager(windows)
            if event_type == "closewindow":
                for window in windows:
                    if window['address'] in self.user_tiled_windows:
                        self.user_tiled_windows.remove(window['address'])
                        self.floation_manager(windows)
                    

        elif event_type == "changefloatingmode":
            window_address = "0x" + event[1]
            if window_address in self.program_tiled_windows:
                self.program_tiled_windows.remove(window_address)
            else:
                if len(windows) == 1:
                    self.change_floating_handler(event)


        elif event_type == "activespecialv2" and not self.ignore_special_workspaces:
            special_workspace_id = event[1]
            if special_workspace_id:
                special_workspace_id = int(special_workspace_id)
                self.in_special_workspace = True
                self.special_workspace_id = special_workspace_id
                windows = query_workspace(special_workspace_id)
                self.floation_manager(windows)
            else:
                self.in_special_workspace = False

    def iterate_events(self, events):
        for event in events:
            self.custom_handler(event)

def main():
    '''Main function of the script.'''
    os.makedirs(CONF_DIR, exist_ok=True)
    hyprfloat = Hyprfloat()

    # Connect to Hyprland's socket and listen for events.
    with socket(AF_UNIX, SOCK_STREAM) as sock:
        sock.connect(SOCKET_PATH)
        while True:
            events = sock.recv(1024).decode().strip().split('\n')
            if events:
                parsed_events = event_parser(events)
                if parsed_events: hyprfloat.iterate_events(parsed_events)
