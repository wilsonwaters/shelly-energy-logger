"""Log energy consumption of Shelly gen 2 devices consumption to CSV file.

Copyright (c) Wilson Waters 2024.

Usage:
    python shelly-energy-logger.py --url http://192.168.1.100 --output living-room.csv
    python shelly-energy-logger.py --help

Configuration can be provided via command-line arguments or environment variables.
Command-line arguments take precedence over environment variables.
"""
import argparse
import requests
import csv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import os


# Default values
DEFAULT_DEVICE_ID = "switch:0"
DEFAULT_CSV_FILENAME = "energy-consumption.csv"
DEFAULT_ENERGY_PRICE = 0.315823
DEFAULT_CRON_SCHEDULE = "0 * * * *"


def parse_args():
    """Parse command-line arguments with environment variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Log energy consumption from Shelly Gen 2 devices to CSV files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  SHELLY_API_BASE_URL      Base URL of the Shelly device (e.g., http://192.168.1.100)
  SHELLY_API_DEVICE_ID     Device ID to query (default: switch:0)
  CSV_FILENAME             Output CSV filename (default: energy-consumption.csv)
  ENERGY_PRICE_PER_KWH     Energy price per kWh for cost calculation (default: 0.315823)
  LOGGING_SCHEDULE_CRON    Cron schedule for logging (default: "0 * * * *")

Examples:
  # Run with command-line arguments
  %(prog)s --url http://192.168.1.100 --output kitchen.csv

  # Run multiple instances for different devices
  %(prog)s --url http://192.168.1.100 --output living-room.csv &
  %(prog)s --url http://192.168.1.101 --output bedroom.csv &

  # Use environment variables
  SHELLY_API_BASE_URL=http://192.168.1.100 %(prog)s

  # Override price and schedule
  %(prog)s --url http://192.168.1.100 --price 0.25 --cron "*/30 * * * *"
"""
    )

    parser.add_argument(
        "-u", "--url",
        dest="base_url",
        default=os.environ.get("SHELLY_API_BASE_URL"),
        help="Base URL of the Shelly device (e.g., http://192.168.1.100). "
             "Can also be set via SHELLY_API_BASE_URL environment variable."
    )

    parser.add_argument(
        "-d", "--device-id",
        dest="device_id",
        default=os.environ.get("SHELLY_API_DEVICE_ID", DEFAULT_DEVICE_ID),
        help=f"Device ID to query (default: {DEFAULT_DEVICE_ID}). "
             "Can also be set via SHELLY_API_DEVICE_ID environment variable."
    )

    parser.add_argument(
        "-o", "--output",
        dest="csv_filename",
        default=os.environ.get("CSV_FILENAME", DEFAULT_CSV_FILENAME),
        help=f"Output CSV filename (default: {DEFAULT_CSV_FILENAME}). "
             "Can also be set via CSV_FILENAME environment variable."
    )

    parser.add_argument(
        "-p", "--price",
        dest="energy_price",
        type=float,
        default=float(os.environ.get("ENERGY_PRICE_PER_KWH", DEFAULT_ENERGY_PRICE)),
        help=f"Energy price per kWh for cost calculation (default: {DEFAULT_ENERGY_PRICE}). "
             "Can also be set via ENERGY_PRICE_PER_KWH environment variable."
    )

    parser.add_argument(
        "-c", "--cron",
        dest="cron_schedule",
        default=os.environ.get("LOGGING_SCHEDULE_CRON", DEFAULT_CRON_SCHEDULE),
        help=f"Cron schedule for logging (default: \"{DEFAULT_CRON_SCHEDULE}\" - every hour). "
             "Can also be set via LOGGING_SCHEDULE_CRON environment variable."
    )

    args = parser.parse_args()

    # Validate required arguments
    if not args.base_url:
        parser.error("--url is required (or set SHELLY_API_BASE_URL environment variable)")

    return args

def query_current_energy(config):
    try:
        response = requests.get(config.base_url + '/rpc/Shelly.GetStatus')
        response.raise_for_status()
        data = response.json()
        return data[config.device_id]['aenergy']['total']
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None

def write_csv_header(config):
   with open(config.csv_filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Timestamp', 'Cumulative Energy Consumed (Wh)', 'Energy Consumed Last Period (Wh)', 'Cost Last Period'])

def write_csv_entry(config, timestamp, cumulative_energy, last_period_energy, last_period_cost):
    with open(config.csv_filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S') # Uses local time
        cumulative_energy_str = f'{cumulative_energy:.3f}' # device provides 3dp of precision
        last_period_energy_str = f'{last_period_energy:.3f}'
        last_period_cost_str = f'{last_period_cost:.7f}' # 7dp of precision is equivalent in kwh is equivalent to 3dp in Wh
        writer.writerow([timestamp_str, cumulative_energy_str, last_period_energy_str, last_period_cost_str])

def read_last_period(config):
    last_line = None
    with open(config.csv_filename, "rb") as file:
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
def rotate_monthly_csv(config, timestamp, last_timestamp):
    current_month = timestamp.strftime('%Y-%m')
    last_month = last_timestamp.strftime('%Y-%m') if last_timestamp else None

    last_rotated_csv_filename = None
    if last_month != current_month:
        # rotate csv file
        if os.path.exists(config.csv_filename):
            last_rotated_csv_filename = f"{config.csv_filename[:-4]}-{datetime.datetime.now().strftime('%Y-%m')}.csv"
            os.rename(config.csv_filename, last_rotated_csv_filename)
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

def handle_new_reading(config, timestamp, current_cumulative_energy):
    # Get last entry
    last_timestamp, last_cumulative_energy, last_period_energy = None, None, 0
    if os.path.exists(config.csv_filename):
        last_timestamp, last_cumulative_energy, last_energy, last_cost = read_last_period(config)
        last_period_energy = current_cumulative_energy - last_cumulative_energy

    # rotate csv on month end (add footer row with sum of energy and cost)
    last_rotated_csv_filename = rotate_monthly_csv(config, timestamp, last_timestamp)

    # if file doesn't exist, create it and write header
    if not os.path.exists(config.csv_filename):
        write_csv_header(config)

    # calculate cost of this period
    #TODO calculate cost of this period based on configurable tiered pricing
    last_period_cost = last_period_energy * config.energy_price / 1000.0

    # write record
    write_csv_entry(config, timestamp, current_cumulative_energy, last_period_energy, last_period_cost)


def trigger_recording(config):
    print(f"Triggered recording at {datetime.datetime.now()} for {config.csv_filename}")
    timestamp = datetime.datetime.now()
    current_cumulative_energy = query_current_energy(config)
    if current_cumulative_energy is not None:
        handle_new_reading(config, timestamp, current_cumulative_energy)
    else:
        raise Exception(f"Error querying energy: {current_cumulative_energy}")


def main():
    config = parse_args()

    print("Starting Shelly Energy Logger")
    print(f"  Device URL: {config.base_url}")
    print(f"  Device ID: {config.device_id}")
    print(f"  Output file: {config.csv_filename}")
    print(f"  Energy price: {config.energy_price} per kWh")
    print(f"  Schedule: {config.cron_schedule}")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        trigger_recording,
        CronTrigger.from_crontab(config.cron_schedule),
        args=[config]
    )
    try:
        scheduler.start()
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == '__main__':
    main()