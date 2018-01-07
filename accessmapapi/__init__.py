'''The flask application package.'''
from flask import Flask
import logging
import os
import time
import threading
from accessmapapi import network_handlers


# Set up the app
def create_app():
    app = Flask(__name__)

    # Set up the configuration data
    if 'PEDDATADIR' in os.environ:
        datadir = os.environ['PEDDATADIR']
    else:
        datadir = os.path.join(os.path.dirname(__file__), '../data')
        datadir = os.path.abspath(datadir)
    app.config['PEDDATADIR'] = datadir

    # To get debugging messages:
    app.config['PROPAGATE_EXCEPTIONS'] = True

    # Set up logging
    formatter = logging.Formatter(
        '[%(levelname)s] %(message)s'
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    # CORS responses
    # FIXME: re-enable CORS soon
    @app.after_request
    def after_request(response):
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers",
                             "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET")
        return response

    def initialize():
        while True:
            havesw = os.path.exists(os.path.join(datadir, 'sidewalks.geojson'))
            havecr = os.path.exists(os.path.join(datadir, 'crossings.geojson'))
            if havesw and havecr:
                break
            app.logger.info('No input data, checking again in 2 seconds...')
            time.sleep(2)

        network_handlers.get_G(app)

    # Initialize data
    thread = threading.Thread(name='read_data', target=initialize)
    thread.start()

    return app

app = create_app()


import accessmapapi.views  # noqa: F401
