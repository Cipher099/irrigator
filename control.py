#!/usr/bin/env python3

# *****************************************
# irrigator - control script
# *****************************************
#
# Description: This script controls the sprinkler relays and turns
# selected relays on/off
#
# control.py -z[xx] -d[xxx] -f
#	-z[xx]		Zone 		Turn on Zone 1,2,3,4
#	-d[xxx] 	Duration	Runtime in minutes
#	-f			Force		Force Multiple Zones or Ignore Weather
#	-i			Init		Initialize Relays to OFF
#	-w[xxxxx]	Weather		Zip Code
#
# This script runs as a separate process from the Flask / Gunicorn
# implementation which handles the web interface.
#
# *****************************************

import argparse
import sys

sys.path.append('.')
from common import *


def Irrigate(platform, zonename, duration, json_data_filename, relay_trigger=0):
    # *****************************************
    # Function: Irrigate
    # Input: platform, str zonename, int duration, str json_data_filename
    # Description: Turn on relay for duration
    # *****************************************
    errorcode = 0

    event = f"Turning on Zone: {zonename} for {duration} minutes."
    WriteLog(event)
    errorcode = errorcode + platform.setrelay(relay_trigger, zonename)  # Turning on Zone

    starttime = time.time()
    now = starttime

    while (now - starttime < (duration * 60)):
        if (CheckOverride(json_data_filename) > 0):
            break
        else:
            time.sleep(1)  # Pause for 1 Second
        now = time.time()

    event = f"Turning off Zone: {zonename}."
    WriteLog(event)

    errorcode = errorcode + platform.setrelay((not relay_trigger), zonename)  # Turning off Zone
    if (CheckOverride(json_data_filename) > 0):
        errorcode = 42

    return (errorcode)


def CheckOverride(json_data_filename):
    json_data_dict = ReadJSON(json_data_filename)

    if (json_data_dict['controls']['manual_override'] == True):
        errorcode = 42
    else:
        errorcode = 0

    return (errorcode)


def checkweather():
    # *****************************************
    # Function: checkweather
    # Input: none
    # Output: amount, errorcode
    # Description:  Read precipitation amount for last day from file
    # *****************************************
    errorcode = 0
    try:
        wx_status = ReadJSON("wx_status.json", type="weather")
    except:
        wx_status = create_wx_json()
        errorcode = 6

    return (wx_status, errorcode)


# *****************************************
# Main Program Start
# *****************************************

# control.py -z[xx] -d[xxx] -f
#	-z [name]		Zone 		Manual Mode: Turn on Zone [name]
#	-d [xxx] 		Duration	Manual Mode: Runtime in minutes
#	-f				Force		ALL Modes: Ignore Rain
#	-i				Init		ALL Modes: Initialize Relays to OFF on reboot
#   -j [filename]	JSON File  	Alternate JSON File [default: irrigator.json]
#	-s [schedule]   Schedule	Auto Mode: Select Schedule Run [name]

event = "***** Control Script Starting *****"
WriteLog(event)

# Parse Input Arguments
parser = argparse.ArgumentParser(description='Irrigator - Sprinkler Zone Control Script.  Usage as follows: ')
parser.add_argument('-z', '--zone', help='Manually turn on zone. (-z [zone_name])', required=False)
parser.add_argument('-d', '--duration', help='Duration to turn on zone. (NOTE: Works with manual zone control only)',
                    required=False)
parser.add_argument('-s', '--schedule', help='Name of schedule/program to run. Auto-Mode.', required=False)
parser.add_argument('-j', '--json', help='Use an alternative JSON settings file.  Default = [irrigator.json]',
                    required=False)
parser.add_argument('-f', '--force', help='Force irrigation regardless of weather', action='store_true', required=False)
parser.add_argument('-i', '--init', help='Initialize relays (on first boot).', action='store_true', required=False)
args = parser.parse_args()

# *****************************************
# Set variables (json,schedule,zone,duration,location)
# *****************************************
errorcode = 0

if args.json:
    json_data_filename = args.json
else:
    json_data_filename = "irrigator.json"

# General open & read JSON into a dictionary
json_data_dict = ReadJSON(json_data_filename)

relay_trigger = json_data_dict['settings']['relay_trigger']

# Flag Control Active at beginning of script
json_data_dict['controls']['active'] = True
WriteJSON(json_data_dict, json_data_filename)

if args.schedule:
    schedule_selected = args.schedule
    schedule_run = True
else:
    schedule_selected = "null"
    schedule_run = False

if args.zone:
    zone = args.zone
else:
    zone = "null"

if args.duration:
    duration = int(args.duration)
else:
    duration = 0

# Store init relays flag
init = args.init

# *****************************************
# Initialize Relays Globally
# *****************************************

# Init outpin structure
outpins = {}
for index_key, index_value in json_data_dict['zonemap'].items():
    outpins[index_key] = json_data_dict['zonemap'][index_key]['GPIO_mapping']
outpins['gate'] = json_data_dict['settings']['zone_gate']

# Init platform object
if (json_data_dict['settings']['target_sys'] == "CHIP"):
    event = "Initializing Relays on CHIP."
    WriteLog(event)
    from platform_chip import Platform

    platform = Platform(outpins, relay_trigger=relay_trigger)

elif (json_data_dict['settings']['target_sys'] == "RasPi"):
    event = "Initializing Relays on Raspberry Pi."
    WriteLog(event)
    from platform_raspi import Platform

    platform = Platform(outpins, relay_trigger=relay_trigger)

else:
    event = "Initializing Relays on NONE.  Prototype Mode."
    WriteLog(event)
    from platform_prototype import Platform

    platform = Platform(outpins, relay_trigger=relay_trigger)

