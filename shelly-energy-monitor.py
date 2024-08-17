"""Log energy of Shelly gen 2 devices consumption to CSV file.

A CSV file is created to hold readings and includes a breakdown of energy consumption per period (default per hour). All time operates as localtime of the device this runs on.

Example:

```
'Timestamp', 'Cumulative Energy Consumed (Wh)', 'Energy Consumed Last Period (Wh)', 'Cost'
2024-08-17 21:00:00, 22374.124, 0, 0
2024-08-17 22:00:00, 22375.412, 1.288, 0
2024-08-17 23:00:00, 22376.596, 1.184, 0
```

This file is rotated monthly and is renamed appropriately.

Some use cases include
- Logging energy consumption of a electric vehicle charger for tax purposes
- more?

Tested with Shelly Pro 1PM. This uses the GetStatus API https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Shelly#shellygetstatus for wider device support.
It is also possible to use the EnergyMonitor component (https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM) for devices which this method is supported

# Installing
- Ensure the device has latest firmware (tested with 1.4.0)
- Install the requests library `pip install requests` (potentially in a virtual environment - `.\.venv\Scripts\activate `)


Requirements
- requests - for http API access https://pypi.org/project/requests/
- apscheduler - for cron-like scheduling https://pypi.org/project/APScheduler/

Copyright (c) Wilson Waters 2024.
"""
import requests
import csv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import os


SHELLY_API_BASE_URL = "http://pm1.alintech.com.au"
SHELLY_API_DEVICE_ID = "switch:0"
CSV_FILENAME = "energy-consumption.csv"
ENERGY_PRICE_PER_KWH = 0.315823
LOGGING_SCHEDULE_CRON = "0 * * * *" #every hour, on the hour

def query_current_energy():
    try:
        response = requests.get(SHELLY_API_BASE_URL+'/rpc/Shelly.GetStatus')
        response.raise_for_status()
        data = response.json()
        return data[SHELLY_API_DEVICE_ID]['aenergy']['total']
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None
    
def write_csv_header():
   with open(CSV_FILENAME, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Timestamp', 'Cumulative Energy Consumed (Wh)', 'Energy Consumed Last Period (Wh)', 'Cost Last Period'])

def write_csv_entry(timestamp, cumulative_energy, last_period_energy, last_period_cost):
    with open(CSV_FILENAME, mode='a', newline='') as file:
        writer = csv.writer(file)
        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S') # Uses local time
        cumulative_energy_str = f'{cumulative_energy:.3f}' # device provides 3dp of precision
        last_period_energy_str = f'{last_period_energy:.3f}'
        last_period_cost_str = f'{last_period_cost:.7f}' # 7dp of precision is equivalent in kwh is equivalent to 3dp in Wh
        writer.writerow([timestamp_str, cumulative_energy_str, last_period_energy_str, last_period_cost_str])

def read_last_period():
    last_line = None
    with open(CSV_FILENAME, "rb") as file:
        # Go to the end of the file before the last break-line
        file.seek(-2, os.SEEK_END) 
        # Keep reading backward until you find the next break-line
        while file.read(1) != b'\n':
            file.seek(-2, os.SEEK_CUR) 
        last_line = file.readline().decode()

    row = last_line.strip().split(',')
    if len(row) == 4:
        last_timestamp = datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        last_cumulative_energy = float(row[1])
        last_energy = float(row[2])
        last_cost = float(row[3])
        return last_timestamp, last_cumulative_energy, last_energy, last_cost
    else:
        raise Exception(f"Error reading csv line: {last_line}")

# returns the name of the rotated file if a rotation occurred    
def rotate_monthly_csv(timestamp, last_timestamp):
    current_month = timestamp.strftime('%Y-%m')
    last_month = last_timestamp.strftime('%Y-%m') if last_timestamp else None

    last_rotated_csv_filename = None
    if last_month != current_month:
        # rotate csv file
        if os.path.exists(CSV_FILENAME):
            last_rotated_csv_filename = f"{CSV_FILENAME[:-4]}-{datetime.datetime.now().strftime('%Y-%m')}.csv"
            os.rename(CSV_FILENAME, last_rotated_csv_filename)
            summarize_monthly_csv(last_rotated_csv_filename)
    return last_rotated_csv_filename

def summarize_monthly_csv(filename):
    total_energy = 0
    total_cost = 0

    with open(filename, mode='r') as file:
        reader = csv.reader(file)
        next(reader)  # skip header row
        for row in reader:
            energy = float(row[2])
            cost = float(row[3])
            total_energy += energy
            total_cost += cost

    # write footer row with sum of energy and cost
    with open(filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        total_energy_str = f'{total_energy:.3f}'
        total_cost_str = f'{total_cost:.7f}' # 7dp of precision is equivalent in kwh is equivalent to 3dp in Wh
        writer.writerow(['Total', '', total_energy_str, total_cost_str])

def handle_new_reading(timestamp, current_cumulative_energy):
    # Get last entry
    last_timestamp, last_cumulative_energy, last_period_energy = None, None, 0
    if os.path.exists(CSV_FILENAME):
        last_timestamp, last_cumulative_energy, last_energy, last_cost = read_last_period()
        last_period_energy = current_cumulative_energy - last_cumulative_energy

    # rotate csv on month end (add footer row with sum of energy and cost)
    last_rotated_csv_filename = rotate_monthly_csv(timestamp, last_timestamp)

    # if file doesn't exist, create it and write header
    if not os.path.exists(CSV_FILENAME):
        write_csv_header()
    
    # calculate cost of this period
    #TODO calculate cost of this period based on configurable tiered pricing
    last_period_cost = last_period_energy * ENERGY_PRICE_PER_KWH / 1000.0

    # write record
    write_csv_entry(timestamp, current_cumulative_energy, last_period_energy, last_period_cost)


def trigger_recording():
    print(f"Triggered recording at {datetime.datetime.now()}")
    timestamp = datetime.datetime.now()
    current_cumulative_energy = query_current_energy()
    if current_cumulative_energy is not None:
        handle_new_reading(timestamp, current_cumulative_energy)
    else:
        raise Exception(f"Error querying energy: {current_cumulative_energy}")

if __name__ == '__main__':
    scheduler = BlockingScheduler()
    job = scheduler.add_job(trigger_recording, CronTrigger.from_crontab(LOGGING_SCHEDULE_CRON))
    try:
        scheduler.start()
    except KeyboardInterrupt:
        scheduler.shutdown()

    # while True:
    #     try:
    #         response = requests.get(SHELLY_API_BASE_URL)
    #         response.raise_for_status()
    #         data = response.json()
    #         with open(CSV_FILENAME, mode='a') as file:
    #             writer = csv.writer(file)
    #             writer.writerow([datetime.datetime.now(), data['energy']])
    #     except requests.exceptions.RequestException as e:
    #         print(f"Error: {e}")
    #     time.sleep(60)