# shelly-energy-logger
Log energy consumption and cost from Shelly devices to CSV file.

A CSV file is created to hold readings and includes a breakdown of energy consumption per period (default per hour). All time operates as localtime of the device this runs on.

Example:

```
'Timestamp', 'Cumulative Energy Consumed (Wh)', 'Energy Consumed Last Period (Wh)', 'Cost'
2024-08-17 21:00:00, 22374.124, 0, 0
2024-08-17 22:00:00, 22375.412, 1.288, 0.000012
2024-08-17 23:00:00, 22376.596, 1.184, 0.000012
```

This file is rotated monthly with a summary footer added.

Some use cases include
- Logging energy consumption of a electric vehicle charger for tax purposes
- more?

Tested with Shelly Pro 1PM (gen 2 device). This uses the GetStatus API https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Shelly#shellygetstatus for wider device support.
It is also possible to use the EnergyMonitor component (https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM) for devices which this method is supported

# Installing
- Ensure the device has latest firmware (tested with 1.4.0)
- Install the requests libraries `pip install -r requirements.txt` (potentially in a virtual environment - `.\.venv\Scripts\activate `)
- TODO: run as a service


Requirements
- requests - for http API access https://pypi.org/project/requests/
- apscheduler - for cron-like scheduling https://pypi.org/project/APScheduler/