"""
	NOTE: To run the test, tunnel.py must be in the same directory
"""
import socket
import threading
import unittest
import subprocess
import sys
import os
try:
	from tunnel import TunnelHelper
except ImportError:
	from zk_shell.tunnel import TunnelHelper

STOP = False
PORT = None


def listen_local_port():
	"""
	Keaps a thread listening to incoming connections in PORT
	"""
	l = []
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.bind(('', PORT))
	s.listen(1)
	while not STOP:
		(c, a) = s.accept()
		l.append(c)
	s.close()

class TestTunnel(unittest.TestCase):

	@classmethod
	def setUpClass(cls):
		"""
		Obtains a free port to be forwarded
		"""
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.bind(('', 0))
		global PORT
		PORT = s.getsockname()[1]
		s.close()

	@classmethod
	def tearDownClass(cls):
		"""
		Stops the thread listening to incoming connections in PORT
		"""
		global STOP
		STOP = True
		command = "nc -zw3 localhost %s && echo \"True\" || echo >&2 \"False\"" % (str(PORT))
		subprocess.check_output([command], shell=True)

	def test_get_random_port(self):
		"""
		Test the obtainment of free random port
		"""
		command = "netstat -nat | awk \'{print $4}\' | sed -e \'s/.*://\'"
		ports = subprocess.check_output([command], shell=True).split()

		port = TunnelHelper.get_random_port()
		self.assertNotIn(str(port), ports)

	def test_create_cancel_local_tunnel(self):
		"""
		Test creation of a local tunnel
		"""
		thr = threading.Thread(target=listen_local_port)
		thr.start()

		passwd = os.environ['TUNNEL_TEST_PASSWORD']
		rhost, rport = TunnelHelper.create_tunnel('localhost', PORT, tunnel_password=passwd)
		command = "nc -zw3 localhost %s && echo \"True\" || echo \"False\"" % (str(rport))
		forwarded = subprocess.check_output([command], shell=True).rstrip()

		self.assertEqual(forwarded, 'True')

		"""
		Test cancelation of the local tunnel created
		"""	
		if forwarded == 'True':
			TunnelHelper.cancel_tunnel('localhost', PORT)
			forwarded = subprocess.check_output([command], shell=True).rstrip()
			self.assertEqual(forwarded, 'False')

	def test_create_cancel_remote_tunnel(self):
		"""
		Test creation of a remote tunnel
		"""
		passwd = os.environ['TUNNEL_TEST_PASSWORD']
		rhost, rport = TunnelHelper.create_tunnel('www.google.com', 80, tunnel_password=passwd)
		command = "nc -zw3 localhost %s && echo \"True\" || echo \"False\"" % (str(rport))
		forwarded = subprocess.check_output([command], shell=True).rstrip()

		self.assertEqual(forwarded, 'True')

		"""
		Test cancelation of the remote tunnel created
		"""	
		if forwarded == 'True':
			TunnelHelper.cancel_tunnel('www.google.com', 80)
			forwarded = subprocess.check_output([command], shell=True).rstrip()
			self.assertEqual(forwarded, 'False')


if __name__ == '__main__':
	unittest.main()


