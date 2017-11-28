#!/usr/bin/env python
"""A noddy fake smtp server."""

import smtpd
import asyncore

class FakeSMTPServer(smtpd.SMTPServer):
    """A Fake smtp server"""

    def __init__(self, *args, **kwargs):
        print "Running fake smtp server"
        self.recieved = False
        smtpd.SMTPServer.__init__(self, *args, **kwargs)

    def process_message(self, *args, **kwargs):
        print("recieved message:")
        print(args)
        print(kwargs)
        self.recieved = True

if __name__ == "__main__":
    smtp_server = FakeSMTPServer(('localhost', 25), None)
    try:
        asyncore.loop()
    except KeyboardInterrupt:
        smtp_server.close()