# Check weather status
wx_status, errorcode = checkweather()
p_units = 'inches' if json_data_dict['wx_data']['units'] == 'F' else 'mm'
if errorcode != 0:
    event = "Weather Fetch Failed for some reason.  Bad API response?  Network Issue?"
else:
    event = ""
    if json_data_dict['wx_data']['temp_enable']:
        event += f"Current Temperature: {wx_status['temp_current']}{json_data_dict['wx_data']['units']} "
    if json_data_dict['wx_data']['history_enable']:
        event += f"Precipitation History: {wx_status['rain_history_total']} {p_units} "
    if json_data_dict['wx_data']['forecast_enable']:
        event += f"Precipitation Forecast: {wx_status['rain_forecast']} {p_units} "
    if event != "":
        WriteLog(event)

# Check if force run is enabled.  
if ((args.force == True)):
    force = True
    event = "Force run selected. Ignoring weather."
    WriteLog(event)
else:
    force = False

# Check weather flags
wx_cancel = False  # Set Weather Cancel to False 
wx_cancel_reason = ""

# Check rain history > precip max 
if (json_data_dict['wx_data']['history_enable']) and (
        wx_status['rain_history_total'] > json_data_dict['wx_data']['precip']):
    wx_cancel = True
    wx_cancel_reason += "(Precipitation History) "

# Check rain forecast > precip max 
if (json_data_dict['wx_data']['forecast_enable']) and (
        wx_status['rain_forecast'] > json_data_dict['wx_data']['precip']):
    wx_cancel = True
    wx_cancel_reason += "(Precipitation Forecast) "

# Check temperature exceeds limits 
if (json_data_dict['wx_data']['temp_enable']) and (
        (wx_status['temp_current'] < json_data_dict['wx_data']['min_temp']) or (
        wx_status['temp_current'] > json_data_dict['wx_data']['max_temp'])):
    wx_cancel = True
    wx_cancel_reason += "(Temperature) "

# Check rain forecast + history > precip max 
if (json_data_dict['wx_data']['forecast_history_enable']) and (
        wx_status['rain_forecast'] + wx_status['rain_history_total'] > json_data_dict['wx_data']['precip']):
    wx_cancel = True
    wx_cancel_reason += "(Precipitation Forecast + History) "

# *****************************************
# Main Program If / Else Tree
# *****************************************

if (init):
    event = "Initialize Relays Selected."
    WriteLog(event)
    errorcode = 0
# Schedule Run
elif ((schedule_run == True) and ((wx_cancel == False) or (force == True))):
    event = "Schedule Run Selected with Schedule: " + schedule_selected
    WriteLog(event)

    if (schedule_selected in json_data_dict['schedules']):
        event = schedule_selected + " found in JSON file. Running Now."
        WriteLog(event)
        json_data_dict['schedules'][schedule_selected]['start_time']['active'] = True  # Set Schedule active = True
        WriteJSON(json_data_dict, json_data_filename)
        for index_key, index_value in sorted(json_data_dict['schedules'][schedule_selected]['zones'].items()):
            if ((json_data_dict['zonemap'][index_key]['enabled'] == True) and (
                    index_value['duration'] != 0)):  # Check if zone enabled and has greater than 0 time
                json_data_dict['zonemap'][index_key]['active'] = True  # Set Zone Active = False
                WriteJSON(json_data_dict, json_data_filename)
                # Run Zone
                errorcode = Irrigate(platform, index_key, index_value['duration'], json_data_filename,
                                     relay_trigger=relay_trigger)
                # Read latest control data from JSON file (just in case anything changed)
                json_data_dict = ReadJSON(json_data_filename)
                json_data_dict['zonemap'][index_key]['active'] = False  # Set Zone Active = False
                WriteJSON(json_data_dict, json_data_filename)
        json_data_dict['schedules'][schedule_selected]['start_time']['active'] = False  # Set Schedule active = False
        WriteJSON(json_data_dict, json_data_filename)

    else:
        event = f"{schedule_selected} not found in JSON file.  Exiting Now."
        WriteLog(event)
        errorcode = 1
# Manual Run
elif ((schedule_run == False) and ((wx_cancel == False) or (force == True))):
    event = "Manual Run Selected."
    WriteLog(event)
    if (zone in json_data_dict['zonemap']):
        json_data_dict['zonemap'][zone]['active'] = True  # Set Zone Active = True
        WriteJSON(json_data_dict, json_data_filename)
        # Run Zone
        errorcode = Irrigate(platform, zone, duration, json_data_filename, relay_trigger=relay_trigger)
        json_data_dict['zonemap'][zone]['active'] = False  # Set Zone Active = False
        WriteJSON(json_data_dict, json_data_filename)
    else:
        event = f"{zone} not found in JSON file.  Exiting."
        WriteLog(event)
        errorcode = 1

# Weather Cancellation
elif (wx_cancel == True):
    event = f"Irrigation cancelled due to weather status exceeding limits. {wx_cancel_reason}"
    WriteLog(event)
    errorcode = 1

# Catch All Conditions
else:
    event = "No Action."
    WriteLog(event)
    errorcode = 0

# Cleanup GPIOs if on SBC
platform.cleanup()

# Write Result and exit
event = "Exiting with errorcode = " + str(errorcode)
WriteLog(event)
event = "***** Control Script Ended *****"
WriteLog(event)

# Flag Control Active at beginning of script
json_data_dict['controls']['active'] = False
json_data_dict['controls']['manual_override'] = False
WriteJSON(json_data_dict, json_data_filename)

exit()
