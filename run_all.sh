#!/bin/bash
# Start both HBlink4 server and dashboard
# Usage: ./run_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Create it first:${NC}"
    echo -e "${YELLOW}  python3 -m venv venv${NC}"
    echo -e "${YELLOW}  ./venv/bin/pip install -r requirements.txt -r requirements-dashboard.txt${NC}"
    exit 1
fi

# Neither program starts without its configuration, and the failure is much
# clearer said here than as a traceback two screens further down.
if [ ! -f "config/config.json" ]; then
    echo -e "${YELLOW}No config/config.json yet. Create it from the sample:${NC}"
    echo -e "${YELLOW}  cp config/config_sample.json config/config.json${NC}"
    echo -e "${YELLOW}Then change 'passphrase' from CHANGE-ME to a password of your choosing.${NC}"
    exit 1
fi

if grep -q '"passphrase": "CHANGE-ME"' config/config.json; then
    echo -e "${YELLOW}config/config.json still has the placeholder passphrase CHANGE-ME.${NC}"
    echo -e "${YELLOW}Repeaters will connect with it as-is, but anyone who has read the${NC}"
    echo -e "${YELLOW}sample config knows it. Set a real one before going live.${NC}"
    echo
fi

if [ ! -f "dashboard/config.json" ]; then
    echo -e "${YELLOW}No dashboard/config.json -- creating it from the sample.${NC}"
    cp dashboard/config_sample.json dashboard/config.json
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source venv/bin/activate

# Check if dashboard requirements are installed
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo -e "${YELLOW}Dashboard dependencies not found. Installing...${NC}"
    pip install -r requirements-dashboard.txt
fi

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Stopping services...${NC}"
    kill $(jobs -p) 2>/dev/null || true
    wait 2>/dev/null || true
    echo -e "${GREEN}All services stopped${NC}"
}

trap cleanup EXIT INT TERM

echo -e "${GREEN}Starting HBlink4 services...${NC}"
echo

# Start dashboard in background
echo -e "${BLUE}Starting Dashboard (bind/port from dashboard/config.json)...${NC}"
python3 run_dashboard.py &
DASHBOARD_PID=$!

# Give dashboard time to start
sleep 2

# Start HBlink4 server
echo -e "${BLUE}Starting HBlink4 server...${NC}"
python3 run_hblink.py config/config.json &
HBLINK_PID=$!

echo
echo -e "${GREEN}Services started:${NC}"
echo -e "  Dashboard: see 'web' section of dashboard/config.json (PID: $DASHBOARD_PID)"
echo -e "  HBlink4:   see 'global' bind/port in config/config.json (PID: $HBLINK_PID)"
echo
echo -e "${YELLOW}Press CTRL+C to stop all services${NC}"
echo

# Wait for processes
wait $HBLINK_PID $DASHBOARD_PID
