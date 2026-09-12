#!/bin/bash
cd "$(dirname "$0")"
echo "Starting Asherfall... Logging output to crash.log"
python3 main.py 2>&1 | tee -a crash.log
EXIT_CODE=${PIPESTATUS[0]}
if [ $EXIT_CODE -ne 0 ]; then
    echo "======================================" | tee -a crash.log
    echo "GAME TERMINATED ABNORMALLY (Code: $EXIT_CODE)" | tee -a crash.log
    if [ $EXIT_CODE -eq 137 ] || [ $EXIT_CODE -eq 9 ]; then
        echo "CAUSE: The Operating System forcibly killed the game (SIGKILL)." | tee -a crash.log
        echo "This usually happens on macOS if the Terminal or App lacks Microphone permissions." | tee -a crash.log
    fi
    echo "======================================" | tee -a crash.log
fi
