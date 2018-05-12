import getpass
import os
import socket
import select
import logging

try:
    import SocketServer
except ImportError:
    import socketserver as SocketServer

import sys
from optparse import OptionParser

import paramiko

SSH_PORT = 22
DEFAULT_PORT = 9001

class ForwardServer (SocketServer.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

class Handler (SocketServer.BaseRequestHandler):

    def handle(self):
        try:
            chan = self.ssh_transport.open_channel('direct-tcpip',
                                                   (self.chain_host, self.chain_port),
                                                   self.request.getpeername())
        except Exception as e:
            print('Incoming request to %s:%d failed: %s' % (self.chain_host,
                                                              self.chain_port,
                                                              repr(e)))
            return
        if chan is None:
            print('Incoming request to %s:%d was rejected by the SSH server.' %
                    (self.chain_host, self.chain_port))
            return

        print('Connected!  Tunnel open %r -> %r -> %r' % (self.request.getpeername(),
                                                            chan.getpeername(), (self.chain_host, self.chain_port)))

        while True:
            r, w, x = select.select([self.request, chan], [], [])
            if self.request in r:
                data = self.request.recv(1024)
                print data
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                print data
                if len(data) == 0:
                    break
                self.request.send(data)
                
        peername = self.request.getpeername()
        chan.close()
        self.request.close()
        print('Tunnel closed from %r' % (peername,))

class TunnelHelper(object):

    TUNNELS = {}

    @classmethod
    def forward_tunnel(cls, server_port, remote_host, remote_port, transport):
        # this is a little convoluted, but lets me configure things for the Handler
        # object.  (SocketServer doesn't give Handlers any way to access the outer
        # server normally.)
        class SubHander (Handler):
            chain_host = remote_host
            chain_port = remote_port
            ssh_transport = transport
        ForwardServer(('', server_port), SubHander).serve_forever()

    @classmethod
    def create_tunnel(
      cls,
      tunnel_host,
      tunnel_user,
      remote_host,
      remote_port,
      tunnel_port=None,
      tunnel_password=None,):

        tunnel_key = (remote_host, remote_port)

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())

        print('Connecting to ssh host %s:%d ...' % (tunnel_host, SSH_PORT))

        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(hostname=tunnel_host, port=SSH_PORT, username=tunnel_user, password=tunnel_password)
        except Exception as e:
            print('*** Failed to connect to %s:%d: %r' % (tunnel_host, SSH_PORT, e))
            sys.exit(1)

        print('Now forwarding port %d to %s:%d ...' % (tunnel_port, remote_host, remote_port))

        try:
            cls.forward_tunnel(tunnel_port, remote_host, remote_port, client.get_transport())
            cls.TUNNELS[tunnel_key] = (tunnel_host, tunnel_port, remote_host, remote_port)
        except KeyboardInterrupt:
            print('C-c: Port forwarding stopped.')
            sys.exit(0)


def get_host_port(spec, default_port):
    "parse 'hostname:22' into a host and port, with the port optional"
    args = (spec.split(':', 1) + [default_port])[:2]
    args[1] = int(args[1])
    return args[0], args[1]


def parse_options():
    HELP = """\
    Set up a forward tunnel across an SSH server, using paramiko. A local port
    (given with -p) is forwarded across an SSH session to an address:port from
    the SSH server. This is similar to the openssh -L option.
    """
    parser = OptionParser(usage='usage: %prog [options] <ssh-server>[:<server-port>]',
                          version='%prog 1.0', description=HELP)
    parser.add_option('-p', '--local-port', action='store', type='int', dest='port',
                      default=DEFAULT_PORT,
                      help='local port to forward (default: %d)' % DEFAULT_PORT)
    parser.add_option('-u', '--user', action='store', type='string', dest='user',
                      default=getpass.getuser(),
                      help='username for SSH authentication (default: %s)' % getpass.getuser())
    parser.add_option('-K', '--key', action='store', type='string', dest='keyfile',
                      default=None,
                      help='private key file to use for SSH authentication')
    parser.add_option('', '--no-key', action='store_false', dest='look_for_keys', default=True,
                      help='don\'t look for or use a private key file')
    parser.add_option('-P', '--password', action='store_true', dest='readpass', default=False,
                      help='read password (for key or password auth) from stdin')
    parser.add_option('-r', '--remote', action='store', type='string', dest='remote', default=None, metavar='host:port',
                      help='remote host and port to forward to')
    options, args = parser.parse_args()

    if len(args) != 1:
        parser.error('Incorrect number of arguments.')
    if options.remote is None:
        parser.error('Remote address required (-r).')
    
    server_host, server_port = get_host_port(args[0], SSH_PORT)
    remote_host, remote_port = get_host_port(options.remote, SSH_PORT)
    return options, (server_host, server_port), (remote_host, remote_port)


def main():
    logging.basicConfig(filename='test.log', level=logging.DEBUG)
    logger = logging.getLogger("my_log")
    options, server, remote = parse_options()
    
    password = None
    if options.readpass:
        password = getpass.getpass('Enter SSH password: ')
    
    TunnelHelper.create_tunnel(server[0], options.user, remote[0], remote[1], tunnel_port=options.port, tunnel_password=password)

if __name__ == '__main__':
    main()