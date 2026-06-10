import subprocess


def get_system_stats() -> str:
  """
    Executes shell commands to retrieve GPU/CPU usage and temperatures,
    returning the results as a formatted string.
    """
  # Define the precise shell command
  cmd = ("echo '=== GPU METRICS ===' && "
         "nvidia-smi --query-gpu=memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits | "
         "awk '{print \"VRAM Usage: \" $1 \"MB / \" $2 \"MB\\nGPU Temp:   \" $3 \"°C\"}' && "
         "echo -e '\\n=== CPU METRICS ===' && "
         "free -h | awk '/Mem:/ {print \"RAM Usage:  \" $3 \" / \" $2}' && "
         "sensors 2>/dev/null | awk '/Package id 0:|Core 0:|Tctl/ {print \"CPU Temp:   \" $2; exit}'")

  try:
    # Run the command in the shell and capture the standard output
    result = subprocess.run(cmd, shell=True, check=True, text=True, capture_output=True)
    return result.stdout.strip()
  except subprocess.CalledProcessError as e:
    return f"Error executing commands: {e.stderr}"

