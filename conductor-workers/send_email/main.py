import time
import logging

from conductor.ConductorWorker import ConductorWorker

logging.getLogger().setLevel(logging.INFO)

# conductor input:
#   email
#   title
#   body
def send_email(task):
    logging.info('send_email')
    logging.info('sending to %s:', task['inputData']['email'])
    logging.info('title %s:', task['inputData']['title'])
    logging.info('body %s:', task['inputData']['body'])

    # GOTCHA must return all these fields
    return {'status': 'COMPLETED', 'output': {}, 'logs': []}

def main():
    logging.info('starting send_email worker')
    cc = ConductorWorker('http://mender-conductor:8080/api', 1, 0.1)

    # this actually just starts polling for work - this is *not* starting a task, see ConductorWorker.py
    cc.start('send_email', send_email, True)

if __name__ == '__main__':
    # GOTCHA conductor takes a looong time to actually start
    # ('depends_on' doesn't help much)
    time.sleep(20)

    main()
