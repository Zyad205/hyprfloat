import subprocess
import json

def hyprctl(cmd):
	'''A wrapper for the hyprctl command.'''
	return_value = subprocess.run(['hyprctl'] + cmd + ["-j"], capture_output = True, text = True)
	try:
		parsed_value = json.loads(return_value.stdout)
		return parsed_value
	except json.decoder.JSONDecodeError:
		pass
