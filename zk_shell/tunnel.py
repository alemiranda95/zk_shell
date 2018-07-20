import getpass
import socket
import select
import threading
import sys
import time
import paramiko
import traceback
try:
    import SocketServer
except ImportError:
    import socketserver as SocketServer

SSH_PORT = 22

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
            print("[!] Unable to establish tcp connection to %s:%d -> %s" % (self.chain_host, self.chain_port), str(e))
            TunnelHelper.cancel_tunnel(self.chain_host, self.chain_port)
            return
        
        if chan is None:
            return

        while True:
            r, w, x = select.select([self.request, chan], [], [])
            if self.request in r:
                data = self.request.recv(10240)
                if len(data) != 0:
                    chan.send(data)
            if chan in r:
                data = chan.recv(10240)
                self.request.send(data)
                if len(data) == 0:
                    break
                
        peername = self.request.getpeername()
        chan.close()
        self.request.close()

class TunnelHelper(object):

    TUNNELS = {}

    @classmethod
    def forward_tunnel(cls, local_port, remote_host, remote_port, transport):
        class SubHander (Handler):
            chain_host = remote_host
            chain_port = int(remote_port)
            ssh_transport = transport

        server = ForwardServer(('', local_port), SubHander)
        cls.TUNNELS[(remote_host, remote_port)] = local_port, server
        server.serve_forever()
        server.server_close()

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
        return port

    @classmethod
    def create_tunnel(
      cls,
      remote_host,
      remote_port,
      tunnel_host='localhost',
      tunnel_port=None,
      tunnel_user=None,
      tunnel_password=None,):

        if not tunnel_password:
            tunnel_password = getpass.getpass('Enter SSH password: ')

        if not tunnel_user:
            tunnel_user = getpass.getuser()

        tunnel_key = (remote_host, remote_port)
        tunnel_port = cls.acquire_host_pair(tunnel_port)

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(hostname=tunnel_host, port=SSH_PORT, username=tunnel_user, password=tunnel_password)
        except Exception as e:
            print('*** Failed to connect to %s:%d: %r' % (tunnel_host, SSH_PORT, e))
            sys.exit(1)

        try:
            thr = threading.Thread(target=cls.forward_tunnel, args=(tunnel_port, remote_host, remote_port, client.get_transport()))
            thr.daemon = True
            thr.start()
        except Exception as e:
            print('*** Failed to forward port %d to %s:%d: %r' % (tunnel_port, remote_host, remote_port, e))
            sys.exit(1)

        return 'localhost', tunnel_port

    #cancels the thread that are running to maintain a specific tunnel open
    @classmethod
    def cancel_tunnel(cls, remote_host, remote_port):
        if cls.TUNNELS[(remote_host, remote_port)]:
            _, server = cls.TUNNELS[(remote_host, remote_port)]
            server.shutdown()
            cls.TUNNELS[(remote_host, remote_port)] = None