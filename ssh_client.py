"""SSH/SCP client for Cloudio - file uploads via scp."""

import os
import subprocess


class SSHClient:
    def __init__(self, server):
        self.server = server
        self._env = os.environ.copy()
        if server.get('auth_type') == 'password' and server.get('password'):
            self._env['SSHPASS'] = server['password']

    def _auth_prefix(self):
        if self.server.get('auth_type') == 'password' and self.server.get('password'):
            return ['sshpass', '-e']
        return []

    def _common_opts(self):
        return ['-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10']

    def _key_opts(self):
        if self.server.get('auth_type') == 'key':
            return ['-i', os.path.expanduser(self.server['key_path'])]
        return []

    def _target(self):
        return f"{self.server['user']}@{self.server['host']}"

    def _port_ssh(self):
        port = self.server.get('port', 22)
        return ['-p', str(port)] if port != 22 else []

    def _port_scp(self):
        port = self.server.get('port', 22)
        return ['-P', str(port)] if port != 22 else []

    def ssh_run(self, remote_cmd):
        """Run a command on the remote server. Returns stdout."""
        cmd = (self._auth_prefix() + ['ssh'] + self._common_opts()
               + self._key_opts() + self._port_ssh()
               + [self._target()] + remote_cmd)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, env=self._env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or 'SSH command failed')
        return result.stdout.strip()

    def upload(self, local_path, remote_path):
        """Upload a file via scp. Blocks until complete."""
        cmd = (self._auth_prefix() + ['scp'] + self._common_opts()
               + self._key_opts() + self._port_scp()
               + [local_path, f"{self._target()}:{remote_path}"])
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, env=self._env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or 'SCP upload failed')
