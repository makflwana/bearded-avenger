#!/usr/bin/env python

import json
import logging
import os.path
import sys
import textwrap
from argparse import ArgumentParser, RawDescriptionHelpFormatter
import traceback
import zmq
from zmq.eventloop import ioloop

import cif.hunter
from cifsdk.client.zeromq import ZMQ as Client
from cif.constants import HUNTER_ADDR, ROUTER_ADDR
from cifsdk.utils import setup_logging, get_argument_parser, setup_signals, read_config
from csirtg_indicator import Indicator

TOKEN = os.environ.get('CIF_TOKEN', None)
TOKEN = os.environ.get('CIF_HUNTER_TOKEN', TOKEN)
CONFIG_PATH = os.environ.get('CIF_HUNTER_CONFIG_PATH', os.path.join(os.getcwd(), 'cif-hunter.yml'))
if not os.path.isfile(CONFIG_PATH):
    CONFIG_PATH = os.path.join(os.path.expanduser('~'), 'cif-hunter.yml')


class Hunter(object):

    def handle_message(self, s, e):
        self.logger.info('handling message...')
        m = s.recv_multipart()
        m = json.loads(m[0])

        self.logger.debug(m)

        m = Indicator(**m)

        for p in self.plugins:
            try:
                p.process(m, self.router)
            except Exception as e:
                self.logger.error(e)
                traceback.print_exc()

    def __init__(self, remote=HUNTER_ADDR, router=ROUTER_ADDR, token=TOKEN, loop=ioloop.IOLoop.instance(), *args,
                 **kvargs):

        self.logger = logging.getLogger(__name__)
        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.SUB)
        if sys.version_info > (3,):
            self.socket.setsockopt_string(zmq.SUBSCRIBE, '')
        else:
            self.socket.setsockopt(zmq.SUBSCRIBE, '')
        self.loop = loop
        self.loop.add_handler(self.socket, self.handle_message, zmq.POLLIN)

        self.plugins = []

        import pkgutil
        self.logger.debug('loading plugins...')
        for loader, modname, is_pkg in pkgutil.iter_modules(cif.hunter.__path__, 'cif.hunter.'):
            p = loader.find_module(modname).load_module(modname)
            self.plugins.append(p.Plugin(*args, **kvargs))
            self.logger.debug('plugin loaded: {}'.format(modname))

        self.hunters = remote

        self.router = Client(remote=router, token=token)

    def start(self):
        self.logger.debug('connecting to {}'.format(self.hunters))
        self.socket.connect(self.hunters)
        self.logger.debug('starting loop...')
        self.loop.start()
        self.logger.debug('started..')

    def stop(self):
        self.loop.stop()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        return self


def main():
    p = get_argument_parser()
    p = ArgumentParser(
        description=textwrap.dedent('''\
        example usage:
            $ cif-hunter -d
        '''),
        formatter_class=RawDescriptionHelpFormatter,
        prog='cif-hunter',
        parents=[p],
    )

    p.add_argument('--remote', help="cif-router hunter address [default %(default)s]", default=HUNTER_ADDR)
    p.add_argument('--router', help='cif-router front end address [default %(default)s]', default=ROUTER_ADDR)
    p.add_argument('--token', help='specify cif-hunter token [default %(default)s]', default=TOKEN)
    p.add_argument('--config', default=CONFIG_PATH)

    args = p.parse_args()
    setup_logging(args)

    o = read_config(args)
    options = vars(args)
    for v in options:
        if options[v] is None:
            options[v] = o.get(v)

    logger = logging.getLogger(__name__)
    logger.info('loglevel is: {}'.format(logging.getLevelName(logger.getEffectiveLevel())))

    setup_signals(__name__)

    with Hunter(remote=options.get('remote'), router=args.router, token=options.get('token')) as h:
        try:
            logger.info('starting up...')
            h.start()
        except KeyboardInterrupt:
            logging.info("shutting down...")
            h.stop()

if __name__ == "__main__":
    main()