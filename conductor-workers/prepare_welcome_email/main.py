import time
import logging

from conductor.ConductorWorker import ConductorWorker

logging.getLogger().setLevel(logging.INFO)

# conductor input:
#   tenant_name
#   username
def prepare_welcome_email(task):
        logging.info('prepare_welcome_email')
        tenant = task['inputData']['tenant_name']
        user = task['inputData']['username']

        title = 'Welcome to Mender'
        body = 'Your organization {} has been created, your login: {}'.format(tenant, user)

        # GOTCHA must return all these fields
        # on errors: return 'status: FAILED'
        return {'status': 'COMPLETED',
                'output': {
                    'email': user,
                    'title': title,
                    'body': body
                    },
                'logs': []}

def main():
    logging.info('starting prepare_welcome_email worker')
    cc = ConductorWorker('http://mender-conductor:8080/api', 1, 0.1)

    # this actually just starts polling for work - this is *not* starting a task, see ConductorWorker.py
    cc.start('prepare_welcome_email', prepare_welcome_email, True)

if __name__ == '__main__':
    # GOTCHA conductor takes a looong time to actually start
    # ('depends_on' doesn't help much)
    time.sleep(20)

    main()
