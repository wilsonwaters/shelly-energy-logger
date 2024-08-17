# shelly-energy-logger
Log energy consumption and cost from Shelly devices to CSV file.

Example `energy-consumption-2024-08.csv`:

```
'Timestamp', 'Cumulative Energy Consumed (Wh)', 'Energy Consumed Last Period (Wh)', 'Cost'
2024-08-17 21:00:00, 22374.124, 0, 0
2024-08-17 22:00:00, 22375.412, 1.288, 0.000012
2024-08-17 23:00:00, 22376.596, 1.184, 0.000012
Total,,2.472,0.000024
```

This file is rotated monthly with a summary footer added with total energy consumed and the cost.

Timestamps are in localtime for the device which the script is running on.

Some use cases include
- Logging energy consumption of a electric vehicle charger for tax purposes
- more?

Tested with [Shelly Pro 1PM (gen 2 device)](https://www.shelly.com/en-au/products/shop/shelly-pro-1pm).

## Installing
- Ensure the Shelly device has latest firmware (tested with 1.4.0)
- Install the requests libraries
    - `pip install -r requirements.txt` (potentially in a virtual environment)
    - OR on linux `sudo apt install python3-responses python3-apscheduler`
- Edit variables at top of `shelly-energy-logger.py` as appropriate
- Run `python3 shelly-energy-logger.py`
- TODO: run as a service

## Development

This uses the [GetStatus API](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Shelly#shellygetstatus) for wider device support.
It may be better to use the [EnergyMonitor](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM) component but not all Shelly devices support this.


## Requirements
- requests - for http API access https://pypi.org/project/requests/
- apscheduler - for cron-like scheduling https://pypi.org/project/APScheduler/