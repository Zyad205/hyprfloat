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

        self.ignore_next_float_event_counter = 0
        self.in_special_workspace = False
        self.special_workspace_id = -98


    def handle_open_window(self, event_data):
        '''Handle the `openwindow` event from Hyprland's socket.'''
        ignore_titles = self.db.get('ignore_titles', []) or []
        address = f'0x{event_data[0]}'

        data_empty = event_data[3] == ''
        data_ignore = any(re.search(pattern, event_data[3]) for pattern in ignore_titles)

        # If the window is a new window with empty title, add it to the ignore list.
        if data_empty or data_ignore:
            self.address_to_ignore.append(address)
            return True
        return False

    def handle_close_window(self, event_data):
        '''Handle the `closewindow` event from Hyprland's socket.'''
        address = f'0x{event_data}'
        # If the window is in the ignore list, remove it.
        if address in self.address_to_ignore:
            self.address_to_ignore.remove(address)
        if address in self.user_tiled_windows:
            self.user_tiled_windows.remove(address)

    def handle_change_floating_mode(self, event_data, workspace_windows):
        '''Handle the `changefloatingmode` event from Hyprland's socket.'''
        window_address, floating = event_data
        address = f'0x{window_address}'

        # Find the window that was changed.
        try:
            window = next(w for w in workspace_windows if w['address'] == address)
        except StopIteration:
            return

        terminals = self.db.get('terminal_classes') or []
        # If the window is a terminal, add or remove it from the user_tiled_windows list.
        if window['class'] in terminals:
            if floating == 0:  # tiled
                if address not in self.user_tiled_windows:
                    self.user_tiled_windows.append(address)
            else:  # floating
                if address in self.user_tiled_windows:
                    self.user_tiled_windows.remove(address)

    def handle_change(self, workspace_windows, active_monitor, event_info=None, from_close=False):
        '''Handle the floating and tiling of windows.'''
        monitors = self.db.get('monitors') or {}
        terminals = self.db.get('terminal_classes') or []
        ignore_titles = self.db.get('ignore_titles', []) or []
        event_type, event_data = event_info if event_info else (None, None)
        visible_windows = [w for w in workspace_windows if not w['hidden']]
        # If there is only one visible window in the workspace, float it.
        if len(visible_windows) == 1:
            window = visible_windows[0]
            # If the window is tagged as not floating, do nothing.
            if window['address'] in self.user_tiled_windows:
                return

            # If the window is not in the terminal list, do nothing.
            if window['class'] not in terminals:
                return

            if any(re.search(pattern, window['title']) for pattern in ignore_titles):
                return

            # Check if monitor configuration exists
            if active_monitor not in monitors:
                return

            width = monitors[active_monitor]['width']
            height = monitors[active_monitor]['height']
            offset = monitors[active_monitor]['offset']
            format_window(window, width, height, offset)
        # If there are multiple windows in the workspace, tile them.
        # Only trigger auto-tiling for openwindow events (new windows)
        # Do NOT trigger for movewindow events (user manually moving windows)
        elif len(workspace_windows) >= 2 and event_type in ('openwindow', 'urgent') and event_data:
            new_window_address = '0x' + event_data[0]
            try:
                new_window = next(w for w in workspace_windows if w['address'] == new_window_address)
                existing_window = next(w for w in workspace_windows if w['address'] != new_window_address)
            except StopIteration:
                # If the window is not found, do nothing and let the default behavior handle it.
                pass
            else:
                if (
                    existing_window['title'] in ignore_titles or
                    new_window['title'] in ignore_titles or
                    (new_window['floating'] == True and event_type != 'movewindowv2')
                ):
                    return
                # Float the new window, center it and move it to the right then
                # tile the existing one, finally tile the new one.



                new_address = new_window['address']
                hyprctl(['dispatch', f'hl.dsp.window.float{{action = "enable", window = "address:{new_address}"}}'])
                hyprctl(['dispatch', f'hl.dsp.window.center({{"address:{new_address}"}})'])
                # Don't know what the old one did so change if you do
                hyprctl(['dispatch', f'hl.dsp.window.move({{direction = "r", window = "address:{new_address}"}})'])
                hyprctl(['dispatch', f'hl.dsp.window.float{{action = "disable", window = "address:{existing_window['address']}"}}'])
                hyprctl(['dispatch', f'hl.dsp.window.focus{{window = "address:{new_address}"}}'])
                # hyprctl(['dispatch', 'settiled']) what is this fore i dont know but i think tiling the new window
                hyprctl(['dispatch', f'hl.dsp.window.float{{action = "disable", window = "address:{new_address}"}}'])


        elif len(visible_windows) >= 2 and event_type in ('workspacev2', 'movewindowv2'):
            # On workspace change or window move, ensure all floating terminal windows are tiled.
            # Prioritize by focus history to tile the most recently focused windows first.
            
            # For movewindow events, identify the moved window to position it on the right
            moved_window_address = None
            if event_type == 'movewindowv2' and event_data:
                moved_window_address = '0x' + event_data[0]
            
            for window in sorted(workspace_windows, key=lambda w: w['focusHistoryID'], reverse=True):
                if (
                    window['class'] in terminals and
                    window['floating'] and
                    window['address'] not in self.user_tiled_windows and
                    not any(re.search(pattern, window['title']) for pattern in ignore_titles)
                ):


                    address = window['address']
                    hyprctl(['dispatch', f'hl.dsp.window.center({{"address:{address}"}})'])
                    hyprctl(['dispatch', f'hl.dsp.window.focus{{window = "address:{address}"}}'])
                    hyprctl(['dispatch', f'hl.dsp.window.move({{direction = "r"}})'])
                    hyprctl(['dispatch', f'hl.dsp.window.focus{{window = "address:{address}"}}'])
                    hyprctl(['dispatch', f'hl.dsp.window.float({{action = "disable"}})'])


            
            # If this is a movewindow event, position the moved window on the right
            if moved_window_address:
                try:
                    moved_window = next(w for w in workspace_windows if w['address'] == moved_window_address)
                    # Only reposition if the moved window is now tiled (not floating)
                    if not moved_window['floating']:

                        hyprctl(['dispatch', f'hl.dsp.window.focus({{window = "address:{moved_window_address}"}})'])
                        hyprctl(['dispatch', f'hl.dsp.window.move({{direction = "r"}})'])

                except StopIteration:
                    pass

    def handle_event(self, event):
        '''Main event handler.'''
        event_type = event[0]
        event_data = event[1:]

        # For movewindow events, determine the target workspace from the event data
        if event_type == 'movewindowv2':
            # movewindow format: address,workspace-_id
            moved_window_address = '0x' + event_data[0]
            target_workspace_id = int(event_data[1])
            clients = json.loads(hyprctl(['clients', '-j']).stdout)
            
            # Find the moved window and check if it should be ignored
            ignore_titles = self.db.get('ignore_titles', []) or []
            moved_window = None
            for client in clients:
                if client['address'] == moved_window_address:
                    moved_window = client

                    break

            # If the moved window has an ignored title, don't process the move
            if moved_window and any(re.search(pattern, moved_window['title']) for pattern in ignore_titles):
                return
            # Get windows for the target workspace
            target_workspace_windows = [c for c in clients if c['workspace']['id'] == target_workspace_id]
            
            # Get the monitor for the target workspace
            workspaces = json.loads(hyprctl(['workspaces', '-j']).stdout)
            target_workspace = next((w for w in workspaces if w['id'] == target_workspace_id), None)
            target_monitor = target_workspace['monitor'] if target_workspace else None
            
            # Also check the active workspace (source) - it might now have only 1 window left
            active_workspace = json.loads(hyprctl(['activeworkspace', '-j']).stdout)
            if active_workspace['id'] != target_workspace_id:
                source_workspace_windows = [c for c in clients if c['workspace']['id'] == active_workspace['id']]
                self.handle_change(source_workspace_windows, active_workspace['monitor'], (event_type, event_data))
            
            return
        else:
            # Get the current workspace and windows.
            workspace = json.loads(hyprctl(['activeworkspace', '-j']).stdout)
            workspace_id = workspace['id']
            active_monitor = workspace['monitor']
            clients = json.loads(hyprctl(['clients', '-j']).stdout)
            workspace_windows = [c for c in clients if c['workspace']['id'] == workspace_id]
            
            # If workspace or focusedmon event, check if the previous workspace needs updating
            if event_type in ('workspacev2', 'focusedmon') and self.active_workspace_id is not None:
                if self.active_workspace_id != workspace_id:
                    # Check the previous workspace
                    previous_workspace_windows = [c for c in clients if c['workspace']['id'] == self.active_workspace_id]
                    if previous_workspace_windows:
                        workspaces = json.loads(hyprctl(['workspaces', '-j']).stdout)
                        previous_workspace = next((w for w in workspaces if w['id'] == self.active_workspace_id), None)
                        if previous_workspace:
                            self.handle_change(previous_workspace_windows, previous_workspace['monitor'], (event_type, event_data))
            
            # Update the tracked workspace
            self.active_workspace_id = workspace_id

        # Handle the event.
        if event_type == 'openwindow':
            if self.handle_open_window(event_data):
                return
            self.handle_change(workspace_windows, active_monitor, (event_type, event_data))

        elif event_type == 'closewindow':
            self.handle_close_window(event_data[0])
            self.handle_change(workspace_windows, active_monitor, (event_type, event_data), True)

        elif event_type == 'changefloatingmode':
            self.handle_change_floating_mode(event_data, workspace_windows)
        elif event_type in ('workspacev2', 'movewindowv2', 'activewindowv2', 'windowtitlev2', 'urgent'):
            self.handle_change(workspace_windows, active_monitor, (event_type, event_data))

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
                self.ignore_next_float_event_counter += 1


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

            # SOLVED IN ANOTHER WAY DONT LISTEN
            # Solves when a window is floating and another window opens the floating window 
            # unfloats and mistakenly stored as user_tiled_window
            # So it deletes user tiled windows in workspace when more than one app is present
            

    def custom_handler(self, event):
        event_type = event[0]
        IMP = ["workspacev2", "openwindow", "closewindow", "windowtitlev2"]
        if event_type in IMP:
            
            if self.in_special_workspace: active_workspace_id = self.special_workspace_id
            else: active_workspace_id = hyprctl(['activeworkspace'])['id']
            windows = query_workspace(active_workspace_id)
            self.floation_manager(windows)

            if event_type == "closewindow":
                for window in windows:
                    if window['address'] in self.user_tiled_windows:
                        self.user_tiled_windows.remove(window['address'])
                        self.floation_manager(windows)
                    

        elif event_type == "changefloatingmode":
            if self.ignore_next_float_event_counter: self.ignore_next_float_event_counter -= False

            else: self.change_floating_handler(event)

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
            print(self.user_tiled_windows)
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
