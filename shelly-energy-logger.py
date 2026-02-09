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
import json
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import datetime
import os


# Device type configurations: maps device type to (device_id, energy_field)
DEVICE_CONFIGS = {
    "pm1-pro": ("switch:0", "aenergy.total"),
    "em50": ("em1data:0", "total_act_energy"),
    "em50:1": ("em1data:1", "total_act_energy"),  # Second channel of EM50
}

# Default values
DEFAULT_DEVICE_TYPE = "pm1-pro"
DEFAULT_CSV_FILENAME = "energy-consumption.csv"
DEFAULT_ENERGY_PRICE = 0.323719
DEFAULT_CRON_SCHEDULE = "0 * * * *"


def parse_args():
    """Parse command-line arguments with environment variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Log energy consumption from Shelly Gen 2 devices to CSV files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported device types: pm1-pro (default), em50, em50:1

Environment Variables:
  SHELLY_API_BASE_URL      Base URL of the Shelly device (e.g., http://192.168.1.100)
  SHELLY_DEVICE_TYPE       Device type (default: pm1-pro)
  CSV_FILENAME             Output CSV filename (default: energy-consumption.csv)
  ENERGY_PRICE_PER_KWH     Energy price per kWh for cost calculation (default: 0.323719)
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
        "-d", "--device",
        dest="device_type",
        default=os.environ.get("SHELLY_DEVICE_TYPE", DEFAULT_DEVICE_TYPE),
        choices=list(DEVICE_CONFIGS.keys()),
        help=f"Device type (default: {DEFAULT_DEVICE_TYPE}). "
             f"Supported: {', '.join(DEVICE_CONFIGS.keys())}. "
             "Can also be set via SHELLY_DEVICE_TYPE environment variable."
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

    parser.add_argument(
        "-t", "--tariff-config",
        dest="tariff_config_file",
        default=os.environ.get("TARIFF_CONFIG_FILE"),
        help="Path to JSON file with time-of-day tariff configuration. "
             "When provided, --price is ignored and costs are calculated based on time periods. "
             "Can also be set via TARIFF_CONFIG_FILE environment variable."
    )

    args = parser.parse_args()

    # Validate required arguments
    if not args.base_url:
        parser.error("--url is required (or set SHELLY_API_BASE_URL environment variable)")

    # Set device_id and energy_field based on device type
    args.device_id, args.energy_field = DEVICE_CONFIGS[args.device_type]

    # Load tariff configuration if specified
    args.tariff_config = None
    if args.tariff_config_file:
        args.tariff_config = load_tariff_config(args.tariff_config_file)
        validate_cron_covers_boundaries(args.cron_schedule, args.tariff_config)

    return args


def load_tariff_config(config_file):
    """Load and validate tariff configuration from JSON file."""
    with open(config_file, 'r') as f:
        config = json.load(f)

    # Validate required fields
    if 'periods' not in config:
        raise ValueError("Tariff config must contain 'periods' array")

    for i, period in enumerate(config['periods']):
        for field in ['name', 'start', 'end', 'rate']:
            if field not in period:
                raise ValueError(f"Tariff period {i} missing required field: {field}")
        # Validate time format
        try:
            datetime.datetime.strptime(period['start'], '%H:%M')
            datetime.datetime.strptime(period['end'], '%H:%M')
        except ValueError:
            raise ValueError(f"Tariff period {i} has invalid time format (expected HH:MM)")

    return config


def get_tariff_boundaries(tariff_config):
    """Extract all unique boundary times (hours) from tariff periods."""
    boundaries = set()
    for period in tariff_config['periods']:
        start_hour = int(period['start'].split(':')[0])
        boundaries.add(start_hour)
    return sorted(boundaries)


def get_cron_hours(cron_schedule):
    """Get all hours when a cron schedule fires within a 24-hour period."""
    trigger = CronTrigger.from_crontab(cron_schedule)

    # Simulate a full day to find all firing times (use timezone-aware datetimes)
    tz = datetime.timezone.utc
    base_date = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=tz)
    end_date = datetime.datetime(2024, 1, 2, 0, 0, 0, tzinfo=tz)

    hours = set()
    current = base_date
    while current < end_date:
        next_fire = trigger.get_next_fire_time(None, current)
        if next_fire is None or next_fire >= end_date:
            break
        hours.add(next_fire.hour)
        current = next_fire + datetime.timedelta(seconds=1)

    return sorted(hours)


def validate_cron_covers_boundaries(cron_schedule, tariff_config):
    """Validate that cron schedule fires at all tariff boundary times."""
    boundaries = get_tariff_boundaries(tariff_config)
    cron_hours = get_cron_hours(cron_schedule)

    missing = [h for h in boundaries if h not in cron_hours]
    if missing:
        missing_times = [f"{h:02d}:00" for h in missing]
        raise ValueError(
            f"Cron schedule '{cron_schedule}' does not fire at tariff boundary times: {', '.join(missing_times)}. "
            f"This would cause incorrect cost calculations. "
            f"Required boundaries: {', '.join(f'{h:02d}:00' for h in boundaries)}"
        )


def is_time_in_period(current_time, start_str, end_str):
    """Check if current_time falls within a tariff period (handles overnight periods)."""
    start = datetime.datetime.strptime(start_str, '%H:%M').time()
    end = datetime.datetime.strptime(end_str, '%H:%M').time()

    if start <= end:
        # Normal period (e.g., 09:00 to 15:00)
        return start <= current_time < end
    else:
        # Overnight period (e.g., 23:00 to 06:00)
        return current_time >= start or current_time < end


def get_tariff_rate(timestamp, tariff_config, fallback_price):
    """Return the $/kWh rate for the given timestamp based on tariff config."""
    if tariff_config is None:
        return fallback_price

    current_time = timestamp.time()
    for period in tariff_config['periods']:
        if is_time_in_period(current_time, period['start'], period['end']):
            return period['rate']

    raise ValueError(f"No tariff period found for time {current_time}")

def get_nested_value(data, path):
    """Navigate nested dict using dot-separated path (e.g., 'aenergy.total')."""
    keys = path.split('.')
    value = data
    for key in keys:
        value = value[key]
    return value


def query_current_energy(config):
    try:
        response = requests.get(config.base_url + '/rpc/Shelly.GetStatus')
        response.raise_for_status()
        data = response.json()
        device_data = data[config.device_id]
        return get_nested_value(device_data, config.energy_field)
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None
    except KeyError as e:
        print(f"Error accessing energy data: {e}. Check --device option matches your Shelly device type.")
        return None

def write_csv_header(config):
   with open(config.csv_filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Timestamp', 'Cumulative Energy Consumed (Wh)', 'Energy Consumed Last Period (Wh)', 'Rate ($/kWh)', 'Cost Last Period'])

def write_csv_entry(config, timestamp, cumulative_energy, last_period_energy, rate, last_period_cost):
    with open(config.csv_filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S') # Uses local time
        cumulative_energy_str = f'{cumulative_energy:.3f}' # device provides 3dp of precision
        last_period_energy_str = f'{last_period_energy:.3f}'
        rate_str = f'{rate:.6f}'
        last_period_cost_str = f'{last_period_cost:.7f}' # 7dp of precision is equivalent in kwh is equivalent to 3dp in Wh
        writer.writerow([timestamp_str, cumulative_energy_str, last_period_energy_str, rate_str, last_period_cost_str])

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
    if len(row) == 5:
        last_timestamp = datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        last_cumulative_energy = float(row[1])
        last_energy = float(row[2])
        last_rate = float(row[3])
        last_cost = float(row[4])
        return last_timestamp, last_cumulative_energy, last_energy, last_rate, last_cost
    else:
        raise Exception(f"Error reading csv line (expected 5 columns): {last_line}")

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
            cost = float(row[4])
            total_energy += energy
            total_cost += cost

    # write footer row with sum of energy and cost
    with open(filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        total_energy_str = f'{total_energy:.3f}'
        total_cost_str = f'{total_cost:.7f}' # 7dp of precision is equivalent in kwh is equivalent to 3dp in Wh
        writer.writerow(['Total', '', total_energy_str, '', total_cost_str])

def handle_new_reading(config, timestamp, current_cumulative_energy):
    # Get last entry
    last_timestamp, last_cumulative_energy, last_period_energy = None, None, 0
    if os.path.exists(config.csv_filename):
        last_timestamp, last_cumulative_energy, last_energy, last_rate, last_cost = read_last_period(config)
        last_period_energy = current_cumulative_energy - last_cumulative_energy

    # rotate csv on month end (add footer row with sum of energy and cost)
    last_rotated_csv_filename = rotate_monthly_csv(config, timestamp, last_timestamp)

    # if file doesn't exist, create it and write header
    if not os.path.exists(config.csv_filename):
        write_csv_header(config)

    # calculate rate and cost of this period based on tariff config or flat rate
    rate = get_tariff_rate(timestamp, config.tariff_config, config.energy_price)
    last_period_cost = last_period_energy * rate / 1000.0

    # write record
    write_csv_entry(config, timestamp, current_cumulative_energy, last_period_energy, rate, last_period_cost)


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
    print(f"  Device type: {config.device_type} (id: {config.device_id}, field: {config.energy_field})")
    print(f"  Output file: {config.csv_filename}")
    if config.tariff_config:
        tariff_name = config.tariff_config.get('name', 'Unnamed tariff')
        print(f"  Tariff: {tariff_name} (time-of-use pricing)")
        for period in config.tariff_config['periods']:
            print(f"    {period['name']}: {period['start']}-{period['end']} @ ${period['rate']:.4f}/kWh")
    else:
        print(f"  Energy price: ${config.energy_price} per kWh (flat rate)")
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