import os
import json
import re
from socket import socket, AF_UNIX, SOCK_STREAM
from .db_helper import DbHelper
from .utils import *
from .settings import CONF_DIR, SOCKET_PATH
from .globals import DEFAULT_CONFIG_VALUES

class Hyprfloat:
    def __init__(self):
        '''Initialize the database and the list of windows to ignore.'''
        self.db = DbHelper()
        self.address_to_ignore = []        
        self.monitors = self.db.get('monitors') or {}
        self.terminals = self.db.get('terminal_classes') or []
        self.ignore_titles = self.db.get('ignore_titles', []) or []

        # To be implemented to get from config file
        self.ignore_special_workspaces = False 

        self.active_workspace_id = None
        self.user_tiled_windows = []
        self.program_tiled_windows = []
        self.in_special_workspace = False
        self.special_workspace_id = -98

    def get_monitor_config (self, active_monitor) -> ((int, int), (int, int)):
        """Returns window size and offset for given monitor and if doesn't exist 
        it returns DEFAULT_CONFIG_VALUES"""

        try:
            width = self.monitors[active_monitor]['width']
            height = self.monitors[active_monitor]['height']
            offset = self.monitors[active_monitor]['offset']
            return ((width, height), offset)

        except KeyError:
            return (DEFAULT_CONFIG_VALUES["size"], DEFAULT_CONFIG_VALUES["offset"])

    def change_floating_handler(self, event):
        """Adds or remove a window from user_tiled_windows depends if it was floated or not"""

        window_address = "0x" + event[1]
        is_floated = int(event[2])
        if not is_floated:            
            self.user_tiled_windows.append(window_address)

        elif is_floated:
            if window_address in self.user_tiled_windows:
                self.user_tiled_windows.remove(window_address)


    def make_windows_normal(self, windows):
        """Makes give windows tiled and stores them in program_tiled_windows so they dont get 
        confused as user_tiled_windows"""

        for window in windows:
            address = window['address']
            if window['floating']:
                hyprctl(['dispatch', f'hl.dsp.window.float{{action = "disable", window = "address:{address}"}}'])
                self.program_tiled_windows.append(address)

    def floation_manager(self, windows):
        """Calls format_window to float a singular terminal when it has correct attributes
        or calls make_windows_normal when it doesn't or their is more than one window"""

        if len(windows) == 1:
            window = windows[0]
            window_address = window['address']
            active_monitor = hyprctl(["activeworkspace"])["monitor"]

            if ( window["class"] in self.terminals and
                 not window['title'] in self.ignore_titles and
                 not window_address in self.user_tiled_windows ):

                format_window(window, *self.get_monitor_config(active_monitor))

            elif window["title"] in self.ignore_titles:
                self.make_windows_normal([window])

        else:
            windows = [sanitize_window(window) for window in windows]
            self.make_windows_normal(windows)
            

    def event_handler(self, event):
        """Main function that handles the events"""

        event_type = event[0]
        # Sets the active_workspace either normal or special
        if self.in_special_workspace: active_workspace_id = self.special_workspace_id
        else: active_workspace_id = hyprctl(['activeworkspace'])['id']

        windows = query_workspace(active_workspace_id)

        if event_type in ["workspacev2", "openwindow", "closewindow", "windowtitlev2"]:

            self.floation_manager(windows)

            if event_type == "closewindow":
                for window in windows:
                    if window['address'] in self.user_tiled_windows:
                        self.user_tiled_windows.remove(window['address'])
                        self.floation_manager(windows)
                    

        elif event_type == "changefloatingmode":
            window_address = "0x" + event[1]
            # Skips changefloatingmode events executed by the program
            if window_address in self.program_tiled_windows:
                self.program_tiled_windows.remove(window_address)
            else:
                # Only stores the window as user_tiled_window when their is a singular
                # Window
                if len(windows) == 1 and not int(event[2]):
                    self.change_floating_handler(event)


        elif event_type == "activespecialv2" and not self.ignore_special_workspaces:
            # If empty then special workspace is deactivated 
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
            self.event_handler(event)

def main():
    '''Main function of the script.'''
    os.makedirs(CONF_DIR, exist_ok=True)
    hyprfloat = Hyprfloat()

    # Connect to Hyprland's socket and listen for events.
    with socket(AF_UNIX, SOCK_STREAM) as sock:
        sock.connect(SOCKET_PATH)
        while True:
            events = sock.recv(1024).decode().strip().split('\n')

            # Only executed when there is an event
            if events:
                parsed_events = event_parser(events)
                if parsed_events: hyprfloat.iterate_events(parsed_events)
