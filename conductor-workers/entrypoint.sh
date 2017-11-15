#!bin/sh

# we have 2 binaries to run simultaneously
# move 1 of them  to the background

# background
python3 /usr/bin/mender/send_email/main.py &

# foreground
python3 /usr/bin/mender/prepare_welcome_email/main.py
