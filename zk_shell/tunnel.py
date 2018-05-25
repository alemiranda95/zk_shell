import getpass
import socket
import select
import threading
import sys
import paramiko
from optparse import OptionParser

SSH_PORT = 22

class TunnelHelper(object):

    TUNNELS = {}

    #we initiate the remote socket and connect. we read from 2 data buffers: the remote socket
    #and the channel associated with the forwarded connection and we relay the data to each.
    #if there is no data, we close the socket and channel.
    @classmethod
    def handler(cls, chan, remote_host, remote_port):
        remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            remote_socket.connect((remote_host, remote_port))
        except:
            print("[!] Unable to establish tcp connection to %s:%d" % (remote_host, remote_port))
            sys.exit(1)

        print("[*] Established tcp connection to %s:%d" % (remote_host, remote_port))
        while True:
            r, w, x = select.select([remote_socket, chan], [], [])
            if remote_socket in r:
                data = remote_socket.recv(1024)
                if len(data) == 0:
                    break
                print("[*] Sending %d bytes via SSH channel" % (len(data)))
                print("[*] Data: ", data)
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                print("[*] Sending %d bytes via TPC Socket" % (len(data)))
                print("[*] Data: ", data)
                remote_socket.send(data)
        chan.close()
        remote_socket.close()
        print("[*] Tunnel connection is closed")

    #request port forwarding from server and open a session ssh channel.
    #forwarded connection will be picked up via the client transport's accept method
    #within the infinite loop.
    #thread will be spawned to handle the forwarded connection.
    @classmethod
    def forward_tunnel(cls, local_port, remote_host, remote_port, client_transport):
        print("[*] Starting reverse port forwarding")
        try:
            client_transport.request_port_forward("", local_port)
            client_transport.open_session()
        except paramiko.SSHException as err:
            print("[!] Unable to enable reverse port forwarding: ", str(err))
            sys.exit(1)
        print("[*] Started. Waiting for tcp connection on 127.0.0.1:%d from SSH server" % (local_port))
        while True:
            try:
                chan = client_transport.accept(60)
                if not chan:
                    continue
                thr = threading.Thread(target=cls.handler, args=(chan, remote_host, remote_port))
                thr.start()
            except KeyboardInterrupt:
                client_transport.cancel_port_forward("", local_port)
                client_transport.close()
                sys.exit(0)

    @classmethod
    def get_random_port(cls):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('localhost', 0))
        _, port = s.getsockname()
        s.close()
        return port

    @classmethod
    def acquire_host_pair(cls, port=None):
        port = port or cls.get_random_port()
        print port
        return port

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
        tunnel_port = cls.acquire_host_pair(tunnel_port)

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
                      help='local port to forward')
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
    options, server, remote = parse_options()
    
    password = None
    if options.readpass:
        password = getpass.getpass('Enter SSH password: ')
    
    TunnelHelper.create_tunnel(server[0], options.user, remote[0], remote[1], tunnel_port=options.port, tunnel_password=password)

if __name__ == '__main__':
    main()