from datetime import datetime
import tzlocal


def get_current_time_with_timezone():
  # Automatically detect the server's local timezone object
  local_tz = tzlocal.get_localzone()

  # Get the current time in that timezone
  now = datetime.now(local_tz)

  # Format the date and time
  time_str = now.strftime("%Y-%m-%d %H:%M:%S %A")

  # local_tz.key returns the string representation (e.g., 'Asia/Kolkata')
  tz_string = local_tz.key

  return f"{time_str} Timezone: {tz_string}"

