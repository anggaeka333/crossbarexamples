# -*- coding: utf-8 -*-

from __future__ import division

import socket

import requests
import psutil

from autobahn.twisted.wamp import Application
from autobahn.twisted.util import sleep

from twisted.internet.defer import inlineCallbacks

def to_gib(bytes, factor=2**30, suffix="GiB"):
    """ Convert a number of bytes to Gibibytes

        Ex : 1073741824 bytes = 1073741824/2**30 = 1GiB
    """
    return "%0.2f%s" % (bytes / factor, suffix)

def get_stats(filters={}):
    """ Returns the current values for CPU/memory/disk usage.

        These values are returned as a dict such as:

            {
                'cpus': ['x%', 'y%', etc],
                'memory': "z%",
                'disk':{
                    '/partition/1': 'x/y (z%)',
                    '/partition/2': 'x/y (z%)',
                    etc
                }
            }

        The filter parameter is a dict such as:

            {'cpus': bool, 'memory':bool, 'disk':bool}

        It's used to decide to include or not values for the 3 types of
        ressources.
    """

    results = {}

    if (filters.get('show_cpus', True)):
        results['cpus'] = tuple("%s%%" % x for x in psutil.cpu_percent(percpu=True))

    if (filters.get('show_memory', True)):
        memory = psutil.phymem_usage()
        results['memory'] = '{used}/{total} ({percent}%)'.format(
            used=to_gib(memory.active),
            total=to_gib(memory.total),
            percent=memory.percent
        )

    if (filters.get('show_disk', True)):
        disks = {}
        for device in psutil.disk_partitions():
            usage = psutil.disk_usage(device.mountpoint)
            disks[device.mountpoint] = '{used}/{total} ({percent}%)'.format(
                used=to_gib(usage.used),
                total=to_gib(usage.total),
                percent=usage.percent
            )
        results['disks'] = disks

    return results

# We create the WAMP client.
app = Application('monitoring')

# This is my machine's public IP since
# this client must be able to reach my server
# from the outside. You should change this value
# to the IP of the machine you put Crossbar.io
# and Django.
SERVER = '192.168.0.104'

# First, we use a trick to know the public IP for this
# machine.
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("8.8.8.8", 80))
# We attach a dict to the app, so that its
# reference is accessible from anywhere.
app._params = {'name': socket.gethostname(), 'ip': s.getsockname()[0]}
s.close()


@app.signal('onjoined')
@inlineCallbacks
def called_on_joinded():
    """ Loop sending the state of this machine using WAMP every x seconds.

        This function is executed when the client joins the router, which
        means it's connected and authenticated, ready to send WAMP messages.
    """
    # Then we make a POST request to the server to notify it we are active
    # and to retrieve the configuration values for our client.
    app._params.update(requests.post('http://' + SERVER + ':8080/clients/',
                                    data={'ip': app._params['ip']}).json())


    # The we loop for ever.
    while True:
        # Every time we loop, we get the stats for our machine
        stats = {'ip': app._params['ip'], 'name': app._params['name']}
        stats.update(get_stats(app._params))

        # If we are requested to send the stats, we publish them using WAMP.
        if not app._params['disabled']:
            app.session.publish('clientstats', stats)

        # Then we wait. Thanks to @inlineCallbacks, using yield means we
        # won't block here, so our client can still listen to WAMP events
        # and react to them.
        yield sleep(app._params['frequency'])


# We subscribe to the "clientconfig" WAMP event.
@app.subscribe('clientconfig.' + app._params['ip'])
def update_configuration(args):
    """ Update the client configuration when Django asks for it. """
    app._params.update(args)


# We start our client.
if __name__ == '__main__':
    app.run(url="ws://%s:8080/ws" % SERVER)
