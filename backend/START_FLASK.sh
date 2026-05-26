#!/bin/bash
# Clean Flask startup script

echo "Starting FairTax Backend..."
echo "=================================="

# Kill any existing Flask processes
pkill -f "python app.py" 2>/dev/null || true
sleep 2

# Make sure we're in the right directory
cd /c/Users/user/Desktop/fairtax/latest/backend

# Start Flask on port 5000
echo "Flask starting on http://localhost:5000"
echo "Press Ctrl+C to stop"
echo "=================================="

python app.py
