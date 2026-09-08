import subprocess
import json
from .globals import IMPORTANT_EVENTS

def hyprctl(cmd):
    """A wrapper for the hyprctl command"""

    return_value = subprocess.run(['hyprctl'] + cmd + ["-j"], capture_output = True, text = True)
    try:
        parsed_value = json.loads(return_value.stdout)
        return parsed_value
    except json.decoder.JSONDecodeError:
        pass

def event_parser(events):
    """It gives a list of events turned into list for each one made
    of ['Event Name', its other return values]"""

    events_list = []
    for event in events:
        event_name, event_args = event.split('>>')
        if event_name in IMPORTANT_EVENTS:
            event_args_list = event_args.split(',')
            events_list.append([event_name, *event_args_list])
    return events_list

def format_window(window, size: tuple(int, int), offset: tuple(int)) -> None:

    """Main function called when a singular terminal is in a workspace to resize and float it"""
    address = window['address']
    
    # If the window is not floating, float it.
    if not window['floating']:
        hyprctl(['dispatch', f'hl.dsp.window.float{{action = "enable", window = "address:{address}"}}'])
        # 'hl.dsp.window.float{ action = "enable", window = "address:0x559896e6cd30" }'
        # hl.dsp.window.float({ action = "toggle" }))
        
    # Broke newly opened apps
    # else:
    #     # Needed because for some reason when an already floating but not centered window is 
    #     # moved to another workspace its not centered for some reason 
    #     hyprctl(['dispatch', f'hl.dsp.window.float{{action = "disable", window = "address:{address}"}}'])
    #     hyprctl(['dispatch', f'hl.dsp.window.float{{action = "enable", window = "address:{address}"}}'])



    # Resize the window
    hyprctl(['dispatch', f'hl.dsp.window.resize({{x = {size[0]}, y= {size[1]}, window = "address:{address}"}})'])
    # hl.dsp.window.resize({ x, y, relative?, window? })
    # hyprctl dispatch 'hl.dsp.window.resize({ x = 500, y = 400, window = "address:0x559896e6c3b0" })'

    # Center the window
    hyprctl(['dispatch', f'gl.dsp.window.center({{"address:{address}"}})'])
    # hl.dsp.window.center({ "address:0x00" })


    # Offset the window if needed.
    hyprctl(['dispatch', f'hl.dsp.window.move({{x= {offset[0]}, y = {offset[1]}, window = "address:{address}}})'])
    # hl.dsp.window.move({ x, y, relative?, window? })


def query_workspace(id, sanitize_windows: bool = True):
    """Returns a list of windows in a workspace with the provided id and 
    the windows are sanitized before being returned if sanitize_windows left unchanged"""
    clients = hyprctl(['clients'])
    active_clients_list = []

    # Exits if there is no windows
    if not clients: return

    for client in clients:
        if client['workspace']['id'] == id:

            # Returns sanitized if its selected other wise adds normally
            active_clients_list.append(sanitize_window(client) if sanitize_windows else client)
            
    return active_clients_list

def sanitize_window(window: dict) -> dict:
    """Takes rid of unwanted values in window dictionaries"""

    keys_to_keep = ["address", "workspace", "floating", "class", "title"]
    # Keep only keys that exist in the original dictionary
    filtered_window_dict = {k: window[k] for k in keys_to_keep if k in window}

    return filtered_window_dict

